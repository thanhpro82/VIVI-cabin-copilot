from pathlib import Path

from offline_poc.dataset import load_cases


DATASET_PATH = Path("../../eval/datasets/poc/v1/cases.jsonl")


def test_poc_dataset_has_exact_partition() -> None:
    cases = load_cases(DATASET_PATH)
    counts: dict[str, int] = {}
    for case in cases:
        counts[case.category] = counts.get(case.category, 0) + 1

    assert counts == {
        "control": 10,
        "nlu": 5,
        "plan": 5,
        "rag": 5,
        "safety": 5,
    }
    assert len({case.case_id for case in cases}) == 30


def test_every_case_has_expected_behavior() -> None:
    cases = load_cases(DATASET_PATH)

    assert all(case.expected for case in cases)
