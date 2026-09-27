from __future__ import annotations

from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from pathlib import Path
import re
from typing import Any, Mapping, Sequence
import unicodedata


_SECTION_PATTERN = re.compile(
    r"^##\s+(?P<section>[A-Z0-9_]+)\s*\|\s*page:\s*(?P<page>\d+)\s*$",
    re.MULTILINE,
)

_QUERY_ANCHORS = {
    "TPMS": ("tpms", "den ap suat lop", "den canh bao ap suat lop"),
    "ECO_MODE": ("eco",),
    "TIRE_CHECK": ("kiem tra ap suat lop", "khi nao can kiem tra"),
}

_STOP_WORDS = {
    "bi",
    "cach",
    "can",
    "co",
    "do",
    "gi",
    "khong",
    "la",
    "mot",
    "nao",
    "nay",
    "o",
    "tay",
    "the",
    "thi",
    "tren",
    "va",
    "xe",
}


@dataclass(frozen=True)
class Evidence:
    section: str
    page: int
    text: str
    chunk_id: str
    score: float = 0.0


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text).casefold()
    without_marks = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    ).replace("đ", "d")
    letters_and_spaces = re.sub(r"[^a-z0-9đ]+", " ", without_marks)
    return " ".join(letters_and_spaces.split())


def _content_tokens(text: str) -> set[str]:
    return {token for token in _fold(text).split() if token not in _STOP_WORDS}


def _matched_anchor_tokens(anchor: str, folded_query: str) -> int:
    if anchor in folded_query:
        return len(anchor.split())
    anchor_tokens = anchor.split()
    if len(anchor_tokens) == 1:
        return 0
    query_tokens = folded_query.split()
    used: set[int] = set()
    matched = 0
    for anchor_token in anchor_tokens:
        candidates = [
            (SequenceMatcher(None, anchor_token, query_token).ratio(), index)
            for index, query_token in enumerate(query_tokens)
            if index not in used
        ]
        if not candidates:
            continue
        ratio, index = max(candidates)
        if ratio >= 0.72:
            used.add(index)
            matched += 1
    return matched if matched / len(anchor_tokens) >= 0.66 else 0


class ManualIndex:
    """Deterministic local index for the tiny PoC manual fixture.

    The real benchmark can replace the scoring adapter with E5/FAISS while
    retaining the same Evidence and citation-validation contracts.
    """

    def __init__(self, passages: Sequence[Evidence]) -> None:
        self.passages = tuple(passages)

    @classmethod
    def from_markdown(cls, path: Path) -> "ManualIndex":
        source = path.read_text(encoding="utf-8")
        headings = list(_SECTION_PATTERN.finditer(source))
        if not headings:
            raise ValueError("manual has no '## SECTION | page: N' blocks")

        passages: list[Evidence] = []
        for index, heading in enumerate(headings):
            body_start = heading.end()
            body_end = headings[index + 1].start() if index + 1 < len(headings) else len(source)
            body = source[body_start:body_end].strip()
            section = heading.group("section")
            page = int(heading.group("page"))
            if not body:
                raise ValueError(f"manual section {section} is empty")
            passages.append(
                Evidence(
                    section=section,
                    page=page,
                    text=body,
                    chunk_id=f"manual:{section}:p{page}:0",
                )
            )
        return cls(passages)

    def search(self, query: str, *, k: int = 5) -> list[Evidence]:
        if k <= 0:
            return []
        folded_query = _fold(query)
        query_tokens = _content_tokens(query)
        ranked: list[Evidence] = []

        for passage in self.passages:
            anchors = _QUERY_ANCHORS.get(passage.section, ())
            matched_anchor_tokens = max(
                (
                    _matched_anchor_tokens(anchor, folded_query)
                    for anchor in anchors
                ),
                default=0,
            )
            if matched_anchor_tokens == 0:
                continue

            passage_tokens = _content_tokens(passage.text)
            overlap = len(query_tokens & passage_tokens) / max(1, len(query_tokens))
            score = matched_anchor_tokens + overlap
            ranked.append(replace(passage, score=score))

        ranked.sort(key=lambda item: (-item.score, item.section, item.page))
        return ranked[:k]


def validate_citations(
    answer_claims: Sequence[Mapping[str, Any]],
    evidence_by_id: Mapping[str, Evidence],
) -> bool:
    if not answer_claims:
        return False
    for claim in answer_claims:
        evidence_id = claim.get("evidence_id")
        evidence = evidence_by_id.get(str(evidence_id))
        if evidence is None:
            return False
        if claim.get("section") != evidence.section:
            return False
        if claim.get("page") != evidence.page:
            return False
    return True
