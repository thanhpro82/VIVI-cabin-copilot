import type { PcmFrame } from "@/lib/audio/pcm";
import { parseWakeWordManifest } from "./manifest";
import type { WakeDetection, WakeWordDetector, WakeWordManifest, WorkerIn, WorkerOut } from "./types";

interface WorkerLike {
  onmessage: ((event: MessageEvent<WorkerOut>) => void) | null;
  onerror: ((event: ErrorEvent) => void) | null;
  postMessage(message: WorkerIn, transfer?: Transferable[]): void;
  terminate(): void;
}

export interface OnnxWakeWordDetectorOptions {
  fetchImpl?: typeof fetch;
  workerFactory?: () => WorkerLike;
  digest?: (bytes: ArrayBuffer) => Promise<ArrayBuffer>;
}

const MANIFEST_PATH = "/models/wake-word/manifest.json";

function toHex(bytes: ArrayBuffer): string {
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function browserWorkerFactory(): WorkerLike {
  return new Worker(new URL("./wakeWord.worker.ts", import.meta.url), { type: "module" });
}

function browserDigest(bytes: ArrayBuffer): Promise<ArrayBuffer> {
  return crypto.subtle.digest("SHA-256", bytes);
}

/** Browser adapter that verifies an offline model before giving it to WASM inference. */
export class OnnxWakeWordDetector implements WakeWordDetector {
  private readonly fetchImpl: typeof fetch;
  private readonly workerFactory: () => WorkerLike;
  private readonly digest: (bytes: ArrayBuffer) => Promise<ArrayBuffer>;
  private worker: WorkerLike | null = null;
  private manifest: WakeWordManifest | null = null;
  private loadPromise: Promise<WakeWordManifest> | null = null;
  private active = false;
  private generation = -1;
  private onDetection: ((detection: WakeDetection) => void) | null = null;
  private onError: ((message: string) => void) | null = null;
  private ring: Float32Array | null = null;
  private writeIndex = 0;
  private filled = 0;
  private samplesSinceInference = 0;
  /**
   * True between posting a window and the worker's "idle" acknowledgement. While set,
   * new windows are dropped rather than posted -- wake detection only ever wants the
   * freshest audio, and queueing windows the worker cannot keep up with made detection
   * latency grow without bound (measured 5.4 s behind live audio), long enough that
   * command capture started after the speaker had already finished talking.
   */
  private inferenceInFlight = false;
  private lastAcceptedSequence = 0;
  private staleBeforeSequence = -1;

  constructor(options: OnnxWakeWordDetectorOptions = {}) {
    // Native fetch throws "Illegal invocation" when called detached from its
    // receiver (e.g. `const f = fetch; f(url)`) -- bind to globalThis so the
    // real browser fetch works when no test override is supplied.
    this.fetchImpl = options.fetchImpl ?? fetch.bind(globalThis);
    this.workerFactory = options.workerFactory ?? browserWorkerFactory;
    this.digest = options.digest ?? browserDigest;
  }

  load(): Promise<WakeWordManifest> {
    if (this.manifest) return Promise.resolve(this.manifest);
    if (!this.loadPromise) this.loadPromise = this.loadModel();
    return this.loadPromise;
  }

  resume(generation: number, onDetection: (detection: WakeDetection) => void, onError: (message: string) => void): void {
    this.generation = generation;
    this.onDetection = onDetection;
    this.onError = onError;
    this.active = true;
  }

  accept(frame: PcmFrame): void {
    const manifest = this.manifest;
    if (!this.active || !this.worker || !manifest) return;
    if (!this.ring) this.ring = new Float32Array(manifest.windowSamples);
    this.lastAcceptedSequence = frame.sequence;

    for (const sample of frame.samples) {
      this.ring[this.writeIndex] = sample;
      this.writeIndex = (this.writeIndex + 1) % manifest.windowSamples;
      if (this.filled < manifest.windowSamples) {
        this.filled += 1;
        if (this.filled === manifest.windowSamples) this.sendInference(frame.sequence);
        continue;
      }
      this.samplesSinceInference += 1;
      if (this.samplesSinceInference >= manifest.hopSamples) {
        this.samplesSinceInference = 0;
        this.sendInference(frame.sequence);
      }
    }
  }

  pause(): void {
    if (this.worker && this.generation >= 0) this.worker.postMessage({ type: "pause", generation: this.generation });
    this.active = false;
    this.onDetection = null;
    this.onError = null;
    this.resetWindow();
  }

  /**
   * Drops the buffered audio window so listening always restarts from fresh sound.
   *
   * Detection pauses for the whole of arming, command capture, the backend turn and the
   * spoken reply -- far longer than the model's refractory window. Keeping the ring
   * across that gap meant the first inference after resuming ran on a window still
   * holding the PREVIOUS wake phrase, which re-triggered the wake immediately and made
   * the assistant appear to arm itself over and over between turns.
   */
  private resetWindow(): void {
    this.filled = 0;
    this.writeIndex = 0;
    this.samplesSinceInference = 0;
    // Anything the worker is still chewing on belongs to the discarded window, so its
    // verdict must not be allowed to arm a fresh session after we resume.
    this.staleBeforeSequence = this.lastAcceptedSequence;
  }

  dispose(): void {
    this.pause();
    if (this.worker && this.generation >= 0) this.worker.postMessage({ type: "dispose", generation: this.generation });
    this.worker?.terminate();
    this.worker = null;
    this.manifest = null;
    this.loadPromise = null;
    this.ring = null;
    this.inferenceInFlight = false;
    this.resetWindow();
  }

  private async loadModel(): Promise<WakeWordManifest> {
    const manifestResponse = await this.fetchImpl(MANIFEST_PATH);
    if (!manifestResponse.ok) throw new Error(`Wake-word manifest request failed (${manifestResponse.status})`);
    const manifest = parseWakeWordManifest(await manifestResponse.json());

    const fetchAndVerify = async (path: string, expectedSha256: string, label: string): Promise<ArrayBuffer> => {
      const response = await this.fetchImpl(path);
      if (!response.ok) throw new Error(`Wake-word ${label} request failed (${response.status})`);
      const bytes = await response.arrayBuffer();
      if (toHex(await this.digest(bytes)) !== expectedSha256) {
        throw new Error(`Wake-word ${label} checksum mismatch`);
      }
      return bytes;
    };

    const melspectrogramBytes = await fetchAndVerify(manifest.melspectrogramPath, manifest.melspectrogramSha256, "melspectrogram model");
    const embeddingBytes = await fetchAndVerify(manifest.embeddingPath, manifest.embeddingSha256, "embedding model");
    const classifierBytes = await fetchAndVerify(manifest.modelPath, manifest.sha256, "classifier model");

    this.manifest = manifest;
    this.worker = this.workerFactory();
    return new Promise<WakeWordManifest>((resolve, reject) => {
      const worker = this.worker;
      if (!worker) return reject(new Error("Wake-word worker was unavailable"));
      const ready = (event: MessageEvent<WorkerOut>) => {
        if (event.data.type === "ready") {
          worker.onmessage = (next) => this.handleWorkerMessage(next.data);
          resolve(manifest);
          return;
        }
        if (event.data.type === "error") reject(new Error(event.data.message));
      };
      worker.onmessage = ready;
      worker.onerror = (event) => reject(new Error(event.message || "Wake-word worker failed"));
      worker.postMessage(
        { type: "load", manifest, melspectrogramBytes, embeddingBytes, classifierBytes, generation: 0 },
        [melspectrogramBytes, embeddingBytes, classifierBytes],
      );
    }).catch((error: unknown) => {
      this.worker?.terminate();
      this.worker = null;
      this.manifest = null;
      this.loadPromise = null;
      throw error;
    });
  }

  private sendInference(throughSequence: number): void {
    const manifest = this.manifest;
    const ring = this.ring;
    if (!manifest || !ring || !this.worker || this.inferenceInFlight) return;
    const pcm = new Float32Array(manifest.windowSamples);
    if (this.writeIndex === 0) pcm.set(ring);
    else {
      pcm.set(ring.subarray(this.writeIndex));
      pcm.set(ring.subarray(0, this.writeIndex), manifest.windowSamples - this.writeIndex);
    }
    this.inferenceInFlight = true;
    this.worker.postMessage({ type: "infer", pcm, throughSequence, generation: this.generation }, [pcm.buffer]);
  }

  private handleWorkerMessage(message: WorkerOut): void {
    // Cleared before the `active` gate: a pause landing mid-inference must not leave
    // the flag stuck, or detection never resumes after the next capture ends.
    if (message.type === "idle") {
      this.inferenceInFlight = false;
      return;
    }
    if (!this.active || message.type === "ready") return;
    if (message.type === "detection") {
      // A verdict computed from audio older than the last window reset describes sound
      // the user has already been answered about -- acting on it re-arms spuriously.
      if (message.detection.throughSequence <= this.staleBeforeSequence) return;
      if (message.detection.generation === this.generation) this.onDetection?.(message.detection);
      return;
    }
    if (message.generation === this.generation) this.onError?.(message.message);
  }

}

export function createOnnxWakeWordDetector(options?: OnnxWakeWordDetectorOptions): WakeWordDetector {
  return new OnnxWakeWordDetector(options);
}
