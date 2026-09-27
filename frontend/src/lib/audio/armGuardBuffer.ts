import type { PcmFrame } from "./pcm";

/** Owns the most recent PCM samples and tracks a beep-fire boundary. */
export class ArmGuardBuffer {
  private frames: PcmFrame[] = [];
  private sampleCount = 0;
  private triggerSequence = -1;

  constructor(private readonly capacitySamples: number) {}

  push(frame: PcmFrame): void {
    const samples = frame.samples.slice();
    this.frames.push({ sequence: frame.sequence, samples });
    this.sampleCount += samples.length;

    while (this.sampleCount > this.capacitySamples && this.frames.length > 1) {
      const removed = this.frames.shift();
      if (removed) this.sampleCount -= removed.samples.length;
    }

    const overflow = this.sampleCount - this.capacitySamples;
    if (overflow > 0 && this.frames[0]) {
      const first = this.frames[0];
      this.frames[0] = { ...first, samples: first.samples.slice(overflow) };
      this.sampleCount -= overflow;
    }
  }

  snapshotThrough(sequence: number): Float32Array {
    this.triggerSequence = sequence;
    const selected = this.frames.filter((frame) => frame.sequence <= sequence);
    const total = selected.reduce((sum, frame) => sum + frame.samples.length, 0);
    const snapshot = new Float32Array(total);
    let offset = 0;
    for (const frame of selected) {
      snapshot.set(frame.samples, offset);
      offset += frame.samples.length;
    }
    return snapshot;
  }

  shouldAppendLive(sequence: number): boolean {
    return sequence > this.triggerSequence;
  }

  clear(): void {
    this.frames = [];
    this.sampleCount = 0;
    this.triggerSequence = -1;
  }
}
