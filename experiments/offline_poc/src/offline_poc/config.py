from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class CandidateConfig(BaseModel):
    profile_id: str
    model_path: Path
    quantization: str
    required: bool
    threads: int = Field(default=4, ge=1)
    context_tokens: int = Field(default=4096, ge=512)
    max_output_tokens: int = Field(default=192, ge=1)


class BenchmarkConfig(BaseModel):
    cpu_limit: int = Field(default=4, ge=1)
    memory_limit_gib: int = Field(default=8, ge=1)
    cold_runs: int = Field(default=5, ge=1)
    warm_runs: int = Field(default=20, ge=1)
    candidates: list[CandidateConfig] = Field(min_length=2)


def load_config(path: Path) -> BenchmarkConfig:
    """Load and validate the benchmark configuration."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return BenchmarkConfig.model_validate(payload)

