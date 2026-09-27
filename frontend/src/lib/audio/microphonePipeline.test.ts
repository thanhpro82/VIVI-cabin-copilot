import { describe, expect, it, vi } from "vitest";
import { MicrophonePipeline, type AudioSourceFactory } from "./microphonePipeline";
import { createPipelineRecording } from "./pipelineRecording";

function fakeSource() {
  let emit: ((samples: Float32Array) => void) | undefined;
  const stop = vi.fn(async () => undefined);
  const factory: AudioSourceFactory = vi.fn(async (onSamples) => {
    emit = onSamples;
    return { stop };
  });
  return { factory, stop, push: (...samples: number[]) => emit?.(Float32Array.from(samples)) };
}

async function decodeWavSamples(blob: Blob): Promise<number[]> {
  const view = new DataView(await blob.arrayBuffer());
  const samples: number[] = [];
  for (let offset = 44; offset < view.byteLength; offset += 2) {
    samples.push(view.getInt16(offset, true));
  }
  return samples;
}

function deferred() {
  let resolve: (() => void) | undefined;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve: () => resolve?.() };
}

describe("MicrophonePipeline", () => {
  it("starts one source and multicasts monotonically sequenced frames", async () => {
    const source = fakeSource();
    const pipeline = new MicrophonePipeline(source.factory);
    const first = vi.fn();
    const second = vi.fn();
    const firstSubscription = pipeline.subscribe(first);
    pipeline.subscribe(second);

    await pipeline.start();
    await pipeline.start();
    source.push(0.1, 0.2);
    firstSubscription.unsubscribe();
    source.push(0.3);

    expect(source.factory).toHaveBeenCalledTimes(1);
    expect(first.mock.calls[0][0].sequence).toBe(1);
    expect(first).toHaveBeenCalledTimes(1);
    expect(second.mock.calls.map(([frame]) => frame.sequence)).toEqual([1, 2]);
  });

  it("stop closes the source once and removes every subscriber", async () => {
    const source = fakeSource();
    const pipeline = new MicrophonePipeline(source.factory);
    const listener = vi.fn();
    pipeline.subscribe(listener);

    await pipeline.start();
    await pipeline.stop();
    await pipeline.stop();
    source.push(0.5);

    expect(source.stop).toHaveBeenCalledTimes(1);
    expect(listener).not.toHaveBeenCalled();
  });

  it("does not start a replacement source until an in-flight stop completes", async () => {
    const firstStop = deferred();
    const stops = [vi.fn(() => firstStop.promise), vi.fn(async () => undefined)];
    const factory = vi.fn(async () => ({ stop: stops[factory.mock.calls.length - 1] }));
    const pipeline = new MicrophonePipeline(factory);
    await pipeline.start();

    const stopping = pipeline.stop();
    const restarting = pipeline.start();
    firstStop.resolve();
    await stopping;

    expect(factory).toHaveBeenCalledTimes(1);

    await restarting;
    await pipeline.stop();
    expect(factory).toHaveBeenCalledTimes(2);
    expect(stops[1]).toHaveBeenCalledTimes(1);
  });

  it("gives each subscriber its own copy of browser PCM samples", async () => {
    let emit: ((samples: Float32Array) => void) | undefined;
    const pipeline = new MicrophonePipeline(async (onSamples) => {
      emit = onSamples;
      return { stop: async () => undefined };
    });
    const received: number[] = [];
    pipeline.subscribe((frame) => {
      frame.samples[0] = 0;
    });
    pipeline.subscribe((frame) => received.push(frame.samples[0]));

    await pipeline.start();
    const sourceSamples = Float32Array.of(0.4);
    emit?.(sourceSamples);
    sourceSamples[0] = 0.9;

    expect(received[0]).toBeCloseTo(0.4);
  });

  it("records initial PCM and only frames after the triggering sequence", async () => {
    const source = fakeSource();
    const pipeline = new MicrophonePipeline(source.factory);
    await pipeline.start();
    for (let sequence = 1; sequence < 7; sequence += 1) source.push(sequence / 10);

    const recording = createPipelineRecording(pipeline, { initialPcm: [1, 2], afterSequence: 7 });
    source.push(0.7);
    source.push(0.5);

    const wav = await recording.stop();
    await pipeline.stop();

    expect(await decodeWavSamples(wav)).toEqual([32767, 32767, 16383]);
  });

  it("keeps recordings subscribed while a source emits its queued stop tail", async () => {
    const pipeline = new MicrophonePipeline(async (onSamples) => ({
      stop: async () => onSamples(Float32Array.of(0.5)),
    }));
    await pipeline.start();
    const recording = createPipelineRecording(pipeline, { afterSequence: 0 });

    await pipeline.stop();
    const wav = await recording.stop();

    expect(await decodeWavSamples(wav)).toEqual([16383]);
  });
});
