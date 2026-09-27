import { describe, expect, it, vi } from "vitest";
import { createWakeWordWorker } from "./wakeWord.worker";
import type { WakeWordManifest, WorkerIn, WorkerOut } from "./types";

const manifest: WakeWordManifest = {
  schemaVersion: "1.0",
  modelVersion: "test-model",
  modelPath: "/models/wake-word/model.onnx",
  sha256: "a".repeat(64),
  melspectrogramPath: "/models/wake-word/melspectrogram.onnx",
  melspectrogramSha256: "c".repeat(64),
  embeddingPath: "/models/wake-word/embedding_model.onnx",
  embeddingSha256: "d".repeat(64),
  license: "LicenseRef-VIVI-Academic-Only",
  trainingRunId: "test-run",
  evaluationReportPath: "/models/wake-word/eval.md",
  sampleRate: 16_000,
  windowSamples: 32_000,
  hopSamples: 1_600,
  labels: ["wake", "non_wake"],
  threshold: 0.8,
  refractoryMs: 1_000,
};

function loadMessage(
  generation: number,
  configuredManifest: WakeWordManifest = manifest,
): Extract<WorkerIn, { type: "load" }> {
  return {
    type: "load",
    manifest: configuredManifest,
    melspectrogramBytes: new ArrayBuffer(1),
    embeddingBytes: new ArrayBuffer(1),
    classifierBytes: new ArrayBuffer(1),
    generation,
  };
}

function inferMessage(generation: number): Extract<WorkerIn, { type: "infer" }> {
  return { type: "infer", pcm: new Float32Array(32_000), throughSequence: 7, generation };
}

/**
 * Mirrors the REAL vendored melspectrogram.onnx output shape for a
 * 32000-sample (2-second) input: (1, 1, 197, 32). Batch and channel are
 * singleton dims at [0]/[1]; the frame count (197) is at dims[2], and the
 * mel-bin count (32) is at dims[dims.length - 1]. 197 frames comfortably
 * clears the 76-frame embedding window either way this fixture is read, so
 * earlier revisions of this file used dims=[76, 1, 1, 32] instead -- a
 * shape that accidentally made a dims[0]-reading bug look correct. Using
 * the real shape here is what actually exercises that bug.
 */
const MELSPEC_FRAMES = 197;
const MELSPEC_BINS = 32;
const MELSPEC_DIMS = [1, 1, MELSPEC_FRAMES, MELSPEC_BINS];

function workerWith(classifierLogits: number[], dims = [1, 2]) {
  const output: WorkerOut[] = [];
  const host = { postMessage: (message: WorkerOut) => output.push(message), close: vi.fn() };
  const melspecSession = {
    run: vi.fn(async () => ({
      output: { data: new Float32Array(MELSPEC_FRAMES * MELSPEC_BINS), dims: MELSPEC_DIMS },
    })),
  };
  const embeddingSession = {
    run: vi.fn(async () => ({ conv2d_19: { data: new Float32Array(96), dims: [1, 1, 1, 96] } })),
  };
  const classifierSession = {
    run: vi.fn(async () => ({ logits: { data: Float32Array.from(classifierLogits), dims } })),
  };
  let createCallCount = 0;
  const sessionsInOrder = [melspecSession, embeddingSession, classifierSession];
  const runtime = {
    env: { wasm: { numThreads: 0, proxy: true, wasmPaths: "" } },
    Tensor: class {
      constructor(..._args: unknown[]) {}
    },
    InferenceSession: { create: vi.fn(async () => sessionsInOrder[createCallCount++]) },
  };
  return {
    handler: createWakeWordWorker(runtime as never, host),
    output,
    host,
    runtime,
    melspecSession,
    embeddingSession,
    classifierSession,
  };
}

describe("wake-word worker", () => {
  it("rejects logits whose declared dimensions are not [1, 2]", async () => {
    const worker = workerWith([12, 0], [2]);
    await worker.handler(loadMessage(3));
    await worker.handler(inferMessage(3));

    expect(worker.output.filter((m) => m.type !== "idle").at(-1)).toMatchObject({ type: "error", generation: 3, message: expect.stringMatching(/shape/i) });
  });

  it.each([[Infinity, 0], [-Infinity, -Infinity], [Number.NaN, 0]])(
    "rejects non-finite logits %j without emitting a detection",
    async (...logits: number[]) => {
      const worker = workerWith(logits);
      await worker.handler(loadMessage(3));
      await worker.handler(inferMessage(3));

      expect(worker.output.some((message) => message.type === "detection")).toBe(false);
      expect(worker.output.filter((m) => m.type !== "idle").at(-1)).toMatchObject({ type: "error", generation: 3, message: expect.stringMatching(/finite/i) });
    },
  );

  it("ignores a stale load so it cannot replace the active model", async () => {
    const worker = workerWith([12, 0]);
    await worker.handler(loadMessage(5));
    await worker.handler(loadMessage(4));
    await worker.handler(inferMessage(5));

    expect(worker.runtime.InferenceSession.create).toHaveBeenCalledTimes(3);
    expect(worker.output.filter((message) => message.type === "ready")).toEqual([{ type: "ready", generation: 5 }]);
    expect(worker.output.filter((m) => m.type !== "idle").at(-1)).toMatchObject({ type: "detection", detection: { generation: 5, label: "wake" } });
  });

  it("ignores a stale dispose so it cannot close the active worker", async () => {
    const worker = workerWith([12, 0]);
    await worker.handler(loadMessage(5));
    await worker.handler({ type: "dispose", generation: 4 });
    await worker.handler(inferMessage(5));

    expect(worker.host.close).not.toHaveBeenCalled();
    expect(worker.output.filter((m) => m.type !== "idle").at(-1)).toMatchObject({ type: "detection", detection: { generation: 5, label: "wake" } });
  });

  it("rejects a dominant non_wake score even though the wake score alone clears the threshold", async () => {
    const worker = workerWith([0, 0.5]);
    await worker.handler(loadMessage(3, { ...manifest, threshold: 0.1 }));
    await worker.handler(inferMessage(3));

    expect(worker.output.some((message) => message.type === "detection")).toBe(false);
  });

  it("rejects an exact tie between wake and non_wake scores", async () => {
    const worker = workerWith([0, 0]);
    await worker.handler(loadMessage(3, { ...manifest, threshold: 0.1 }));
    await worker.handler(inferMessage(3));

    expect(worker.output.some((message) => message.type === "detection")).toBe(false);
  });

  it("sends the melspectrogram session a [1, pcm.length] tensor", async () => {
    const worker = workerWith([12, 0]);
    await worker.handler(loadMessage(3));
    await worker.handler(inferMessage(3));

    expect(worker.melspecSession.run).toHaveBeenCalledTimes(1);
  });

  it("reads the total frame count from dims[2], not dims[0], of the real (1, 1, frames, melBins) output", async () => {
    // Regression test for the melspectrogram axis bug: dims[0] is the
    // singleton batch dim (always 1) on the real vendored model, which is
    // far smaller than the 76-frame embedding window and would make every
    // inference throw "shorter than the embedding window" before the
    // embedding session is ever called.
    const worker = workerWith([12, 0]);
    await worker.handler(loadMessage(3));
    await worker.handler(inferMessage(3));

    expect(worker.output.filter((m) => m.type !== "idle").at(-1)).not.toMatchObject({ type: "error" });
    expect(worker.embeddingSession.run).toHaveBeenCalled();
  });

  it("strides embedding windows by 8 frames, not 1, matching openWakeWord's step_size=8", async () => {
    // Regression test: openWakeWord's AudioFeatures._get_embeddings uses
    // step_size=8 with window_size=76. With 197 total frames the correct
    // window count is floor((197 - 76) / 8) + 1 = 16. A naive stride-1
    // implementation would instead compute 197 - 76 + 1 = 122 windows and
    // call the embedding session 122 times -- feeding it a feature
    // distribution the classifier head was never trained on.
    const worker = workerWith([12, 0]);
    await worker.handler(loadMessage(3));
    await worker.handler(inferMessage(3));

    expect(worker.embeddingSession.run).toHaveBeenCalledTimes(16);
  });

  it("applies the value/10 + 2 melspectrogram transform before windowing", async () => {
    // Regression test: openWakeWord's AudioFeatures._get_melspectrogram
    // default transform is `lambda x: x/10 + 2`. Fill the fake
    // melspectrogram output with a known constant and assert the embedding
    // session receives the transformed value, not the raw one.
    const RAW_MEL_VALUE = 40;
    const output: WorkerOut[] = [];
    const host = { postMessage: (message: WorkerOut) => output.push(message), close: vi.fn() };
    const melspecSession = {
      run: vi.fn(async () => ({
        output: { data: new Float32Array(MELSPEC_FRAMES * MELSPEC_BINS).fill(RAW_MEL_VALUE), dims: MELSPEC_DIMS },
      })),
    };
    class RecordingTensor {
      args: unknown[];
      constructor(...args: unknown[]) {
        this.args = args;
      }
    }
    const embeddingSession = {
      run: vi.fn(async (_input: { input_1: RecordingTensor }) => ({
        conv2d_19: { data: new Float32Array(96), dims: [1, 1, 1, 96] },
      })),
    };
    const classifierSession = {
      run: vi.fn(async () => ({ logits: { data: Float32Array.from([12, 0]), dims: [1, 2] } })),
    };
    let createCallCount = 0;
    const sessionsInOrder = [melspecSession, embeddingSession, classifierSession];
    const runtime = {
      env: { wasm: { numThreads: 0, proxy: true, wasmPaths: "" } },
      Tensor: RecordingTensor,
      InferenceSession: { create: vi.fn(async () => sessionsInOrder[createCallCount++]) },
    };
    const handler = createWakeWordWorker(runtime as never, host);
    await handler(loadMessage(3));
    await handler(inferMessage(3));

    expect(embeddingSession.run).toHaveBeenCalled();
    const firstCallArgs = embeddingSession.run.mock.calls[0][0];
    const windowData = firstCallArgs.input_1.args[1] as Float32Array;
    const expectedTransformed = RAW_MEL_VALUE / 10 + 2;
    expect(windowData[0]).toBeCloseTo(expectedTransformed);
    expect(windowData[0]).not.toBeCloseTo(RAW_MEL_VALUE);
  });

  it("rescales normalized [-1, 1] PCM to int16 magnitude before the melspectrogram session sees it", async () => {
    // Regression test: openwakeword.utils.AudioFeatures._get_melspectrogram
    // hard-rejects anything but exact np.int16 dtype, so the melspectrogram
    // model was only ever trained/evaluated against int16-scale magnitudes
    // (train.py's _window_pcm: `np.clip(pcm, -32768, 32767).astype(np.int16)`;
    // evaluate.py's fixed infer closure does the identical clip-and-cast).
    // This repo's browser audio pipeline (frontend/src/lib/audio/pcm.ts)
    // normalizes PCM to [-1, 1] as its established convention, so the worker
    // must rescale before calling the melspec session -- passing normalized
    // floats through unchanged silently feeds the model a distribution it
    // was never trained on.
    const NORMALIZED_PCM_VALUE = 0.5;
    const output: WorkerOut[] = [];
    const host = { postMessage: (message: WorkerOut) => output.push(message), close: vi.fn() };
    class RecordingTensor {
      args: unknown[];
      constructor(...args: unknown[]) {
        this.args = args;
      }
    }
    const melspecSession = {
      run: vi.fn(async (_input: { input: RecordingTensor }) => ({
        output: { data: new Float32Array(MELSPEC_FRAMES * MELSPEC_BINS), dims: MELSPEC_DIMS },
      })),
    };
    const embeddingSession = {
      run: vi.fn(async () => ({ conv2d_19: { data: new Float32Array(96), dims: [1, 1, 1, 96] } })),
    };
    const classifierSession = {
      run: vi.fn(async () => ({ logits: { data: Float32Array.from([12, 0]), dims: [1, 2] } })),
    };
    let createCallCount = 0;
    const sessionsInOrder = [melspecSession, embeddingSession, classifierSession];
    const runtime = {
      env: { wasm: { numThreads: 0, proxy: true, wasmPaths: "" } },
      Tensor: RecordingTensor,
      InferenceSession: { create: vi.fn(async () => sessionsInOrder[createCallCount++]) },
    };
    const handler = createWakeWordWorker(runtime as never, host);
    await handler(loadMessage(3));
    const pcm = new Float32Array(32_000).fill(NORMALIZED_PCM_VALUE);
    await handler({ type: "infer", pcm, throughSequence: 7, generation: 3 });

    expect(melspecSession.run).toHaveBeenCalled();
    const firstCallArgs = melspecSession.run.mock.calls[0][0];
    const sentPcm = firstCallArgs.input.args[1] as Float32Array;
    expect(sentPcm[0]).toBe(Math.trunc(NORMALIZED_PCM_VALUE * 32767));
    expect(sentPcm[0]).not.toBeCloseTo(NORMALIZED_PCM_VALUE);
  });
});
