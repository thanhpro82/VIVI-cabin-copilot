import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class PocCase(BaseModel):
    case_id: str
    category: Literal["control", "nlu", "plan", "rag", "safety"]
    input_text: str
    vehicle_state: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any]


def load_cases(path: Path) -> list[PocCase]:
    """Load a JSONL dataset and reject duplicate case identifiers."""
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    cases = [PocCase.model_validate(json.loads(line)) for line in lines]
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("duplicate case_id")
    return cases

