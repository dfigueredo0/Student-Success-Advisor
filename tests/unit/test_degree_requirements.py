"""Degree requirements parsers against trimmed catalog pages."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import httpx
import pytest

from schemas.degree_requirements import ProgramRequirements

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "degree_requirements"
URL = "https://catalog.iit.edu/undergraduate/armour-college-engineering/computer-science/bs/"


def _load_scraper() -> ModuleType:
    path = ROOT / "pipelines" / "ingest" / "degree_requirements.py"
    spec = importlib.util.spec_from_file_location("degree_requirements", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dr = _load_scraper()


def page(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_program_links_keeps_only_undergraduate_program_pages() -> None:
    assert dr.program_links(page("index.html")) == [
        "https://catalog.iit.edu/undergraduate/armour-college-engineering/computer-science/bs/",
        "https://catalog.iit.edu/undergraduate/applied-technology/information-technology/bs/",
    ]


def test_program_header_and_total() -> None:
    p = dr.parse_program(page("program_cs.html"), URL)
    assert p["title"] == "Computer Science, B.S."
    assert p["total_hours"] == 127
    assert p["slug"] == "computer-science-bs"


def test_courses_and_or_alternatives() -> None:
    first = dr.parse_program(page("program_cs.html"), URL)["sections"][0]
    assert (first["title"], first["hours"]) == ("Computer Science Requirements", 36)
    cs, math = first["items"]
    assert (cs["kind"], cs["code"], cs["title"], cs["hours"]) == (
        "course",
        "CS 115",
        "Object-Oriented Programming I",
        4,
    )
    assert math["code"] == "MATH 332"
    assert math["alternatives"] == [{"code": "MATH 333", "title": "Matrix Algebra"}]


def test_rules_keep_text_and_hints() -> None:
    select, core, odd = dr.parse_program(page("program_cs.html"), URL)["sections"][1]["items"]
    assert select["text"].startswith("Select 12 credit hours of HUM or SSCI")
    assert select["hours"] == 12 and select["footnotes"] == [2]
    assert select["hints"]["min_level"] == 300
    assert select["hints"]["subjects"] == ["HUM", "SSCI"]
    assert core["hints"] == {"core_curriculum": True, "core_sections": ["B", "C"]}
    assert odd["text"] == "Something nobody planned for"


def test_footnotes_are_collected_verbatim() -> None:
    p = dr.parse_program(page("program_cs.html"), URL)
    assert p["notes"] == [
        {
            "table": 0,
            "number": 1,
            "text": "Choose from the approved list.",
            "borrowed": False,
        },
        {
            "table": 0,
            "number": 2,
            "text": "No more than 6 hours at the 200 level.",
            "borrowed": False,
        },
    ]


def test_unrecognised_row_is_flagged_for_review() -> None:
    review = dr.parse_program(page("program_cs.html"), URL)["needs_review"]
    assert any("Something nobody planned for" in r for r in review)


def test_page_without_class_hooks() -> None:
    """Header rows without areaheader, hour ranges and 'excluding' still come out sensibly."""
    p = dr.parse_program(page("program_plain.html"), "")
    section = p["sections"][0]
    assert (section["title"], section["hours"]) == ("Foundations", 7)
    phys1, phys2, rule = section["items"]
    assert (phys1["code"], phys1["hours"]) == ("PHYS 123", 4)
    assert (phys2["hours"], phys2["hours_max"]) == (3, 4)  # "3-4" is a range
    assert rule["hints"]["excluding"] == ["CS 100"]
    assert rule["footnotes"] == [1, 3]
    assert p["total_hours"] is None
    assert "total credit hours not found" in p["needs_review"]


def test_unknown_layout_is_flagged_not_crashed() -> None:
    p = dr.parse_program("<html><body><p>hi</p></body></html>")
    assert p["sections"] == []
    assert any("no requirement tables" in r for r in p["needs_review"])


def test_output_matches_contract() -> None:
    program = ProgramRequirements.model_validate(dr.parse_program(page("program_cs.html"), URL))
    rule = program.sections[1].items[0]
    assert rule.kind == "rule" and rule.hints.min_level == 300
    assert program.sections[0].items[1].alternatives[0].code == "MATH 333"
    json.dumps(program.model_dump(mode="json"))  # round-trips to plain JSON


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12", 12),
        (" 3 ", 3),
        ("3-4", None),  # hours_of is for single numbers; ranges go through hours_pair
        ("", None),
        ("TBD", None),
    ],
)
def test_hours_of(text: str, expected: int | None) -> None:
    assert dr.hours_of(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("300-level or above", {"min_level": 300}),
        ("400+ level HUM courses", {"min_level": 400, "subjects": ["HUM"]}),
        ("See Illinois Tech Core Curriculum", {"core_curriculum": True}),
        (
            "See Illinois Tech Core Curriculum, sections B and C",
            {"core_curriculum": True, "core_sections": ["B", "C"]},
        ),
        ("Any elective", {}),
    ],
)
def test_rule_hints(text: str, expected: dict) -> None:
    assert dr.rule_hints(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("(footnote 2)", [2]),
        ("footnotes 1 and 3", [1, 3]),
        ("footnotes 1, 2 & 4", [1, 2, 4]),
        ("no notes here", []),
    ],
)
def test_footnotes_in(text: str, expected: list[int]) -> None:
    assert dr.footnotes_in(text) == expected


# -- scraper (HTTP stubbed with httpx.MockTransport, no network) ---------------------------


def _scraper(handler) -> "dr.RequirementsScraper":
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return dr.RequirementsScraper(workers=2, min_interval=0, retries=2, client=client)


def _site(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("undergraduate-degree-programs/"):
        return httpx.Response(200, text=page("index.html"))
    if path.endswith("/information-technology/bs/"):
        return httpx.Response(404)
    return httpx.Response(200, text=page("program_cs.html"))


def test_fetch_retries_server_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dr.time, "sleep", lambda s: None)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, text="ok")

    with _scraper(handler) as s:
        assert s._fetch(URL) == "ok"
    assert len(calls) == 3


def test_fetch_gives_up_with_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dr.time, "sleep", lambda s: None)
    with (
        _scraper(lambda r: httpx.Response(500)) as s,
        pytest.raises(dr.RequirementsScraperException, match="failed after 3 tries"),
    ):
        s._fetch(URL)


def test_one_bad_page_does_not_lose_the_run() -> None:
    with _scraper(_site) as s:
        programs, failed, skipped = s.scrape(s.program_urls())
    assert [p.slug for p in programs] == ["computer-science-bs"]
    assert [f["slug"] for f in failed] == ["information-technology-bs"]
    assert skipped == []


def test_landing_page_is_skipped_not_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("undergraduate-degree-programs/"):
            return httpx.Response(200, text=page("index.html"))
        return httpx.Response(
            200, text="<html><body><h1>Department</h1><p>About us</p></body></html>"
        )

    with _scraper(handler) as s:
        programs, failed, skipped = s.scrape(s.program_urls())
    assert programs == [] and failed == []
    assert [x["slug"] for x in skipped] == ["computer-science-bs", "information-technology-bs"]


def test_course_pairs_are_taken_together() -> None:
    items = dr.parse_program(page("program_choices.html"), "")["sections"][0]["items"]
    pair = items[1]
    assert (pair["code"], pair["hours"]) == ("CS 115", 4)
    assert pair["together_with"] == [{"code": "CS 116", "title": "Object-Oriented Programming II"}]
    assert pair["title"] == "Object-Oriented Programming I"
    assert items[2]["together_with"][0]["code"] == "CS 201"


def test_select_rules_get_counts_and_options_flag() -> None:
    rules = [
        i
        for i in dr.parse_program(page("program_choices.html"), "")["sections"][0]["items"]
        if i["kind"] == "rule"
    ]
    seq, three, range_, upto = rules
    assert seq["hints"]["options_follow"] is True
    assert three["hints"]["choose"] == {"min": 3, "max": None, "unit": "courses"}
    assert range_["hints"]["choose"] == {"min": 2, "max": 4, "unit": "hours"}
    assert upto["hints"]["choose"] == {"min": None, "max": 2, "unit": "hours"}


def test_pair_and_choice_rows_no_longer_need_review() -> None:
    review = dr.parse_program(page("program_choices.html"), "")["needs_review"]
    assert not any(r.startswith("rule with hours") for r in review)
    assert not any("CS 115 & CS 116" in r for r in review)
    assert any("MATH 100 or MATH 101" in r for r in review)  # "or" in one cell stays flagged


def test_main_writes_validated_json_and_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = httpx.Client
    monkeypatch.setattr(
        dr.httpx, "Client", lambda **kw: real(**kw, transport=httpx.MockTransport(_site))
    )
    code = dr.main(
        [
            "--out",
            str(tmp_path),
            "--save-html",
            "--min-interval",
            "0",
            "--programs",
            "computer-science",
        ]
    )
    assert code == 0
    saved = ProgramRequirements.model_validate_json(
        (tmp_path / "computer-science-bs.json").read_text()
    )
    assert saved.total_hours == 127
    raw = json.loads((tmp_path / "computer-science-bs.json").read_text())
    assert "hints" not in raw["sections"][0]["items"][0]  # defaults are not written
    assert raw["sections"][0]["items"][0]["kind"] == "course"
    index = json.loads((tmp_path / "index.json").read_text())
    assert index["programs"][0]["slug"] == "computer-science-bs"
    assert index["programs"][0]["needs_review"] >= 1 and index["failed"] == []
    assert (tmp_path / "html" / "computer-science-bs.html").exists()
    assert not list(tmp_path.glob("*.tmp"))  # atomic writes leave nothing behind


def test_main_offline_html_flag(capsys: pytest.CaptureFixture[str]) -> None:
    assert dr.main(["--html", str(FIXTURES / "program_cs.html")]) == 0
    assert json.loads(capsys.readouterr().out)["total_hours"] == 127


def test_prose_mentioning_codes_is_a_rule_not_a_course() -> None:
    html = (
        '<table class="sc_courselist"><tr class="areaheader"><td colspan="2">X</td></tr>'
        '<tr><td class="codecol">Students wishing to take BME 200 , ECE 211 should use a free '
        'elective</td><td></td><td class="hourscol"></td></tr>'
        '<tr><td colspan="2"><span class="courselistcomment">Recommended electives include:'
        "</span></td><td></td></tr>"
        '<tr><td class="codecol">Choose 3 courses from the below</td><td></td>'
        '<td class="hourscol">9</td></tr></table>'
    )
    prose, lead_in, choose = dr.parse_program(html)["sections"][0]["items"]
    assert prose["kind"] == "rule" and "BME 200" in prose["text"]
    assert lead_in["hints"] == {"options_follow": True}
    assert choose["hints"]["choose"] == {"min": 3, "max": None, "unit": "courses"}


def test_footnote_markers_leave_text_and_link_to_notes() -> None:
    p = dr.parse_program(page("program_tracks.html"), URL)
    course, select, core = p["sections"][0]["items"]
    assert course["title"] == "Object-Oriented Programming II" and course["footnotes"] == [1]
    assert select["text"] == "Select 12 credit hours" and select["footnotes"] == [2]
    assert p["notes"][1]["text"].startswith("Any CS course at the 300-level")
    assert len(p["notes"]) == 2
    # the level rule lives in the footnote, so it is parsed from there too
    assert select["footnote_hints"]["min_level"] == 300
    assert select["footnote_hints"]["excluding"] == ["CS 401", "CS 402"]
    assert core["hints"]["core_sections"] == ["B", "C"]


def test_tables_are_grouped_with_their_own_totals() -> None:
    p = dr.parse_program(page("program_tracks.html"), URL)
    assert p["title"] == "Computer Science, B.S."
    assert p["total_hours"] == 121  # the first table; tracks have their own totals
    main, track = p["sections"][0], p["sections"][-1]
    assert (main["group"], main["group_total_hours"]) == ("Degree Requirements", 121)
    assert (track["group"], track["group_total_hours"]) == (
        "Specialization in Artificial Intelligence",
        12,
    )
    minimum = track["items"][-1]
    assert minimum["hints"]["choose"] == {"min": 3, "max": None, "unit": "courses"}


def test_header_footnotes_are_kept_and_each_table_has_its_own_notes() -> None:
    dl = lambda *texts: (  # noqa: E731
        '<dl class="sc_footnotes">'
        + "".join(f"<dt><sup> {i} </sup></dt><dd><p>{x}</p></dd>" for i, x in enumerate(texts, 1))
        + "</dl>"
    )
    html = (
        '<div id="requirementstextcontainer"><table class="sc_courselist">'
        '<tr class="areaheader"><td colspan="2">Communication Elective<sup>2</sup></td>'
        '<td class="hourscol"> (3)</td></tr>'
        '<tr><td class="codecol"><a>COM 321</a></td><td>Tech Comm</td>'
        '<td class="hourscol">3</td></tr>'
        "</table>" + dl("First.", "Must be COM 321.") + "<h3>Honors</h3>"
        '<table class="sc_courselist"><tr><td colspan="2"><span class="courselistcomment">'
        'Select six hours<sup>1</sup></span></td><td class="hourscol">6</td></tr></table>'
        + dl("Any course at the 400-level or higher.")
        + '<table class="sc_plangrid"><tr><td>x</td></tr></table>'
        + dl("Plan note 1.", "Plan note 2.", "Plan note 3.")
        + "</div>"
    )
    p = dr.parse_program(html)
    head = p["sections"][0]
    assert head["footnotes"] == [2] and head["hours"] == 3 and head["table"] == 0
    honors = p["sections"][1]
    assert honors["table"] == 1 and honors["items"][0]["footnotes"] == [1]
    assert honors["items"][0]["footnote_hints"] == {"min_level": 400}  # its own table's note
    assert [(n["table"], n["number"]) for n in p["notes"]] == [(0, 1), (0, 2), (1, 1)]
    assert not any("footnotes" in r for r in p["needs_review"])


def test_real_computer_science_page() -> None:
    """The saved catalog page (Fall 2026): 7 requirement tables, footnotes per table."""
    p = ProgramRequirements.model_validate(
        dr.parse_program(page("real_computer_science_bs.html"), URL)
    )
    assert p.title == "Bachelor of Science in Computer Science"
    assert p.total_hours == 121
    first = p.sections[0]
    assert (first.group, first.title, first.hours) == (
        "Required Courses",
        "Computer Science Requirements",
        36,
    )
    assert [s.group for s in p.sections if s.table > 0 and s.table != 2][:1] == [
        "Artificial Intelligence"
    ]
    assert {s.table for s in p.sections} == set(range(7))
    notes = {(n.table, n.number): n.text for n in p.notes}
    assert sorted(notes) == [(0, 1), (0, 2), (0, 3), (2, 1), (2, 2), (2, 3)]  # plan grid excluded
    assert notes[(2, 3)].startswith("Students must take at least two adviser approved 500-level")
    electives = next(i for s in p.sections for i in s.items if i.text == "Select 12 credit hours")
    assert electives.footnotes == [2]
    assert electives.footnote_hints.min_level == 300
    assert electives.footnote_hints.excluding == ["CS 401", "CS 402"]
    codes = {i.code for s in p.sections for i in s.items if i.kind == "course"}
    assert {"CS 331", "MATH 332", "CS 549"} <= codes
    assert not any("with no note text" in r for r in p.needs_review)


def test_footnotes_after_the_plan_grid_are_borrowed_and_marked() -> None:
    html = (
        '<div><h2>Required Courses</h2><table class="sc_courselist">'
        '<tr><td class="codecol"><a>CHEM 321</a></td><td>Instrumental Analysis<sup>1</sup></td>'
        '<td class="hourscol">3</td></tr></table>'
        '<h2>Curriculum</h2><table class="sc_plangrid"><tr><td>Year 1</td></tr></table>'
        '<dl class="sc_footnotes"><dt><sup> 1 </sup></dt><dd><p>CHEM 321 or CHEM 434.</p></dd></dl>'
        '<h2>Specializations</h2><table class="sc_courselist"><tr><td class="codecol">'
        '<a>BIOL 100</a></td><td>Intro</td><td class="hourscol">3</td></tr></table></div>'
    )
    p = dr.parse_program(html)
    assert p["notes"] == [
        {"table": 0, "number": 1, "text": "CHEM 321 or CHEM 434.", "borrowed": True}
    ]
    assert any("not beside it" in r for r in p["needs_review"])
    assert not any("no note text" in r for r in p["needs_review"])
    # the specialization table cites nothing, so it does not inherit the grid's block
    assert all(n["table"] == 0 for n in p["notes"])


def test_real_biochemistry_page_groups_options_and_ranges() -> None:
    """Indented rows belong to the rule above; "13 OR 14" is a range; notes sit before the table."""
    p = ProgramRequirements.model_validate(
        dr.parse_program(page("real_biochemistry_ai_bs.html"), URL)
    )
    assert p.total_hours == 121
    stats = next(s for s in p.sections if s.title == "Statistics Requirement")
    assert (stats.hours, stats.hours_max) == (3, 4)

    items = [i for s in p.sections if s.table == 1 for i in s.items]
    rules = {i.text: i for i in items if i.kind == "rule"}
    chem = rules["Chemistry"]
    assert (chem.hours, chem.hours_max) == (13, 14)
    kids = items[items.index(chem) + 1 :][: chem.children]
    assert [k.code for k in kids] == ["CHEM 247", "CHEM 321", "CHEM 415", "CHEM 434"]
    assert chem.children_basis == "indent"

    computation = rules["Computation"]
    inner = rules["Select one of the following"]
    assert computation.children == 8  # CS 116, CS 331, CS 422, the rule, and its 4 courses
    assert (inner.children, inner.children_basis) == (4, "following_courses")

    note = p.notes[0]
    assert (note.table, note.number, note.borrowed) == (1, 1, True)
    assert "CHEM 321 or CHEM 434" in note.text
    cs331 = next(i for i in items if i.code == "CS 331")
    assert cs331.footnotes == [1]
    assert not any("no note text" in r for r in p.needs_review)


# -- core curriculum ------------------------------------------------------------------------


def _load_core() -> ModuleType:
    import sys

    ingest = str(ROOT / "pipelines" / "ingest")
    if ingest not in sys.path:
        sys.path.insert(0, ingest)
    path = ROOT / "pipelines" / "ingest" / "core_curriculum.py"
    spec = importlib.util.spec_from_file_location("core_curriculum", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_core_curriculum_sections_and_rules() -> None:
    from schemas.core_curriculum import CoreCurriculum

    core = CoreCurriculum.model_validate(_load_core().parse_core(page("real_core_curriculum.html")))
    sections = {s.id: s for s in core.sections}
    assert [s.title for s in core.sections] == [
        "Writing and Communication",
        "Humanities 100-Level Course",
        "Human Sciences Module",
        "STEM Module",
        "Collaborative Interdisciplinary and/or Professional Experience",
    ]
    # every rule's wording is still on the saved page
    assert [r for s in core.sections for r in s.needs_review] == []

    c = {r.id: r for r in sections["C"].requirements}
    assert sections["C"].hours_min == 18 and c["C.total"].hours_min == 18
    assert (c["C.humanities"].courses_min, c["C.humanities"].level_min) == (2, 200)
    assert c["C.humanities"].attribute == "H"
    assert (c["C.social"].courses_min, c["C.social_upper"].level_min) == (3, 200)
    assert c["C.social_fields"].fields_min == 2
    assert c["C.remaining"].excluding == ["COM 101", "COM 111"]

    assert sections["B"].hours_min == 3
    assert [x.code for x in sections["B"].courses] == [
        "HUM 100",
        "HUM 102",
        "HUM 104",
        "HUM 106",
        "HUM 108",
    ]
    assert sections["B"].open_options == ["or any other HUM 100 -level elective"]
    assert {x.code for x in sections["D"].courses} >= {"CS 104", "CS 201", "PHYS 240"}
    assert sections["E"].footnotes and "UGSC" in sections["E"].footnotes[0]
    assert core.notes and "minor" in core.notes[0]


def test_core_rule_with_changed_wording_is_flagged() -> None:
    html = page("real_core_curriculum.html").replace(
        "At least two Humanities courses", "At least three Humanities courses"
    )
    core = _load_core().parse_core(html)
    review = next(s for s in core["sections"] if s["id"] == "C")["needs_review"]
    assert any(r.startswith("C.humanities") for r in review)
