import type { WakeWordManifest } from "./types";

const REQUIRED_LABELS = ["wake", "non_wake"] as const;

function invalid(reason: string): never {
  throw new Error(`Invalid wake-word manifest: ${reason}`);
}

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) invalid("must be an object");
  return value as Record<string, unknown>;
}

function requiredText(value: unknown, field: string): string {
  if (typeof value !== "string" || !value.trim()) invalid(`${field} must be non-empty`);
  return value;
}

function checksum(value: unknown, field: string): string {
  const text = requiredText(value, field).toLowerCase();
  if (!/^[a-f0-9]{64}$/.test(text)) invalid(`${field} must be a 64-character hexadecimal digest`);
  return text;
}

function positiveInteger(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value <= 0) {
    invalid(`${field} must be a positive integer`);
  }
  return value;
}

function threshold(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0 || value > 1) {
    invalid("threshold must be greater than zero and at most one");
  }
  return value;
}

function architecture(value: unknown): "mean_pooled_softmax" | "sequence_sigmoid" {
  if (value === undefined) return "mean_pooled_softmax";
  if (value !== "mean_pooled_softmax" && value !== "sequence_sigmoid") {
    invalid("architecture must be mean_pooled_softmax or sequence_sigmoid");
  }
  return value;
}

function sequenceLength(value: unknown, resolvedArchitecture: "mean_pooled_softmax" | "sequence_sigmoid"): number | undefined {
  if (resolvedArchitecture !== "sequence_sigmoid") return undefined;
  return positiveInteger(value, "sequenceLength");
}

/** Validates the non-negotiable three-model contract before any model bytes are used. */
export function parseWakeWordManifest(value: unknown): WakeWordManifest {
  const raw = record(value);
  if (raw.schemaVersion !== "1.0") invalid("schemaVersion must be 1.0");
  if (raw.sampleRate !== 16_000) invalid("sampleRate must be 16000");
  if (raw.windowSamples !== 32_000) invalid("windowSamples must be 32000");
  if (!Array.isArray(raw.labels) || raw.labels.length !== REQUIRED_LABELS.length ||
    !raw.labels.every((label, index) => label === REQUIRED_LABELS[index])) {
    invalid("labels must be wake, non_wake in order");
  }

  const license = requiredText(raw.license, "license");
  if (license !== "LicenseRef-VIVI-Academic-Only") invalid("license is not supported");
  const resolvedArchitecture = architecture(raw.architecture);

  return {
    schemaVersion: "1.0",
    modelVersion: requiredText(raw.modelVersion, "modelVersion"),
    modelPath: requiredText(raw.modelPath, "modelPath"),
    sha256: checksum(raw.sha256, "sha256"),
    melspectrogramPath: requiredText(raw.melspectrogramPath, "melspectrogramPath"),
    melspectrogramSha256: checksum(raw.melspectrogramSha256, "melspectrogramSha256"),
    embeddingPath: requiredText(raw.embeddingPath, "embeddingPath"),
    embeddingSha256: checksum(raw.embeddingSha256, "embeddingSha256"),
    license,
    trainingRunId: requiredText(raw.trainingRunId, "trainingRunId"),
    evaluationReportPath: requiredText(raw.evaluationReportPath, "evaluationReportPath"),
    sampleRate: 16_000,
    windowSamples: 32_000,
    hopSamples: positiveInteger(raw.hopSamples, "hopSamples"),
    labels: ["wake", "non_wake"],
    threshold: threshold(raw.threshold),
    refractoryMs: positiveInteger(raw.refractoryMs, "refractoryMs"),
    architecture: resolvedArchitecture,
    sequenceLength: sequenceLength(raw.sequenceLength, resolvedArchitecture),
  };
}
