import pytest

from domain.grades import grade_satisfies


@pytest.mark.parametrize(
    ("earned", "required", "expected"),
    [
        ("A", "C", True),
        ("C", "C", True),
        ("C-", "C", False),
        ("D", "C", False),
        ("B+", "B", True),  # grade points, not string order ("B+" > "B" as text too)
        ("A-", "B+", True),  # string order would say "A-" < "B+"
        ("D", "D", True),
        ("E", "D", False),
        ("E", None, False),  # failed: no credit even without a minimum
        ("F", None, False),
        ("W", None, False),
        ("I", "D", False),
        ("TR", None, True),
        ("TR", "TR", True),
        ("S", "S", True),
        ("A", "TR", True),  # a letter grade meets a non-letter minimum
        ("TR", "D", False),  # credit without a letter does not meet a letter minimum
        ("AP", "C", False),
        ("P", "C", False),
    ],
)
def test_known_grades(earned: str, required: str | None, expected: bool) -> None:
    assert grade_satisfies(earned, required) is expected


@pytest.mark.parametrize("required", [None, "D", "TR", "S"])
def test_reported_completion_meets_the_passing_floor(required: str | None) -> None:
    assert grade_satisfies(None, required) is True


@pytest.mark.parametrize("required", ["C", "B"])
def test_unknown_grade_against_a_higher_minimum_is_unknown(required: str) -> None:
    assert grade_satisfies(None, required) is None
