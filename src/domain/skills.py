"""Skill-gap arithmetic for career advice. Pure: skills come in as already-parsed strings."""


def normalize_skill(skill: str) -> str:
    return " ".join(skill.lower().split())


def skill_gap(current: list[str], desired: list[str]) -> list[str]:
    """Desired skills the student doesn't already list, in the order asked, without duplicates.

    Matching is case- and whitespace-insensitive but otherwise exact: "ML" and "machine
    learning" count as different skills until an O*NET skill taxonomy is loaded.
    """
    have = {normalize_skill(s) for s in current}
    gap: dict[str, str] = {}
    for skill in desired:
        key = normalize_skill(skill)
        if key and key not in have:
            gap.setdefault(key, skill.strip())
    return list(gap.values())
