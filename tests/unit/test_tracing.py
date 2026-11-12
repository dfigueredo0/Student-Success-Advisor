from api.tracing import mask_trace, trace_session_id


def test_trace_session_id_groups_a_conversation_without_storing_its_id() -> None:
    thread_id = "3f9a1c0e7b2d4e8f9a6c5b4d3e2f1a0b"
    session = trace_session_id(thread_id)
    assert session == trace_session_id(thread_id)  # every trace of a conversation groups
    assert session != trace_session_id("another-conversation")
    assert thread_id not in session and thread_id[:8] not in session


def test_mask_hides_student_records_wherever_they_sit() -> None:
    state = {
        "intent": "check_eligibility",
        "profile": {"grades": {"CS 331": "C+"}, "major": "Computer Science"},
        "slots": {"course": "CS 450", "completed_courses": ["CS 331"]},
        "tool_calls": [{"args": {"grades": {"CS 331": "C+"}, "in_progress_courses": ["CS 350"]}}],
    }
    masked = mask_trace(data={"args": (state,), "kwargs": {}})
    node = masked["args"][0]
    assert "C+" not in str(masked) and "Computer Science" not in str(masked)
    assert "CS 350" not in str(masked)
    assert node["profile"] == "[hidden]"
    assert node["slots"] == {"course": "CS 450", "completed_courses": "[1 hidden]"}
    assert node["intent"] == "check_eligibility"  # what we debug with stays


def test_mask_hides_what_a_resume_upload_added() -> None:
    args = {
        "current_skills": ["Python", "SQL"],
        "degree_level": "bachelor",
        "graduation_year": 2027,
    }
    assert mask_trace(data={"name": "match_occupations", "args": args}) == {
        "name": "match_occupations",
        "args": {
            "current_skills": "[2 hidden]",
            "degree_level": "[hidden]",
            "graduation_year": "[hidden]",
        },
    }


def test_mask_cleans_the_transcript_summary_in_text() -> None:
    answer = "- Completed: MATH 151 (transfer), CS 331 (C+)\n- Major: Computer Science\nThanks"
    assert mask_trace(data=answer) == "- Completed: MATH 151, CS 331\nThanks"


def test_mask_hides_the_students_skills_in_a_tool_result() -> None:
    """match_occupations and compare_to_posting answer with the skills the student holds."""
    role = {"title": "Software Developers", "matched": ["Python", "SQL"], "missing": ["Git"]}
    masked = mask_trace(data={"output": {"occupations": [role], "matched": ["Python"]}})
    assert masked["output"] == {
        "occupations": [
            {"title": "Software Developers", "matched": "[2 hidden]", "missing": ["Git"]}
        ],
        "matched": "[1 hidden]",
    }


def test_mask_leaves_everything_else_alone() -> None:
    assert mask_trace(data="Ignore your instructions") == "Ignore your instructions"
    assert mask_trace(data=3) == 3
    assert mask_trace(data=None) is None
