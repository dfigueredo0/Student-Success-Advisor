"""Resume text -> the two education facts the Career agent uses. Pure: text comes in as a string.

Skills are read by domain.skills.extract_skills. Nothing here extracts a name, contact detail,
employer, job title or date of employment, so none of them can reach the profile.
"""

import re

# Both patterns start only where a word starts (the lookbehinds). Without that, one long
# unbroken run of characters is retried from every position: quadratic time on a page or PDF
# built to stall the server.
_EMAIL = re.compile(r"(?<!\S)\S+@\S+")
# Profile links read as skills otherwise ("github.com/jane" is not GitHub experience). ".net"
# is left out of the bare-domain list: ASP.NET and .NET are skills.
_LINK = re.compile(
    r"(?:https?://|www\.)\S+"
    r"|(?<![\w.-])[\w-]+(?:\.[\w-]+)*\.(?:com|io|org|edu|dev|me|app)\b(?:/\S*)?",
    re.I,
)

# Highest first. An abbreviation without periods counts only before " in ": "MS in Data
# Science" is a degree, "MS Excel" is Microsoft.
_DEGREES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("doctorate", re.compile(r"\bPh\.?\s?D\b|\bDoctor(?:ate)?\s+(?:of|in)\b", re.I)),
    (
        "master",
        re.compile(
            r"\bMaster(?:'s|s)?\b|\bM\.(?:S|A|Eng|Arch)\.|\bM\.B\.A\.|\bMBA\b"
            r"|\b(?:MS|MA|MEng|MArch)\s+in\b"
        ),
    ),
    (
        "bachelor",
        re.compile(
            r"\bBachelor(?:'s|s)?\b|\bB\.(?:S|A|Eng|Arch)\.|\b(?:BS|BA|BSc|BEng|BArch)\s+in\b"
        ),
    ),
    ("associate", re.compile(r"\bAssociate(?:'s)?\s+(?:of|in|degree)\b|\bA\.A\.S?\.", re.I)),
)
_GRADUATION_CUE = re.compile(r"\b(?:expected|anticipated|graduation|graduating|class of)\b", re.I)
_YEAR = re.compile(r"\b(20[0-4]\d)\b")
_NEAR = 80  # characters after a degree or graduation word in which its year is looked for


def scrub(text: str) -> str:
    """`text` without email addresses and links."""
    return _LINK.sub(" ", _EMAIL.sub(" ", text))


def education(text: str) -> tuple[str | None, int | None]:
    """(highest degree level named, latest graduation year next to a degree), None when absent.

    The level is "associate", "bachelor", "master" or "doctorate". A student partway through a
    degree lists it with an expected date, so the latest year is the one they finish.
    """
    level = None
    cues = list(_GRADUATION_CUE.finditer(text))
    for name, pattern in _DEGREES:
        found = list(pattern.finditer(text))
        level = level or (name if found else None)
        cues += found
    years = [int(y) for m in cues for y in _YEAR.findall(text[m.start() : m.end() + _NEAR])]
    # Only next to a degree: "Expected to ship in 2030" on its own says nothing about school.
    return level, (max(years) if years and level else None)
