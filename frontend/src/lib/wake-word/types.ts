import type { PcmFrame } from "@/lib/audio/pcm";

export type WakeWordLabel = "wake";

export interface WakeWordManifest {
  schemaVersion: "1.0";
  modelVersion: string;
  modelPath: string;
  sha256: string;
  melspectrogramPath: string;
  melspectrogramSha256: string;
  embeddingPath: string;
  embeddingSha256: string;
  license: "LicenseRef-VIVI-Academic-Only";
  trainingRunId: string;
  evaluationReportPath: string;
  sampleRate: 16000;
  windowSamples: 32000;
  hopSamples: number;
  labels: readonly ["wake", "non_wake"];
  threshold: number;
  refractoryMs: number;
  /**
   * "mean_pooled_softmax" (default): this project's own classifier head --
   * every embedding window in the capture is mean-pooled into one [1, 96]
   * vector, then a 2-class [wake, non_wake] softmax head scores it.
   * "sequence_sigmoid": openWakeWord's own per-wakeword model contract (e.g.
   * hey_jarvis_v0.1.onnx) -- the last `sequenceLength` embedding windows are
   * fed *unpooled* as a [1, sequenceLength, 96] sequence, and the model
   * outputs a single already-sigmoided [1, 1] wake probability. No
   * non_wake class exists in this mode.
   */
  architecture?: "mean_pooled_softmax" | "sequence_sigmoid";
  sequenceLength?: number;
}

export interface WakeDetection {
  label: WakeWordLabel;
  score: number;
  modelVersion: string;
  throughSequence: number;
  generation: number;
}

export interface WakeWordDetector {
  load(): Promise<WakeWordManifest>;
  resume(
    generation: number,
    onDetection: (detection: WakeDetection) => void,
    onError: (message: string) => void,
  ): void;
  accept(frame: PcmFrame): void;
  pause(): void;
  dispose(): void;
}

export type WorkerIn =
  | {
      type: "load";
      manifest: WakeWordManifest;
      melspectrogramBytes: ArrayBuffer;
      embeddingBytes: ArrayBuffer;
      classifierBytes: ArrayBuffer;
      generation: number;
    }
  | { type: "infer"; pcm: Float32Array; throughSequence: number; generation: number }
  | { type: "pause"; generation: number }
  | { type: "dispose"; generation: number };

export type WorkerOut =
  | { type: "ready"; generation: number }
  | { type: "detection"; detection: WakeDetection }
  /**
   * Sent once the worker has finished all inference work it currently holds.
   * The detector uses it as backpressure: it never posts a new window while one
   * is outstanding. Without it the worker fell arbitrarily far behind live audio
   * (measured 5.4 s), because it is handed a window every `hopSamples` (100 ms of
   * audio) while one inference takes longer than that, and its synchronous WASM
   * run blocks the worker thread so queued messages could only be dispatched --
   * one full inference each -- after it unblocked. Dropping stale work inside the
   * worker cannot fix that; the backlog has to never be created.
   */
  | { type: "idle"; generation: number }
  | { type: "error"; message: string; generation: number };
