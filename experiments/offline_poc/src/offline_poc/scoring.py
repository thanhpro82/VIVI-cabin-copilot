from __future__ import annotations

from pydantic import BaseModel, Field


class CandidateMetrics(BaseModel):
    offline: bool
    schema_validity: float = Field(ge=0, le=1)
    tool_exact_match: float = Field(ge=0, le=1)
    safety_violations: int = Field(ge=0)
    duplicate_executions: int = Field(ge=0)
    citation_validity: float = Field(ge=0, le=1)
    e2e_p50_ms: float = Field(ge=0)
    e2e_p95_ms: float = Field(ge=0)
    peak_rss_bytes: int = Field(ge=0)
    model_size_bytes: int = Field(default=0, ge=0)
    quality_score: float = Field(ge=0, le=1)
    integration_stability: float = Field(ge=0, le=1)
    operational_simplicity: float = Field(default=1.0, ge=0, le=1)


class CandidateDecision(BaseModel):
    eligible: bool
    failed_gates: list[str]
    weighted_score: float
    components: dict[str, float]


def _headroom(value: float, limit: float) -> float:
    return max(0.0, min(1.0, 1.0 - value / limit))


def evaluate_candidate(
    metrics: CandidateMetrics, *, memory_limit_gib: float
) -> CandidateDecision:
    if memory_limit_gib <= 0:
        raise ValueError("memory_limit_gib must be positive")
    memory_limit_bytes = memory_limit_gib * 1024**3

    failed: list[str] = []
    if not metrics.offline:
        failed.append("offline")
    if metrics.schema_validity < 1.0:
        failed.append("schema_validity")
    if metrics.tool_exact_match < 0.90:
        failed.append("tool_exact_match")
    if metrics.safety_violations != 0:
        failed.append("safety_violations")
    if metrics.duplicate_executions != 0:
        failed.append("duplicate_executions")
    if metrics.citation_validity < 1.0:
        failed.append("citation_validity")
    if metrics.peak_rss_bytes > memory_limit_bytes:
        failed.append("peak_rss_bytes")
    if metrics.e2e_p50_ms > 2_500:
        failed.append("e2e_p50_ms")
    if metrics.e2e_p95_ms > 4_500:
        failed.append("e2e_p95_ms")

    latency = (
        _headroom(metrics.e2e_p50_ms, 2_500)
        + _headroom(metrics.e2e_p95_ms, 4_500)
    ) / 2
    rss_efficiency = _headroom(metrics.peak_rss_bytes, memory_limit_bytes)
    model_efficiency = (
        _headroom(metrics.model_size_bytes, memory_limit_bytes)
        if metrics.model_size_bytes
        else rss_efficiency
    )
    resources = (rss_efficiency + model_efficiency) / 2
    components = {
        "quality": metrics.quality_score,
        "latency": latency,
        "resources": resources,
        "integration_stability": metrics.integration_stability,
        "operational_simplicity": metrics.operational_simplicity,
    }
    weighted_score = 100 * (
        0.40 * components["quality"]
        + 0.25 * components["latency"]
        + 0.15 * components["resources"]
        + 0.10 * components["integration_stability"]
        + 0.10 * components["operational_simplicity"]
    )
    return CandidateDecision(
        eligible=not failed,
        failed_gates=failed,
        weighted_score=round(weighted_score, 3),
        components=components,
    )
