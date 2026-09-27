/** Mean-pools a flattened (numWindows, dim) embedding sequence into a single (dim,) vector. */
export function meanPool(embeddings: Float32Array, numWindows: number, dim: number): Float32Array {
  if (numWindows <= 0) throw new Error("meanPool requires at least one window");
  if (embeddings.length !== numWindows * dim) {
    throw new Error(`meanPool embeddings length (${embeddings.length}) does not match numWindows * dim (${numWindows * dim})`);
  }
  const result = new Float32Array(dim);
  for (let window = 0; window < numWindows; window += 1) {
    const offset = window * dim;
    for (let index = 0; index < dim; index += 1) {
      result[index] += embeddings[offset + index];
    }
  }
  for (let index = 0; index < dim; index += 1) {
    result[index] /= numWindows;
  }
  return result;
}
