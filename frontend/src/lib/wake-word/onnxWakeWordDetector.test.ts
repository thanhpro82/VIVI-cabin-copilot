import { afterEach, describe, expect, it, vi } from "vitest";
import { createOnnxWakeWordDetector } from "./onnxWakeWordDetector";
import type { WakeWordManifest, WorkerIn, WorkerOut } from "./types";

const manifest: WakeWordManifest = {
  schemaVersion: "1.0",
  modelVersion: "2026.08.16",
  modelPath: "/models/wake-word/model.onnx",
  sha256: "3".repeat(64),
  melspectrogramPath: "/models/wake-word/melspectrogram.onnx",
  melspectrogramSha256: "1".repeat(64),
  embeddingPath: "/models/wake-word/embedding_model.onnx",
  embeddingSha256: "2".repeat(64),
  license: "LicenseRef-VIVI-Academic-Only",
  trainingRunId: "wake-word-2026-08-16",
  evaluationReportPath: "/models/wake-word/evaluation.md",
  sampleRate: 16_000,
  windowSamples: 32_000,
  hopSamples: 1_600,
  labels: ["wake", "non_wake"],
  threshold: 0.8,
  refractoryMs: 1_000,
};

class FakeWorker {
  onmessage: ((event: MessageEvent<WorkerOut>) => void) | null = null;
  onerror: ((event: ErrorEvent) => void) | null = null;
  readonly sent: WorkerIn[] = [];
  terminated = false;

  postMessage(message: WorkerIn): void {
    this.sent.push(message);
    if (message.type === "load") this.emit({ type: "ready", generation: message.generation });
  }

  terminate(): void {
    this.terminated = true;
  }

  emit(message: WorkerOut): void {
    this.onmessage?.({ data: message } as MessageEvent<WorkerOut>);
  }
}

function response(body: unknown): Response {
  return new Response(typeof body === "string" ? body : JSON.stringify(body), { status: 200 });
}

function modelResponse(byte: number): Response {
  return new Response(new Uint8Array([byte]), { status: 200 });
}

/** Good-path digests: hex "1"x64 / "2"x64 / "3"x64, matching the manifest's three checksums in fetch order. */
function goodDigestSequence(): ArrayBuffer[] {
  return [new Uint8Array(32).fill(0x11).buffer, new Uint8Array(32).fill(0x22).buffer, new Uint8Array(32).fill(0x33).buffer];
}

function detectorWith(worker: FakeWorker, digestSequence: ArrayBuffer[] = goodDigestSequence()) {
  // Four responses in order: manifest, then melspectrogram, embedding, classifier bytes -- matching loadModel's fetch order.
  const responses = [response(manifest), modelResponse(1), modelResponse(2), modelResponse(3)];
  let callIndex = 0;
  const fetchImpl: typeof fetch = vi.fn(async () => responses[callIndex++] ?? response(manifest));
  const digest = vi.fn(async () => digestSequence.shift() ?? new Uint8Array(32).buffer);
  return {
    detector: createOnnxWakeWordDetector({ fetchImpl, workerFactory: () => worker, digest }),
    fetchImpl,
    digest,
  };
}

afterEach(() => vi.restoreAllMocks());

describe("OnnxWakeWordDetector", () => {
  it.each([
    ["melspectrogram", 0],
    ["embedding", 1],
    ["classifier", 2],
  ])("rejects a %s model with a checksum mismatch before creating a worker", async (_label, badIndex) => {
    const worker = new FakeWorker();
    const digestSequence = goodDigestSequence();
    digestSequence[badIndex] = new Uint8Array(32).fill(0xff).buffer;
    const { detector } = detectorWith(worker, digestSequence);

    await expect(detector.load()).rejects.toThrow(/checksum/i);
    expect(worker.sent).toEqual([]);
  });

  it("ignores a detection posted by an old generation", async () => {
    const worker = new FakeWorker();
    const { detector } = detectorWith(worker);
    await detector.load();
    const onDetection = vi.fn();
    detector.resume(9, onDetection, vi.fn());

    worker.emit({
      type: "detection",
      detection: { label: "wake", score: 0.95, modelVersion: manifest.modelVersion, throughSequence: 3, generation: 8 },
    });

    expect(onDetection).not.toHaveBeenCalled();
  });

  it("prevents callbacks after pause", async () => {
    const worker = new FakeWorker();
    const { detector } = detectorWith(worker);
    await detector.load();
    const onDetection = vi.fn();
    detector.resume(9, onDetection, vi.fn());
    detector.pause();
    worker.emit({
      type: "detection",
      detection: { label: "wake", score: 0.95, modelVersion: manifest.modelVersion, throughSequence: 3, generation: 9 },
    });

    expect(onDetection).not.toHaveBeenCalled();
  });

  it("holds one inference window and sends it once per hop with the latest sequence", async () => {
    const worker = new FakeWorker();
    const { detector } = detectorWith(worker);
    await detector.load();
    detector.resume(4, vi.fn(), vi.fn());

    detector.accept({ sequence: 1, samples: new Float32Array(16_000).fill(1) });
    detector.accept({ sequence: 2, samples: new Float32Array(16_000).fill(2) });
    worker.emit({ type: "idle", generation: 4 });
    detector.accept({ sequence: 3, samples: new Float32Array(1_600).fill(3) });

    const inference = worker.sent.filter((message) => message.type === "infer");
    expect(inference).toHaveLength(2);
    expect(inference[0]).toMatchObject({ throughSequence: 2, generation: 4 });
    expect(inference[1]).toMatchObject({ throughSequence: 3, generation: 4 });
    expect(inference[1]?.type === "infer" && inference[1].pcm).toHaveLength(32_000);
    expect(inference[1]?.type === "infer" && inference[1].pcm[0]).toBe(1);
    expect(inference[1]?.type === "infer" && inference[1].pcm.at(-1)).toBe(3);
  });

  it("discards the buffered window on pause so resuming cannot re-detect the previous wake phrase", async () => {
    const worker = new FakeWorker();
    const { detector } = detectorWith(worker);
    await detector.load();
    detector.resume(4, vi.fn(), vi.fn());

    // A full window accumulates and is scored -- this is the turn's own wake phrase.
    detector.accept({ sequence: 1, samples: new Float32Array(32_000).fill(1) });
    const sentDuringTurn = worker.sent.filter((message) => message.type === "infer").length;
    expect(sentDuringTurn).toBeGreaterThan(0);

    // The turn runs: arming, capture, backend round-trip, spoken reply.
    detector.pause();
    worker.emit({ type: "idle", generation: 4 });
    detector.resume(4, vi.fn(), vi.fn());

    // A hop's worth of fresh audio must NOT be enough to score again -- the window it
    // would be scored against is still mostly the previous wake phrase.
    detector.accept({ sequence: 2, samples: new Float32Array(1_600).fill(2) });
    expect(worker.sent.filter((message) => message.type === "infer")).toHaveLength(sentDuringTurn);

    // Only once a whole window of genuinely new audio exists does scoring resume.
    detector.accept({ sequence: 3, samples: new Float32Array(30_400).fill(2) });
    const afterRefill = worker.sent.filter((message) => message.type === "infer");
    expect(afterRefill).toHaveLength(sentDuringTurn + 1);
    expect(afterRefill.at(-1)?.type === "infer" && afterRefill.at(-1)?.pcm.every((v) => v === 2)).toBe(true);
  });

  it("ignores a detection computed from audio predating the last pause", async () => {
    const worker = new FakeWorker();
    const onDetection = vi.fn();
    const { detector } = detectorWith(worker);
    await detector.load();
    detector.resume(4, onDetection, vi.fn());
    detector.accept({ sequence: 7, samples: new Float32Array(32_000).fill(1) });

    detector.pause();
    detector.resume(4, onDetection, vi.fn());

    // The worker finishes the pre-pause window only after listening resumed.
    worker.emit({
      type: "detection",
      detection: { label: "wake", score: 1, modelVersion: "2026.08.16", throughSequence: 7, generation: 4 },
    });
    expect(onDetection).not.toHaveBeenCalled();

    worker.emit({
      type: "detection",
      detection: { label: "wake", score: 1, modelVersion: "2026.08.16", throughSequence: 9, generation: 4 },
    });
    expect(onDetection).toHaveBeenCalledTimes(1);
  });

  it("drops windows instead of queueing them while the worker has not acknowledged the last one", async () => {
    const worker = new FakeWorker();
    const { detector } = detectorWith(worker);
    await detector.load();
    detector.resume(4, vi.fn(), vi.fn());

    detector.accept({ sequence: 1, samples: new Float32Array(32_000).fill(1) });
    const afterFirst = worker.sent.filter((message) => message.type === "infer").length;

    // Many hops arrive while the worker is still busy. Queueing them is what let
    // detection fall seconds behind live audio, so every one must be dropped.
    for (let hop = 2; hop < 12; hop += 1) {
      detector.accept({ sequence: hop, samples: new Float32Array(1_600).fill(hop) });
    }
    expect(worker.sent.filter((message) => message.type === "infer")).toHaveLength(afterFirst);

    // Once acknowledged, the very next hop is sent -- and it carries the freshest
    // audio, not the oldest window that was dropped.
    worker.emit({ type: "idle", generation: 4 });
    detector.accept({ sequence: 12, samples: new Float32Array(1_600).fill(12) });
    const inference = worker.sent.filter((message) => message.type === "infer");
    expect(inference).toHaveLength(afterFirst + 1);
    expect(inference.at(-1)).toMatchObject({ throughSequence: 12 });
    expect(inference.at(-1)?.type === "infer" && inference.at(-1)?.pcm.at(-1)).toBe(12);
  });

  it("posts the three fetched model buffers to the worker on load", async () => {
    const worker = new FakeWorker();
    const { detector } = detectorWith(worker);
    await detector.load();

    const loadMessage = worker.sent.find((message) => message.type === "load");
    expect(loadMessage).toBeDefined();
    if (loadMessage?.type !== "load") throw new Error("expected a load message");
    expect(new Uint8Array(loadMessage.melspectrogramBytes)).toEqual(new Uint8Array([1]));
    expect(new Uint8Array(loadMessage.embeddingBytes)).toEqual(new Uint8Array([2]));
    expect(new Uint8Array(loadMessage.classifierBytes)).toEqual(new Uint8Array([3]));
  });
});
