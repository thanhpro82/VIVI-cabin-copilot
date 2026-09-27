import { describe, expect, it } from "vitest";
import { parseWakeWordManifest } from "./manifest";
import type { WakeWordManifest } from "./types";

const validManifest: WakeWordManifest = {
  schemaVersion: "1.0",
  modelVersion: "vivi-wake-v2-openwakeword",
  modelPath: "/models/wake-word/vivi-wake-classifier.onnx",
  sha256: "a".repeat(64),
  melspectrogramPath: "/models/wake-word/melspectrogram.onnx",
  melspectrogramSha256: "c".repeat(64),
  embeddingPath: "/models/wake-word/embedding_model.onnx",
  embeddingSha256: "d".repeat(64),
  license: "LicenseRef-VIVI-Academic-Only",
  trainingRunId: "vivi-wake-v2-seed192",
  evaluationReportPath: "/models/wake-word/evaluation.md",
  sampleRate: 16_000,
  windowSamples: 32_000,
  hopSamples: 1_600,
  labels: ["wake", "non_wake"],
  threshold: 0.8,
  refractoryMs: 1_000,
  architecture: "mean_pooled_softmax",
};

describe("parseWakeWordManifest", () => {
  it("accepts the pinned wake-word model contract", () => {
    expect(parseWakeWordManifest(validManifest)).toEqual(validManifest);
  });

  it.each([
    ["sample rate", { sampleRate: 48_000 }],
    ["window size", { windowSamples: 16_000 }],
    ["label order", { labels: ["non_wake", "wake"] }],
    ["empty training run", { trainingRunId: "" }],
    ["empty evaluation report", { evaluationReportPath: "" }],
    ["empty license", { license: "" }],
    ["zero hop", { hopSamples: 0 }],
    ["fractional hop", { hopSamples: 0.5 }],
    ["zero threshold", { threshold: 0 }],
    ["threshold above one", { threshold: 1.01 }],
    ["zero refractory", { refractoryMs: 0 }],
    ["fractional refractory", { refractoryMs: 0.5 }],
    ["empty melspectrogram checksum", { melspectrogramSha256: "" }],
    ["short melspectrogram checksum", { melspectrogramSha256: "abc" }],
    ["empty embedding checksum", { embeddingSha256: "" }],
    ["short embedding checksum", { embeddingSha256: "abc" }],
    ["empty melspectrogram path", { melspectrogramPath: "" }],
    ["empty embedding path", { embeddingPath: "" }],
  ])("rejects an invalid %s", (_name, change) => {
    expect(() => parseWakeWordManifest({ ...validManifest, ...change })).toThrow(/manifest/i);
  });
});
