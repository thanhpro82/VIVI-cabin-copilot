import { copyFile, mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = resolve(fileURLToPath(new URL(".", import.meta.url)));
const frontendDirectory = resolve(scriptDirectory, "..");
const sourceDirectory = resolve(frontendDirectory, "node_modules/onnxruntime-web/dist");
const targetDirectory = resolve(frontendDirectory, "public/ort-wasm");
const assets = ["ort-wasm-simd-threaded.wasm", "ort-wasm-simd-threaded.mjs"];

await mkdir(targetDirectory, { recursive: true });
await Promise.all(assets.map((asset) => copyFile(resolve(sourceDirectory, asset), resolve(targetDirectory, asset))));
