"""Grade comparison for prerequisite minimums. Grades compare as grade points, never strings.

IIT letters are A-E plus F, with no +/- grades; anything else ("B+") is not a grade and never
counts. Transfer work arrives as TR, not as the other school's letter.
Banner minimums seen in the catalog: D, C, B, plus the non-letter codes TR and S.
"""

GRADE_POINTS: dict[str, float] = {"A": 4.0, "B": 3.0, "C": 2.0, "D": 1.0, "E": 0.0, "F": 0.0}

# Credit without a letter grade: transfer, satisfactory, pass, AP/test credit.
NON_LETTER_PASS = frozenset({"TR", "S", "P", "AP"})

# A course the student reports as completed is taken to be passed; the lowest passing
# letter is the only minimum that self-reported completion meets without a grade.
PASSING_FLOOR = "D"


def is_passing(grade: str) -> bool:
    if grade in NON_LETTER_PASS:
        return True
    return GRADE_POINTS.get(grade, 0.0) >= GRADE_POINTS[PASSING_FLOOR]


def grade_satisfies(earned: str | None, required: str | None) -> bool | None:
    """Whether `earned` meets the minimum `required`; None when the grade decides it but is
    unknown (`earned` is None: the student said they took the course, no transcript).

    Policy (from the System Design defaults):
    - no minimum, or a non-letter minimum (TR, S): any passing credit counts;
    - a letter minimum: only a letter grade with at least as many grade points;
      credit without a letter (TR, S, P, AP) does not meet it;
    - E/F, W, I, NP, U and audit never count.
    TODO: needs decision - Banner lists "Minimum Grade of TR", so transfer credit may rank
    above D in Banner's grade table; confirm with the registrar whether TR meets D or C.
    TODO: needs decision - repeat policy (latest vs best attempt) is the transcript's
    `Transcript.grades()`; this sees one grade per course.
    """
    floor_only = required is None or required not in GRADE_POINTS
    if earned is None:
        return True if floor_only or required == PASSING_FLOOR else None
    if not is_passing(earned):
        return False
    if floor_only:
        return True
    if earned not in GRADE_POINTS:
        return False
    return GRADE_POINTS[earned] >= GRADE_POINTS[required]
