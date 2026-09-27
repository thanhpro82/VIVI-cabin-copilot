import { describe, expect, it } from "vitest";
import { meanPool } from "./pooling";

describe("meanPool", () => {
  it("averages each dimension across windows", () => {
    // 3 windows, 2 dims: [[1,2],[3,4],[5,6]]
    const flat = Float32Array.from([1, 2, 3, 4, 5, 6]);
    const result = meanPool(flat, 3, 2);
    expect(Array.from(result)).toEqual([3, 4]);
  });

  it("throws when the flattened length does not match numWindows * dim", () => {
    const flat = Float32Array.from([1, 2, 3]);
    expect(() => meanPool(flat, 2, 2)).toThrow(/length/i);
  });

  it("throws for zero windows", () => {
    expect(() => meanPool(Float32Array.from([]), 0, 2)).toThrow(/window/i);
  });
});
