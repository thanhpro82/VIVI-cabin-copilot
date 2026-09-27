/// <reference lib="webworker" />
import * as ort from "onnxruntime-web/wasm";
import type { WakeDetection, WakeWordManifest, WorkerIn, WorkerOut } from "./types";
import { meanPool } from "./pooling";

export interface WakeWordWorkerHost {
  postMessage(message: WorkerOut): void;
  close(): void;
}

const EMBEDDING_WINDOW_FRAMES = 76;
const EMBEDDING_DIM = 96;
const EMBEDDING_WINDOW_STEP_FRAMES = 8;

/**
 * Rescales normalized float32 PCM (the browser audio pipeline's established
 * convention -- see frontend/src/lib/audio/pcm.ts's encodePcm16Wav, which
 * clamps to [-1, 1] and encodes with the same asymmetric int16 scale used
 * below) to int16-magnitude float32 values.
 *
 * openwakeword.utils.AudioFeatures._get_melspectrogram hard-rejects
 * anything but exact np.int16 dtype, so the melspectrogram model was only
 * ever trained/evaluated against int16-scale magnitudes -- see
 * scripts/wake_word/train.py's _window_pcm (`np.clip(pcm, -32768,
 * 32767).astype(np.int16)`) and the now-fixed scripts/wake_word/evaluate.py
 * _build_three_session_infer's `infer` closure, which does the identical
 * clip-and-cast immediately before calling AudioFeatures. Feeding the
 * melspectrogram session normalized ([-1, 1]) PCM instead silently produces
 * a feature distribution the model was never trained on -- measured cosine
 * similarity against the trained-on distribution was only ~0.980 with the
 * transform and stride-8 fixes already applied, well short of parity.
 */
function toInt16ScalePcm(pcm: Float32Array): Float32Array {
  const scaled = new Float32Array(pcm.length);
  for (let index = 0; index < pcm.length; index += 1) {
    const clamped = Math.max(-1, Math.min(1, pcm[index]));
    // Truncate to match Python training's `.astype(np.int16)`, which hard-truncates
    // rather than rounds -- without this, the frontend fed fractional int16-scale
    // values where training saw exact integers (a sub-LSB parity gap).
    scaled[index] = Math.trunc(clamped < 0 ? clamped * 32768 : clamped * 32767);
  }
  return scaled;
}

function stableSoftmax(logits: readonly number[]): number[] {
  if (!logits.length || logits.some((value) => !Number.isFinite(value))) {
    throw new Error("Wake-word model logits must be finite");
  }
  const max = Math.max(...logits);
  const exponents = logits.map((value) => Math.exp(value - max));
  const total = exponents.reduce((sum, value) => sum + value, 0);
  if (!Number.isFinite(total) || total <= 0) throw new Error("Wake-word softmax denominator was invalid");
  const scores = exponents.map((value) => value / total);
  if (scores.some((score) => !Number.isFinite(score))) throw new Error("Wake-word softmax scores were invalid");
  return scores;
}

/** Creates the protocol handler separately so its safety gates are unit-testable. */
export function createWakeWordWorker(runtime: typeof ort, host: WakeWordWorkerHost) {
  runtime.env.wasm.numThreads = 1;
  runtime.env.wasm.proxy = false;
  runtime.env.wasm.wasmPaths = "/ort-wasm/";

  let melspecSession: ort.InferenceSession | null = null;
  let embeddingSession: ort.InferenceSession | null = null;
  let classifierSession: ort.InferenceSession | null = null;
  let manifest: WakeWordManifest | null = null;
  let latestGeneration = -1;
  let disposed = false;
  let lastDetectionAt = Number.NEGATIVE_INFINITY;

  const output = (message: WorkerOut) => host.postMessage(message);

  const infer = async (message: Extract<WorkerIn, { type: "infer" }>) => {
    if (disposed || !melspecSession || !embeddingSession || !classifierSession || !manifest || message.generation < latestGeneration)
      return;
    latestGeneration = message.generation;

    const pcmInt16Scale = toInt16ScalePcm(message.pcm);
    const melspecResult = await melspecSession.run({
      input: new runtime.Tensor("float32", pcmInt16Scale, [1, pcmInt16Scale.length]),
    });
    const melspecOutput = Object.values(melspecResult)[0];
    if (!melspecOutput) throw new Error("Melspectrogram model produced no output");
    // The real vendored melspectrogram.onnx returns (1, 1, frames, melBins)
    // for a chunked input -- batch and channel are singleton dims at [0]
    // and [1]. The frame count lives at dims[2], not dims[0] (which is
    // always 1). Reading dims[0] here made every inference throw "shorter
    // than the embedding window" against the real model.
    const totalFrames = melspecOutput.dims[2];
    const melDim = melspecOutput.dims[melspecOutput.dims.length - 1];
    if (totalFrames < EMBEDDING_WINDOW_FRAMES) throw new Error("Melspectrogram output is shorter than the embedding window");

    // openWakeWord's AudioFeatures._get_melspectrogram applies this exact
    // elementwise transform (melspec_transform = lambda x: x/10 + 2) before
    // the melspectrogram is ever windowed for the embedding model. Skipping
    // it feeds the embedding model a feature distribution it was never
    // trained on -- measured cosine similarity against the trained-on
    // distribution was only 0.9459 without this transform, vs 0.9999999
    // with it (see scripts/wake_word/evaluate.py's _build_three_session_infer).
    const rawMelData = melspecOutput.data as Float32Array;
    const melData = new Float32Array(rawMelData.length);
    for (let index = 0; index < rawMelData.length; index += 1) {
      melData[index] = rawMelData[index] / 10 + 2;
    }

    // openWakeWord's AudioFeatures._get_embeddings strides sliding embedding
    // windows by step_size=8 frames, not every frame position. Only every
    // 8th window is actually extracted and embedded during training.
    const numWindows = Math.floor((totalFrames - EMBEDDING_WINDOW_FRAMES) / EMBEDDING_WINDOW_STEP_FRAMES) + 1;
    const embeddingBatch = new Float32Array(numWindows * EMBEDDING_DIM);
    for (let windowIndex = 0; windowIndex < numWindows; windowIndex += 1) {
      const startFrame = windowIndex * EMBEDDING_WINDOW_STEP_FRAMES;
      const windowFrames = new Float32Array(EMBEDDING_WINDOW_FRAMES * melDim);
      windowFrames.set(melData.subarray(startFrame * melDim, (startFrame + EMBEDDING_WINDOW_FRAMES) * melDim));
      const embeddingResult = await embeddingSession.run({
        input_1: new runtime.Tensor("float32", windowFrames, [1, EMBEDDING_WINDOW_FRAMES, melDim, 1]),
      });
      const embeddingOutput = Object.values(embeddingResult)[0];
      if (!embeddingOutput) throw new Error("Embedding model produced no output");
      embeddingBatch.set(embeddingOutput.data as Float32Array, windowIndex * EMBEDDING_DIM);
    }

    if (message.generation !== latestGeneration || disposed) return;

    let label: "wake";
    let score: number;
    if (manifest.architecture === "sequence_sigmoid") {
      const sequenceLength = manifest.sequenceLength ?? 16;
      // openWakeWord's own per-wakeword models (e.g. hey_jarvis_v0.1.onnx) score
      // a *sequence* of the most recent embedding windows, unpooled -- not the
      // mean-pooled single vector this project's own head expects. Zero-pad the
      // front on the (normally unreachable, since windowSamples already yields
      // >= sequenceLength windows) case of a short first inference.
      const sequence = new Float32Array(sequenceLength * EMBEDDING_DIM);
      const availableWindows = Math.min(sequenceLength, numWindows);
      const sourceStart = (numWindows - availableWindows) * EMBEDDING_DIM;
      const destStart = (sequenceLength - availableWindows) * EMBEDDING_DIM;
      sequence.set(embeddingBatch.subarray(sourceStart, sourceStart + availableWindows * EMBEDDING_DIM), destStart);
      const inputName = classifierSession.inputNames[0];
      if (!inputName) throw new Error("Wake-word classifier session has no declared input");
      const classifierResult = await classifierSession.run({
        [inputName]: new runtime.Tensor("float32", sequence, [1, sequenceLength, EMBEDDING_DIM]),
      });
      if (message.generation !== latestGeneration || disposed) return;
      const scoreOutput = Object.values(classifierResult)[0];
      if (!scoreOutput || (scoreOutput.data as Float32Array).length !== 1) {
        throw new Error("Wake-word sequence classifier output must be a single score");
      }
      score = (scoreOutput.data as Float32Array)[0];
      if (!Number.isFinite(score)) throw new Error("Wake-word prediction score was invalid");
      if (score < manifest.threshold) return;
      label = "wake";
    } else {
      const pooled = meanPool(embeddingBatch, numWindows, EMBEDDING_DIM);
      const classifierResult = await classifierSession.run({ embedding: new runtime.Tensor("float32", pooled, [1, EMBEDDING_DIM]) });
      if (message.generation !== latestGeneration || disposed) return;

      const logitsOutput = classifierResult.logits;
      if (!logitsOutput || logitsOutput.dims.length !== 2 || logitsOutput.dims[0] !== 1 || logitsOutput.dims[1] !== 2) {
        throw new Error("Wake-word classifier logits must have shape [1, 2]");
      }
      const logits = Array.from(logitsOutput.data as Float32Array);
      if (logits.length !== 2) throw new Error("Wake-word classifier logits must have shape [1, 2]");
      const scores = stableSoftmax(logits);
      if (!manifest.labels.includes("non_wake")) throw new Error("Wake-word manifest is missing the non_wake label");
      let labelIndex = 0;
      for (let index = 1; index < scores.length; index += 1) {
        if (scores[index] > scores[labelIndex]) labelIndex = index;
      }
      const predictedLabel = manifest.labels[labelIndex];
      const predictedScore = scores[labelIndex];
      if (!predictedLabel || !Number.isFinite(predictedScore)) throw new Error("Wake-word prediction index was invalid");
      const nonWakeScore = scores[manifest.labels.indexOf("non_wake")];
      if (predictedLabel === "non_wake" || predictedScore <= nonWakeScore || predictedScore < manifest.threshold) return;
      if (predictedLabel !== "wake") throw new Error("Wake-word prediction label was invalid");
      label = predictedLabel;
      score = predictedScore;
    }
    const now = Date.now();
    if (now - lastDetectionAt < manifest.refractoryMs) return;
    lastDetectionAt = now;
    const detection: WakeDetection = {
      label,
      score,
      modelVersion: manifest.modelVersion,
      throughSequence: message.throughSequence,
      generation: message.generation,
    };
    output({ type: "detection", detection });
  };

  /**
   * Runs at most one inference at a time and keeps only the NEWEST window that arrived
   * while it was busy, dropping the rest.
   *
   * The detector posts a full `windowSamples` window every `hopSamples` (100 ms of
   * audio). One inference is a melspectrogram pass, `numWindows` embedding-model passes
   * and a classifier pass, single-threaded in WASM -- routinely slower than the 100 ms
   * it is handed work at. Awaiting each message in arrival order therefore let the
   * backlog grow without bound, and detection latency grew with it: by the time a wake
   * surfaced, the live microphone had moved on, so command capture recorded silence
   * (every frame RMS 0.00000), found no speech, and discarded the turn. Wake detection
   * only ever wants the freshest window, so stale ones are dropped rather than queued.
   */
  let inferRunning = false;
  let queuedInfer: Extract<WorkerIn, { type: "infer" }> | null = null;

  const runInferCoalesced = async (message: Extract<WorkerIn, { type: "infer" }>): Promise<void> => {
    if (inferRunning) {
      queuedInfer = message;
      return;
    }
    inferRunning = true;
    try {
      let next: Extract<WorkerIn, { type: "infer" }> | null = message;
      while (next) {
        await infer(next);
        next = queuedInfer;
        queuedInfer = null;
      }
    } finally {
      inferRunning = false;
      // Tells the detector it may send the next window. Emitted even on failure,
      // otherwise one thrown inference would wedge detection off permanently.
      if (!disposed) output({ type: "idle", generation: message.generation });
    }
  };

  return async (message: WorkerIn): Promise<void> => {
    if (message.generation < latestGeneration) return;
    try {
      if (message.type === "load") {
        latestGeneration = message.generation;
        disposed = false;
        lastDetectionAt = Number.NEGATIVE_INFINITY;
        const loadedMelspec = await runtime.InferenceSession.create(message.melspectrogramBytes, { executionProviders: ["wasm"] });
        const loadedEmbedding = await runtime.InferenceSession.create(message.embeddingBytes, { executionProviders: ["wasm"] });
        const loadedClassifier = await runtime.InferenceSession.create(message.classifierBytes, { executionProviders: ["wasm"] });
        if (message.generation !== latestGeneration || disposed) return;
        manifest = message.manifest;
        melspecSession = loadedMelspec;
        embeddingSession = loadedEmbedding;
        classifierSession = loadedClassifier;
        output({ type: "ready", generation: message.generation });
      } else if (message.type === "infer") {
        await runInferCoalesced(message);
      } else if (message.type === "pause") {
        latestGeneration = message.generation;
      } else {
        latestGeneration = message.generation;
        disposed = true;
        melspecSession = null;
        embeddingSession = null;
        classifierSession = null;
        manifest = null;
        host.close();
      }
    } catch (error) {
      if (message.generation >= latestGeneration && !disposed) {
        output({ type: "error", message: error instanceof Error ? error.message : "Wake-word worker failed", generation: message.generation });
      }
    }
  };
}

if (typeof self !== "undefined") {
  const handle = createWakeWordWorker(ort, self);
  self.onmessage = (event: MessageEvent<WorkerIn>) => {
    void handle(event.data);
  };
}
