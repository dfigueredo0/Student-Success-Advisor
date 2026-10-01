def unmet_prerequisites(prerequisite_courses: list[str], completed: list[str]) -> list[str]:
    """Prerequisite course codes the student has not completed.

    TODO: needs impl - climb the prerequisite expression tree. Banner expressions mix
    AND/OR, minimum grades, and concurrent enrollment ("(CS 331 or CS 401) and CS 350*");
    this treats every named course as required, so OR-alternatives are over-reported
    as missing. Transitive prerequisites are not followed either.
    """
    done = set(completed)
    return [code for code in prerequisite_courses if code not in done]
