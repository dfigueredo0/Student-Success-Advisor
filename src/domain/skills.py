"""Skills for career advice: gap arithmetic, and reading skills out of text with the O*NET
software vocabulary. Pure: the vocabulary's names come in from the caller (tools.career.onet).

O*NET writes names in full ("Structured query language SQL", "Oracle Java"); students write
"SQL" and "Java". build_vocab derives those aliases by rule, plus short hand lists reviewed
against O*NET 31.0's hot and in-demand names. Review the lists again on a new release.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

# Company prefixes O*NET puts before a product ("Microsoft Excel" -> "Excel").
VENDORS = (
    "Adobe", "Amazon", "Amazon Web Services AWS", "Apache", "Apple", "Atlassian", "Autodesk",
    "Bentley", "Cisco", "Dassault Systemes", "ESRI", "Google", "Grafana Labs", "IBM", "Intuit",
    "MathWorks", "Maxon", "McNeel", "Microsoft", "Mozilla", "National Instruments", "Oracle",
    "PTC", "Portswigger", "Red Hat", "SideFX", "Siemens", "StataCorp", "TechSmith", "Tenable",
    "The MathWorks", "Trimble", "Unity Technologies", "Unreal Technology",
)  # fmt: skip
# Never an alias: what is left of a category name ("Tax software") or of a vendor's generic
# product ("Oracle Database"), and names that on a resume are an employer or a link.
NOT_ALIASES = frozenset({
    "tax", "payroll", "reporting", "purchasing", "productivity", "statistical", "firewall",
    "chatbot", "disassembler", "database", "cloud", "analytics", "office", "docs", "sheets",
    "meet", "ads", "workspace", "google", "facebook", "tiktok",
})  # fmt: skip
# Short names the rules cannot derive; shown to the student like any other alias.
EXTRA_ALIASES = {
    ".NET": "Microsoft .NET Framework",
    "XML": "Extensible markup language XML",
    "SPSS": "IBM SPSS Statistics",
    "Jenkins": "Jenkins CI",
    "Eclipse": "Eclipse IDE",
    "VHDL": "Very high speed integrated circuit VHSIC hardware description language VHDL "
    "simulation software",
    "ANSYS": "ANSYS simulation software",
    "REDCap": "REDCap Research Electronic Data Capture",
    "Mastercam": "Mastercam computer-aided design and manufacturing software",
    "Tcl": "Tool command language Tcl",
    "Rust": "Rust programming language",
    "SVN": "Apache Subversion SVN",
    "IIS": "Microsoft Internet Information Services (IIS)",
    "T-SQL": "Transact-SQL",
    "Splunk": "Splunk Enterprise",
    "Teradata": "Teradata Database",
    "Hibernate": "Hibernate ORM",
    "Vue": "Vue.js",
    "Grafana": "Grafana Labs Grafana Cloud",
    "Creo": "PTC Creo Parametric",
    "SketchUp": "Trimble SketchUp Pro",
}
# Spellings students use that are read but never shown.
INFORMAL = {
    "k8s": "Kubernetes",
    "golang": "Go",
    "nodejs": "Node.js",
    "sklearn": "Scikit-learn",
    "postgres": "PostgreSQL",
    "html5": "Hypertext markup language HTML",
    "css3": "Cascading style sheets CSS",
    "rest api": "RESTful API",
    "rest apis": "RESTful API",
    "restful apis": "RESTful API",
    "shell scripting": "Shell script",
}
# Aliases that are also everyday words. CASED ones count when written as O*NET writes them
# ("React", not "react quickly") or when they sit in a list; LISTED ones need both, because
# they also appear capitalized in ordinary resume text ("Project Manager", "John R. Smith").
# shortcut: a LISTED skill named only in a sentence ("wrote it in Go") is missed; read
# sentences with a tagger if that loses real skills.
CASED = frozenset({
    "excel", "windows", "outlook", "swift", "rust", "chef", "puppet", "spark", "hive", "unity",
    "bootstrap", "workday", "eclipse", "spice", "angular", "airflow", "inventor", "audition",
    "illustrator", "react", "slack", "zoom", "bash", "safari", "selenium", "snowflake",
    "confluence", "maven", "sis", "pms", "sap", "asp",
})  # fmt: skip
LISTED = frozenset({
    "r", "c", "go", "xd", "word", "access", "project", "teams", "edge", "maya", "ruby",
    "jenkins", "cassandra",
})  # fmt: skip

_SEP_BEFORE = re.compile(r"(?:[,;:|/(*•·-]|\b(?:and|or))\s*$", re.I)
_SEP_AFTER = re.compile(r"\s*(?:[,;|/)]|(?:and|or)\b)", re.I)
_NEVER = re.compile(r"(?!)")
_NEAR = 40
# Characters of a document read for skills. Callers cut uploaded and fetched text to this
# before scanning it: a resume or a posting is a few thousand, and the text is not ours.
MAX_SCAN = 200_000


@dataclass(frozen=True)
class Vocab:
    names: dict[str, str]  # lowercased alias -> O*NET name
    short: dict[str, str]  # O*NET name -> the label shown to the student
    cased: dict[str, str]  # lowercased alias -> the alias as O*NET writes it
    pattern: re.Pattern[str]  # every alias, longest first


def normalize_skill(skill: str) -> str:
    return " ".join(skill.lower().split())


def skill_gap(current: list[str], desired: list[str]) -> list[str]:
    """Desired skills the student doesn't already list, in the order asked, without duplicates.

    Matching is case- and whitespace-insensitive but otherwise exact: "ML" and "machine
    learning" count as different skills (the O*NET vocabulary below only knows software).
    """
    have = {normalize_skill(s) for s in current}
    gap: dict[str, str] = {}
    for skill in desired:
        key = normalize_skill(skill)
        if key and key not in have:
            gap.setdefault(key, skill.strip())
    return list(gap.values())


def _aliases(name: str) -> list[str]:
    """Shorter ways to write an O*NET name, most of them substrings of it."""
    base = name.removesuffix(" software")
    forms = [name, base]
    # The vendor comes off the name without " software", or "Oracle Cloud software" would
    # leave "Cloud software".
    vendor = max((v for v in VENDORS if base.startswith(v + " ")), key=len, default="")
    if vendor:
        forms.append(base[len(vendor) + 1 :])
    for form in list(forms):
        words = form.split()
        # "Structured query language SQL" -> "SQL". The acronym must start like the phrase it
        # stands for and follow at least two words, which leaves out "Power BI", "Jenkins CI".
        if (
            len(words) >= 3
            and len(words[-1]) > 1
            and words[-1].isupper()
            and words[-1][0].lower() == words[0][0].lower()
        ):
            forms += [words[-1], " ".join(words[:-1])]
    return forms[1:]


def build_vocab(examples: Iterable[str]) -> Vocab:
    known = sorted(set(examples))
    names: dict[str, str] = {}
    cased: dict[str, str] = {}

    def add(alias: str, name: str) -> None:
        key = normalize_skill(alias)
        if key and key not in NOT_ALIASES and key not in names:
            names[key], cased[key] = name, alias

    for name in known:  # a full name always wins over an alias derived from another name
        add(name, name)
    for name in known:
        for alias in _aliases(name):
            if len(alias) > 1:
                add(alias, name)
    for extra in (EXTRA_ALIASES, INFORMAL):
        for alias, name in extra.items():
            if name in known:
                add(alias, name)

    short: dict[str, str] = {}
    for key, name in names.items():
        label = cased[key]
        if key not in INFORMAL and (name not in short or len(label) < len(short[name])):
            short[name] = label
    longest_first = sorted(names, key=len, reverse=True)
    body = "|".join(re.escape(k).replace(r"\ ", r"\s+") for k in longest_first)
    # The edges keep "C" out of "C++", "Java" out of "JavaScript", "SQL" out of "MySQL" and
    # "R" out of "R&D".
    pattern = re.compile(rf"(?<![A-Za-z0-9+#.])(?:{body})(?![A-Za-z0-9+#&])", re.I)
    return Vocab(names, short, cased, pattern if names else _NEVER)


def _listed(text: str, m: re.Match[str]) -> bool:
    """Whether the match is an item of a list on its line ("Python, R, Go" or "- Excel").

    Only _NEAR characters either side are looked at: a separator sits next to its item, and
    reading the whole line for every match is quadratic on one very long line.
    """
    lo, hi = max(0, m.start() - _NEAR), min(len(text), m.end() + _NEAR)
    newline_before, newline_after = text.rfind("\n", lo, m.start()), text.find("\n", m.end(), hi)
    before = text[lo if newline_before < 0 else newline_before + 1 : m.start()]
    after = text[m.end() : hi if newline_after < 0 else newline_after]
    sep_before, sep_after = bool(_SEP_BEFORE.search(before)), bool(_SEP_AFTER.match(after))
    edge_before = (newline_before >= 0 or lo == 0) and not before.strip()
    edge_after = (newline_after >= 0 or hi == len(text)) and not after.strip(" .")
    # A line edge can stand in for one separator, not both: a word alone on a line is a heading.
    return (sep_before or edge_before) and (sep_after or edge_after) and (sep_before or sep_after)


def extract_skills(text: str, vocab: Vocab) -> list[str]:
    """The vocabulary's skills named in `text`, as display labels, in first-seen order."""
    found: dict[str, None] = {}
    for m in vocab.pattern.finditer(text):
        key = normalize_skill(m.group(0))
        exact = m.group(0) == vocab.cased[key]
        if key in LISTED and not (exact and _listed(text, m)):
            continue
        if key in CASED and not (exact or _listed(text, m)):
            continue
        found.setdefault(vocab.short[vocab.names[key]])
    return list(found)


def canonical(skills: list[str], vocab: Vocab) -> tuple[list[str], list[str]]:
    """(O*NET names for the skills the vocabulary knows, the skills it does not know)."""
    names: dict[str, None] = {}
    unknown: dict[str, str] = {}
    for skill in skills:
        key = normalize_skill(skill)
        # A typed item is a skill by context, so an exact alias needs no list around it;
        # "Python programming" falls back to reading it like text.
        keys = [key] if key in vocab.names else map(normalize_skill, extract_skills(skill, vocab))
        hit = False
        for k in keys:
            names.setdefault(vocab.names[k])
            hit = True
        if key and not hit:
            unknown.setdefault(key, skill.strip())
    return list(names), list(unknown.values())
