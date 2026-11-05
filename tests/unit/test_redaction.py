import time

import pytest

from domain.redaction import REDACTED, redact

# (text, the part that must not survive)
REMOVED = [
    ("Your ID is A20123456.", "A20123456"),
    ("Your ID is a20123456.", "a20123456"),
    ("Your ID is A-20123456.", "20123456"),
    ("Your ID is A 2012 3456.", "2012 3456"),
    ("Email jdoe@hawk.illinoistech.edu", "jdoe@hawk"),
    ("Email jdoe@hawk.iit.edu", "jdoe@hawk"),
    ("Email jdoe [at] hawk.iit.edu", "jdoe"),
    ("Email jdoe at hawk dot iit dot edu", "jdoe"),
    ("SSN 123-45-6789 on file", "123-45-6789"),
    ("Call me at 773-555-0142", "555-0142"),
    ("Call me at (773) 555 0142", "555 0142"),
    ("Call me at +1 773.555.0142", "555.0142"),
    ("Birth Date 01/01/2000", "01/01/2000"),
    ("date of birth: 1-1-2000", "1-1-2000"),
]

# Things answers legitimately contain, which must come through untouched.
KEPT = [
    "Contact advising@iit.edu for help.",
    "Call or text 988 right now. If you're in immediate danger, call 911.",
    "The Registrar's office is at 312-567-3100.",
    "Call (312) 567-3100 for the Registrar.",
    "CS 331 - Data Structures (3 cr): 2 section(s), 47 seats open [1]",
    "MW from 11:25 AM to 12:40 PM in Siegel Hall 118",
    "IIT Banner course catalog, CS 450, term 202710",
    "CRN 41234, Fall 2026",
    "Completed: MATH 151 (transfer), CS 115 (A), CS 331 (C+)",
    "Your GPA on the transcript is 3.27.",
    "Classes start 08/24/2026.",
]


@pytest.mark.parametrize(("text", "secret"), REMOVED)
def test_personal_data_is_removed(text: str, secret: str) -> None:
    out = redact(text)
    assert secret not in out
    assert REDACTED in out


@pytest.mark.parametrize("text", KEPT)
def test_ordinary_answers_are_untouched(text: str) -> None:
    assert redact(text) == text


def test_birth_date_label_stays_so_the_answer_still_reads() -> None:
    assert redact("Birth Date 01/01/2000") == f"Birth Date {REDACTED}"


@pytest.mark.parametrize("piece", ["a.b+", "a", "1 ", "A ", "1-", "at ", "x at hawk dot "])
def test_crafted_text_cannot_slow_the_check_down(piece: str) -> None:
    text = piece * (20_000 // len(piece))
    start = time.perf_counter()
    redact(text)
    assert time.perf_counter() - start < 0.5
