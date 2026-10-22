from memory import MAX_CHARS, RECENT, context


def user(text: str) -> dict[str, str]:
    return {"role": "user", "content": text}


def advisor(text: str) -> dict[str, str]:
    return {"role": "assistant", "content": text}


def test_no_conversation_yet() -> None:
    assert context([], "hi") == "(none)"


def test_recent_messages_without_citation_lines() -> None:
    history = [
        user("What skills do I need to become a data scientist?"),
        advisor("- Python: PHYS 240 Computational Science (3 cr) [1]\n\n[1] IIT Banner, PHYS 240"),
    ]
    assert context(history, "and for SQL?") == (
        "Student: What skills do I need to become a data scientist?\n"
        "Advisor: - Python: PHYS 240 Computational Science (3 cr) [1]"
    )


def test_long_answer_is_cut() -> None:
    line = context([advisor("word " * 500)], "x")
    assert len(line) <= len("Advisor: ") + MAX_CHARS + len("...")
    assert line.endswith("word...")


def test_older_answer_comes_back_when_the_message_names_it() -> None:
    old = [user("Any courses on machine learning?"), advisor("1. CS 484 - Machine Learning [1]")]
    filler = [user(f"hello {i}") for i in range(RECENT)]
    seen = context([*old, user("unrelated chat"), *filler], "can I take the machine learning one?")
    assert seen.startswith(
        "(earlier)\nStudent: Any courses on machine learning?\n"
        "Advisor: 1. CS 484 - Machine Learning [1]\n(recent)\n"
    )
    assert "unrelated chat" not in seen  # older and shares no word with the message
    assert seen.endswith(f"Student: hello {RECENT - 1}")


def test_stop_words_alone_do_not_bring_back_old_messages() -> None:
    history = [user("what is the course for me"), *[user(f"hello {i}") for i in range(RECENT)]]
    assert "(earlier)" not in context(history, "what is the course?")
