import { PCM_SAMPLE_RATE, type PcmFrame } from "./pcm";

export type FrameListener = (frame: PcmFrame) => void;

export interface FrameSubscription {
  unsubscribe(): void;
}

export interface AudioSourceHandle {
  stop(): Promise<void>;
}

export type AudioSourceFactory = (onSamples: (samples: Float32Array) => void) => Promise<AudioSourceHandle>;

const MICROPHONE_CONSTRAINTS = {
  audio: {
    channelCount: 1,
    sampleRate: PCM_SAMPLE_RATE,
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
  },
};
const WORKLET_URL = "/worklets/pcm16k-recorder.js";
const WORKLET_NAME = "pcm16k-recorder";
const FLUSH_DELAY_MS = 80;

/** Owns one browser microphone source and distributes isolated PCM frames. */
export class MicrophonePipeline {
  private sequence = 0;
  private listeners = new Set<FrameListener>();
  private source: AudioSourceHandle | null = null;
  private lifecycle: Promise<void> = Promise.resolve();

  constructor(private readonly sourceFactory: AudioSourceFactory = createBrowserAudioSource) {}

  start(): Promise<void> {
    return this.enqueue(async () => {
      if (this.source) return;
      this.source = await this.sourceFactory((samples) => this.publish(samples));
    });
  }

  subscribe(listener: FrameListener): FrameSubscription {
    this.listeners.add(listener);
    return { unsubscribe: () => this.listeners.delete(listener) };
  }

  stop(): Promise<void> {
    return this.enqueue(async () => {
      const source = this.source;
      if (!source) {
        this.listeners.clear();
        return;
      }

      try {
        await source.stop();
      } finally {
        if (this.source === source) this.source = null;
        this.listeners.clear();
      }
    });
  }

  private publish(samples: Float32Array): void {
    const sequence = ++this.sequence;
    for (const listener of this.listeners) {
      listener({ sequence, samples: samples.slice() });
    }
  }

  private enqueue(operation: () => Promise<void>): Promise<void> {
    const run = this.lifecycle.then(operation, operation);
    this.lifecycle = run.catch(() => undefined);
    return run;
  }
}

/** Creates the only browser-specific microphone graph used by audio capture. */
export async function createBrowserAudioSource(
  onSamples: (samples: Float32Array) => void,
): Promise<AudioSourceHandle> {
  const stream = await navigator.mediaDevices.getUserMedia(MICROPHONE_CONSTRAINTS);
  const AudioContextCtor =
    window.AudioContext ??
    (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AudioContextCtor) throw new Error("AudioContext is not supported in this browser.");

  const context = new AudioContextCtor({ sampleRate: PCM_SAMPLE_RATE });
  await context.audioWorklet.addModule(WORKLET_URL);
  const source = context.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(context, WORKLET_NAME);
  const silent = context.createGain();
  silent.gain.value = 0;
  node.port.onmessage = (event: MessageEvent<Float32Array>) => onSamples(event.data);
  source.connect(node);
  node.connect(silent);
  silent.connect(context.destination);

  let stopped = false;
  return {
    async stop() {
      if (stopped) return;
      stopped = true;
      source.disconnect();
      await new Promise<void>((resolve) => setTimeout(resolve, FLUSH_DELAY_MS));
      node.port.onmessage = null;
      node.disconnect();
      silent.disconnect();
      for (const track of stream.getTracks()) track.stop();
      await context.close();
    },
  };
}
