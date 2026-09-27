/** Shared 16 kHz PCM primitives used by browser audio capture. */

export const PCM_SAMPLE_RATE = 16_000;
export const ARM_GUARD_SAMPLES = 4_800;

export interface PcmFrame {
  sequence: number;
  samples: Float32Array;
}

export interface SpeechEnergyTracker {
  feed(samples: Float32Array, chunkMs: number): void;
  hadSpeech(): boolean;
}

const SILENCE_RMS_THRESHOLD = 0.02;
const SILENCE_DURATION_MS = 900;

function computeRms(samples: Float32Array): number {
  let sumSquares = 0;
  for (let i = 0; i < samples.length; i++) sumSquares += samples[i] * samples[i];
  return Math.sqrt(sumSquares / samples.length);
}

/**
 * Tracks audible speech for recording feedback and optional end-of-speech UX.
 * It is intentionally not a wake-word detector.
 */
export function createSpeechEnergyTracker(onSilenceDetected?: () => void): SpeechEnergyTracker {
  let hasSpeech = false;
  let silenceMs = 0;
  let fired = false;

  return {
    feed(samples, chunkMs) {
      const rms = computeRms(samples);
      if (rms >= SILENCE_RMS_THRESHOLD) {
        hasSpeech = true;
        silenceMs = 0;
        return;
      }

      if (!hasSpeech || fired || !onSilenceDetected) return;
      silenceMs += chunkMs;
      if (silenceMs >= SILENCE_DURATION_MS) {
        fired = true;
        onSilenceDetected();
      }
    },
    hadSpeech: () => hasSpeech,
  };
}

function resampleLinear(input: Float32Array, fromRate: number, toRate: number): Float32Array {
  if (fromRate === toRate) return input;

  const ratio = fromRate / toRate;
  const output = new Float32Array(Math.round(input.length / ratio));
  for (let i = 0; i < output.length; i++) {
    const sourcePosition = i * ratio;
    const sourceIndex = Math.floor(sourcePosition);
    const fractional = sourcePosition - sourceIndex;
    const a = input[sourceIndex] ?? 0;
    const b = input[sourceIndex + 1] ?? a;
    output[i] = a + (b - a) * fractional;
  }
  return output;
}

/** Encodes float PCM chunks as a mono, 16-bit, 16 kHz WAV Blob. */
export function encodePcm16Wav(chunks: Float32Array[], sourceSampleRate: number): Blob {
  const capturedTotal = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const merged = new Float32Array(capturedTotal);
  let mergedOffset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, mergedOffset);
    mergedOffset += chunk.length;
  }

  const samples =
    sourceSampleRate === PCM_SAMPLE_RATE
      ? merged
      : resampleLinear(merged, sourceSampleRate, PCM_SAMPLE_RATE);
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeString = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i));
  };

  writeString(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, PCM_SAMPLE_RATE, true);
  view.setUint32(28, PCM_SAMPLE_RATE * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, samples.length * 2, true);

  for (let i = 0, offset = 44; i < samples.length; i++, offset += 2) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
  }

  return new Blob([buffer], { type: "audio/wav" });
}
