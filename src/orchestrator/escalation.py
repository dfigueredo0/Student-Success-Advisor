"""Hand-offs: messages the advisor must not answer itself, checked before the router.

Word patterns, not the model: a crisis message must get the same reply every time, and these
run even when the agent is waiting for an answer to its own question. Checked in order; the
first hit wins, so the most urgent and the most specific rules come first.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Escalation:
    kind: str
    reply: str


_CODE = r"[A-Za-z]{2,4}\s?\d{3}\b"

_RULES: list[tuple[str, re.Pattern[str], str]] = [
    (
        "crisis",
        # Err toward a hand-off: people rarely say "suicide", so the reworded forms matter most.
        re.compile(
            r"\bsuicid\w*|\bkill(ing)? myself\b|\b(want|going) to (die|end (it|my life|everything))"
            r"|\bself[- ]?harm|\bhurt(ing)? myself\b|\bcut(ting)? myself\b"
            r"|\b(don'?t|do not) want to (be (here|around) any ?more|be alive|live|exist|wake up)\b"
            r"|\b(think|thinking|thought) (about|of) ending\b|\bending (it all|things|my life)\b"
            r"|\bend it all\b|\bbetter off (dead|without me)\b|\bno reason to live\b"
            r"|\bwish i (was|were) dead\b|\bcan'?t go on\b|\btake my (own )?life\b"
            r"|\b(not|isn'?t|is not) worth living\b",
            re.I,
        ),
        "I'm really sorry you're going through this, and I'm glad you reached out. Please call "
        "or text 988 (Suicide & Crisis Lifeline) right now; it's free and open 24/7. If you're "
        "in immediate danger, call 911. You can also reach the Student Health and Wellness "
        "Center for counseling.",
    ),
    (
        "distress",
        re.compile(
            r"\b(stressed|overwhelmed|anxious|anxiety|depressed|burn(ed|t) out)\b"
            r"|\bfailing (a |my |\w+ )?(class|course)s?\b|\bwho can i talk to\b"
            r"|\b(feel|feeling|so|completely) hopeless\b|\bmy mental health\b|\bcan'?t cope\b"
            r"|\bpanic attacks?\b|\b(i'?m|i am) not (okay|ok)\b",
            re.I,
        ),
        "That sounds really hard, and you don't have to sort it out alone. Your academic "
        "advisor can help you look at your options for this class, and the Student Health and "
        "Wellness Center offers free counseling. If it ever feels like too much, you can call "
        "or text 988 any time.",
    ),
    (
        "probation",
        re.compile(
            r"\bacademic(ally)? (probation|dismiss\w*|suspen\w*)|\bon probation\b"
            r"|\bdismissed\b|\breinstate\w*",
            re.I,
        ),
        "Academic standing is something your academic advisor needs to go through with you, "
        "since it depends on your full record and the university's policies. Please contact "
        "your advisor or the Dean of Students office soon; they can explain what it means for "
        "you and what to do next.",
    ),
    (
        "appeal",
        re.compile(
            r"\bappeal\w*|\bcheat(ing|ed)?\b|\bplagiari\w+|\bacademic (integrity|dishonesty)",
            re.I,
        ),
        "I can't advise on appeals or academic integrity cases. Start with your instructor, "
        "then your academic advisor or the Dean of Students office, who can walk you through "
        "the official process and deadlines.",
    ),
    (
        "financial",
        re.compile(
            r"\bfinancial aid\b|\bfafsa\b|\bscholarships?\b|\btuition\b|\bbill\b|\bbursar\b"
            r"|\bloans?\b|\bvisa\b|\bf-?1\b|\bimmigration\b|\blegal\b|\blawyer\b",
            re.I,
        ),
        "Questions about financial aid, tuition, visas or legal matters need an official "
        "answer, so I won't guess. Please contact the Office of Financial Aid (aid and "
        "scholarships), the Student Accounting office (bills and tuition), or the International "
        "Center (visa and enrollment status) before you change your schedule.",
    ),
    (
        "withdrawal",
        # Leaving the university or every class. Dropping one named course ("Should I withdraw
        # from CS 351?") goes to the router's consequence check instead, which ends with the
        # same advice to see an advisor (UC-09).
        re.compile(
            rf"(?s)^(?!.*{_CODE}).*?(\bwithdraw\w*|\bdrop out\b|\bleave of absence\b"
            r"|\btake (a|the) (semester|term) off\b)",
            re.I,
        ),
        "Withdrawing can affect your financial aid, a student visa, and how long your degree "
        "takes, so please talk to your academic advisor before you do it. If you get aid or "
        "are on a visa, check with the Office of Financial Aid or the International Center too.",
    ),
    (
        "major_change",
        re.compile(r"\b(switch|change|changing|switching)\b.{0,20}\bmajors?\b", re.I),
        "Changing majors is a decision to make with your academic advisor; they can check how "
        "your completed courses count toward the new program. I can look up courses in either "
        "program if that helps.",
    ),
    (
        "transfer_credit",
        re.compile(
            r"\btransfer(red)? credits?\b|\bcredits? transfer\b|\bap (credit|exam|score)s?\b"
            r"|\bcommunity college\b",
            re.I,
        ),
        "Only the Registrar's office and the department can decide how transfer or AP credit "
        "counts. Your academic advisor can help you request an evaluation.",
    ),
    (
        "exception",
        re.compile(
            rf"\boverride\b|\boverload\b|\bsubstitut\w*|\binstead of {_CODE}|\bwaive\w*"
            rf"|\bskip {_CODE}|\b(19|2\d) credits\b|\bspecial (approval|permission)\b"
            r"|\b(advisor|dean|professor|registrar) (said|told me|approved)\b",
            re.I,
        ),
        "I can only give advice from the catalog, so I can't approve or confirm exceptions "
        "like overrides, substitutions or extra credits. Only your department or academic "
        "advisor can grant one, and it should be in writing. Ask me about a course's "
        "prerequisites if you'd like to see the catalog rule.",
    ),
]


def escalate(text: str) -> Escalation | None:
    """The hand-off for this message, or None to let the router handle it."""
    text = text.replace("\u2019", "'")  # phones type a curly apostrophe (U+2019)
    for kind, pattern, reply in _RULES:
        if pattern.search(text):
            return Escalation(kind, reply)
    return None
