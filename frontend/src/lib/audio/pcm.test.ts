import { describe, expect, it, vi } from "vitest";
import {
  PCM_SAMPLE_RATE,
  ARM_GUARD_SAMPLES,
  createSpeechEnergyTracker,
  encodePcm16Wav,
} from "./pcm";

const LOUD = new Float32Array(128).fill(0.5);
const SILENT = new Float32Array(128).fill(0);

describe("PCM primitives", () => {
  it("defines the required 16 kHz, 300ms arm guard margin", () => {
    expect(PCM_SAMPLE_RATE).toBe(16_000);
    expect(ARM_GUARD_SAMPLES).toBe(4_800);
  });

  it("encodes mono 16-bit PCM at 16 kHz", async () => {
    const wav = encodePcm16Wav([Float32Array.from([-1, 0, 1])], 16_000);
    const view = new DataView(await wav.arrayBuffer());

    expect(wav.type).toBe("audio/wav");
    expect(view.getUint16(22, true)).toBe(1);
    expect(view.getUint32(24, true)).toBe(16_000);
    expect(view.getUint16(32, true)).toBe(2);
    expect(view.getUint16(34, true)).toBe(16);
    expect(view.getUint32(40, true)).toBe(6);
  });
});

describe("createSpeechEnergyTracker", () => {
  it("calls onSilenceDetected exactly once after speech then 900ms silence", () => {
    const onSilenceDetected = vi.fn();
    const tracker = createSpeechEnergyTracker(onSilenceDetected);

    tracker.feed(LOUD, 100);
    expect(onSilenceDetected).not.toHaveBeenCalled();
    expect(tracker.hadSpeech()).toBe(true);

    tracker.feed(SILENT, 500);
    tracker.feed(SILENT, 300);
    expect(onSilenceDetected).not.toHaveBeenCalled();
    tracker.feed(SILENT, 200);
    expect(onSilenceDetected).toHaveBeenCalledTimes(1);

    tracker.feed(SILENT, 1000);
    expect(onSilenceDetected).toHaveBeenCalledTimes(1);
  });

  it("does not treat silence before speech as completed speech", () => {
    const onSilenceDetected = vi.fn();
    const tracker = createSpeechEnergyTracker(onSilenceDetected);

    for (let i = 0; i < 20; i++) tracker.feed(SILENT, 100);

    expect(onSilenceDetected).not.toHaveBeenCalled();
    expect(tracker.hadSpeech()).toBe(false);
  });

  it("resets the silence interval when speech resumes", () => {
    const onSilenceDetected = vi.fn();
    const tracker = createSpeechEnergyTracker(onSilenceDetected);

    tracker.feed(LOUD, 100);
    tracker.feed(SILENT, 600);
    tracker.feed(LOUD, 100);
    tracker.feed(SILENT, 800);
    expect(onSilenceDetected).not.toHaveBeenCalled();

    tracker.feed(SILENT, 200);
    expect(onSilenceDetected).toHaveBeenCalledTimes(1);
  });

  it("records speech without an optional silence callback", () => {
    const tracker = createSpeechEnergyTracker();

    expect(tracker.hadSpeech()).toBe(false);
    tracker.feed(LOUD, 100);
    tracker.feed(SILENT, 5000);
    expect(tracker.hadSpeech()).toBe(true);
  });
});
