import { describe, expect, it } from "vitest";
import { ArmGuardBuffer } from "./armGuardBuffer";

const frame = (sequence: number, ...samples: number[]) => ({
  sequence,
  samples: Float32Array.from(samples),
});

describe("ArmGuardBuffer", () => {
  it("retains exactly the newest capacity and snapshots through trigger once", () => {
    const buffer = new ArmGuardBuffer(6);
    buffer.push(frame(1, 1, 1));
    buffer.push(frame(2, 2, 2));
    buffer.push(frame(3, 3, 3));
    buffer.push(frame(4, 4, 4));

    expect(Array.from(buffer.snapshotThrough(3))).toEqual([2, 2, 3, 3]);
    expect(buffer.shouldAppendLive(3)).toBe(false);
    expect(buffer.shouldAppendLive(4)).toBe(true);
  });

  it("copies pushed samples so later caller mutation cannot corrupt a snapshot", () => {
    const buffer = new ArmGuardBuffer(4);
    const samples = Float32Array.from([1, 2]);
    buffer.push({ sequence: 7, samples });
    samples[0] = 99;

    expect(Array.from(buffer.snapshotThrough(7))).toEqual([1, 2]);
  });

  it("clear removes samples and sequence ownership", () => {
    const buffer = new ArmGuardBuffer(4);
    buffer.push(frame(7, 1, 2));
    buffer.clear();

    expect(buffer.snapshotThrough(7)).toHaveLength(0);
    expect(buffer.shouldAppendLive(7)).toBe(false);
    expect(buffer.shouldAppendLive(8)).toBe(true);
  });
});
