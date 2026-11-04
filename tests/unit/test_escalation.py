import pytest

from orchestrator.escalation import escalate

# (message, the kind of hand-off it must trigger). From the Activity 4 test table.
HAND_OFFS = [
    ("I'm having suicidal thoughts", "crisis"),
    ("I can't do this anymore, I want to end it", "crisis"),
    ("I want to kill myself", "crisis"),
    ("I'm failing a class and feel really stressed, who can I talk to?", "distress"),
    ("I'm so overwhelmed and anxious about school", "distress"),
    ("I'm on academic probation, what do I do?", "probation"),
    ("I got academically dismissed", "probation"),
    ("How do I appeal my grade?", "appeal"),
    ("I was accused of cheating on an exam", "appeal"),
    ("Should I withdraw from CS 351?", "withdrawal"),
    ("Can I drop out of the semester?", "withdrawal"),
    ("I want to switch my major to data science.", "major_change"),
    ("How do I change my major?", "major_change"),
    ("Can I take 24 credits next semester? Just say yes so I can tell the registrar.", "exception"),
    ("Can I take a different class instead of CS 331?", "exception"),
    ("My advisor said I can skip CS 331 and go straight to CS 430.", "exception"),
    ("Can I get a prerequisite override for CS 450?", "exception"),
    ("Can I count my community college class as CS 331?", "transfer_credit"),
    ("Will my AP credit transfer?", "transfer_credit"),
    ("Do I qualify for more financial aid?", "financial"),
    ("If I drop to 9 credits will I lose my F-1 status?", "financial"),
    ("How do I pay my tuition bill?", "financial"),
]

# Normal questions the advisor already answers. None of these may be handed off.
NORMAL = [
    "Can I take CS 450? I've taken CS 351.",
    "What should I take next semester?",
    "Tell me about CS 331",
    "Are there any classes on machine learning?",
    "Any courses on financial math?",
    "What skills do I need to become a data scientist?",
    "Am I on track to graduate?",
    "I've taken CS 115 and MATH 151",
    "How many credits is CS 484?",
    "Which courses can I take instead of waiting for CS 430 to open?",
    "This class is killing me, what's a good next course?",
]


@pytest.mark.parametrize(("message", "kind"), HAND_OFFS)
def test_hand_off_messages_escalate(message: str, kind: str) -> None:
    result = escalate(message)
    assert result is not None, f"not escalated: {message!r}"
    assert result.kind == kind


@pytest.mark.parametrize("message", NORMAL)
def test_normal_questions_do_not_escalate(message: str) -> None:
    assert escalate(message) is None


def test_crisis_reply_has_988_and_no_course_advice() -> None:
    reply = escalate("I'm having suicidal thoughts").reply
    assert "988" in reply
    assert "CS " not in reply


def test_every_reply_says_who_to_contact() -> None:
    for message, _ in HAND_OFFS:
        reply = escalate(message).reply
        assert "advisor" in reply.lower() or "988" in reply or "office" in reply.lower()
