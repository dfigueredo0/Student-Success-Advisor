"""Resume text -> skills, degree level and graduation year, and nothing that identifies."""

import json
import time
from pathlib import Path

import pytest

from domain.resume import education, scrub
from domain.skills import build_vocab
from tools.career import onet
from tools.career import resume_parser as tool

# Synthetic: laid out like a student resume, holds no real person's data.
TEXT = (Path(__file__).parents[1] / "fixtures" / "resume" / "synthetic.txt").read_text()
VOCAB = build_vocab([
    "Python", "Oracle Java", "C++", "Structured query language SQL", "JavaScript", "R", "Git",
    "GitHub", "Docker", "Linux", "Amazon Web Services AWS software", "React", "Microsoft Excel",
    "RESTful API", "Spring Boot", "Kubernetes", "JUnit", "Atlassian JIRA", "Django",
    "PostgreSQL", "Microsoft Project",
])  # fmt: skip
SKILLS = [
    "Python", "Java", "C++", "SQL", "JavaScript", "R", "Git", "Docker", "Linux", "AWS", "React",
    "Excel", "RESTful API", "Spring Boot", "Kubernetes", "JUnit", "JIRA", "Django", "PostgreSQL",
]  # fmt: skip


@pytest.fixture
def vocab(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onet, "vocabulary", lambda: VOCAB)


@pytest.fixture
def resume(monkeypatch: pytest.MonkeyPatch, vocab: None) -> None:
    """Any upload reads as the synthetic resume."""
    monkeypatch.setattr(tool, "pdf_text", lambda content, what: TEXT)


@pytest.mark.usefixtures("resume")
def test_reads_skills_degree_and_graduation_year() -> None:
    assert tool.parse_resume(b"%PDF-") == {
        "skills": SKILLS,
        "degree_level": "bachelor",
        "graduation_year": 2027,
    }


@pytest.mark.usefixtures("resume")
def test_nothing_identifying_is_kept() -> None:
    kept = json.dumps(tool.parse_resume(b"%PDF-"))
    # name, email, phone, city, employer, GPA, and the profile links (GitHub is also a skill)
    for private in ("Test", "Student", "hawk", "555", "Chicago", "Examplecorp", "3.6", "GitHub"):
        assert private not in kept


@pytest.mark.usefixtures("vocab")
@pytest.mark.parametrize(
    "content",
    [b"plain text", b"%PDF-1.7 not really a pdf", b"%PDF-" + b"0" * tool.MAX_BYTES],
    ids=["not-pdf", "corrupt", "too-large"],
)
def test_unreadable_uploads_are_rejected_without_calling_them_transcripts(content: bytes) -> None:
    with pytest.raises(tool.ResumeRejected) as exc:
        tool.parse_resume(content)
    assert "transcript" not in str(exc.value)


@pytest.mark.usefixtures("vocab")
def test_scanned_pdf_without_text_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool, "pdf_text", lambda content, what: " \n \n")
    with pytest.raises(tool.ResumeRejected, match="couldn't find any text"):
        tool.parse_resume(b"%PDF-")


@pytest.mark.usefixtures("vocab")
def test_pdf_without_skills_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool, "pdf_text", lambda content, what: "Lorem ipsum dolor sit amet. " * 9)
    with pytest.raises(tool.ResumeRejected, match="skills"):
        tool.parse_resume(b"%PDF-")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("B.S. in Computer Science, Expected May 2027", ("bachelor", 2027)),
        ("BS in Mechanical Engineering | Class of 2026", ("bachelor", 2026)),
        (
            "Master of Science in Data Science\nAug 2025 - May 2027\n"
            "Bachelor of Engineering, 2021 - 2025",
            ("master", 2027),
        ),
        ("Ph.D. Candidate, Electrical Engineering (2029)", ("doctorate", 2029)),
        ("Associate of Science, Class of 2024", ("associate", 2024)),
        ("MS Excel, MS Word and a BS detector", (None, None)),  # Microsoft, not a degree
        ("Teller at a bank, 2019-2023", (None, None)),  # a job's dates are not a graduation
        ("Bachelor of Arts in Design", ("bachelor", None)),
    ],
)
def test_education(text: str, expected: tuple[str | None, int | None]) -> None:
    assert education(text) == expected


@pytest.mark.parametrize(
    "hostile", ["x" * 40_000, "a-" * 20_000, "a." * 20_000], ids=["no-at-sign", "dashes", "dots"]
)
def test_scrub_stays_fast_on_text_built_to_stall_it(hostile: str) -> None:
    """A fetched page or a crafted PDF is someone else's text: one long unbroken run must not
    make the email and link patterns retry from every character."""
    start = time.perf_counter()
    scrub(hostile)
    assert time.perf_counter() - start < 0.5


def test_only_the_start_of_a_huge_document_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onet, "vocabulary", lambda: VOCAB)
    huge = "Python. " + "filler " * 60_000 + "Docker"  # the cap falls inside the filler
    monkeypatch.setattr(tool, "pdf_text", lambda content, what: huge)
    assert tool.parse_resume(b"%PDF-")["skills"] == ["Python"]


def test_scrub_drops_emails_and_links_but_not_dotted_skills() -> None:
    cleaned = scrub("a.b@x.com https://github.com/jane www.site.org/p linkedin.com/in/jane ASP.NET")
    assert cleaned.split() == ["ASP.NET"]
