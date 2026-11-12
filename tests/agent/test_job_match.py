"""Job matching through the real graph: profile skills in, a cited list of roles out."""

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from agents.career_advisor import CareerAdvisor
from agents.college_advisor import CollegeAdvisor
from orchestrator.graph import build_graph
from orchestrator.state import turn_input
from tests.agent.fakes import FakeLLM, FakeTool, eligibility_result

ANSWER = FakeLLM.route("follow_up", 0.9)
RESUME = {"current_skills": ["Python", "SQL"], "degree_level": "bachelor", "graduation_year": 2027}


def jobs_result() -> dict[str, Any]:
    return {
        "reason": None,
        "occupations": [
            {
                "title": "Software Developers",
                "asked": 3,
                "asked_have": 2,
                "wanted": 5,
                "matched": ["Python", "SQL"],
                "missing": ["Kubernetes", "Git"],
                "needs": None,
            }
        ],
        "unrecognized": [],
        "graduation_year": 2027,
        "graduated": False,
        "citations": [
            {
                "source": "O*NET 31.0 Database, 15-1252.00 Software Developers",
                "url": "https://www.onetonline.org/link/summary/15-1252.00",
            }
        ],
    }


class Chat:
    def __init__(self, *replies: dict[str, Any], profile: dict[str, Any] | None = None) -> None:
        self.match = FakeTool("match_occupations", jobs_result())
        find = FakeTool("find_courses_for_skills", {})
        agents = [
            CollegeAdvisor(FakeTool("check_prerequisites", eligibility_result())),
            CareerAdvisor(find, match=self.match),
        ]
        self.llm = FakeLLM(*replies)
        self.graph = build_graph(
            InMemorySaver(), agents=agents, classify=self.llm.classify, fill=self.llm.fill
        )
        self.config = {"configurable": {"thread_id": "t"}}
        if profile:  # what POST /resume leaves behind
            self.graph.update_state(self.config, {"profile": profile}, as_node="merge")

    def say(self, text: str) -> dict[str, Any]:
        return self.graph.invoke(turn_input(text), self.config)


def test_resume_question_needs_no_model_and_nothing_is_asked() -> None:
    chat = Chat(profile=RESUME)  # no scripted replies: any model call fails the test

    state = chat.say("What jobs fit my resume?")

    assert (state["intent"], state["route"], state["route_source"]) == (
        "job_match",
        "career_advisor",
        "regex",
    )
    assert chat.match.calls == [RESUME]
    assert state["pending_field"] is None
    assert "1. Software Developers - you have 2 of the 3" in state["answer"]
    assert state["citations"][0]["url"].endswith("/15-1252.00")


def test_without_a_resume_it_asks_for_skills_then_matches() -> None:
    chat = Chat(FakeLLM.route("job_match", 0.9), ANSWER)

    asked = chat.say("Which jobs am I a fit for?")
    assert asked["pending_field"] == "current_skills" and "Upload resume" in asked["answer"]

    chat.say("Python and SQL")
    assert chat.match.calls == [
        {"current_skills": ["Python", "SQL"], "degree_level": None, "graduation_year": None}
    ]


def test_use_my_resume_continues_the_open_request_without_the_model() -> None:
    chat = Chat(FakeLLM.route("job_match", 0.9))
    chat.say("Which jobs am I a fit for?")
    # POST /resume while the advisor waits: profile and the open request's slot are filled.
    chat.graph.update_state(
        chat.config,
        {"profile": RESUME, "slots": {"current_skills": RESUME["current_skills"]}},
        as_node="merge",
    )

    state = chat.say("Use my resume")

    assert len(chat.llm.requests) == 1  # only the opening question was routed by the model
    assert state["intent"] == "job_match" and chat.match.calls == [RESUME]


def test_reply_to_tell_me_other_tools_is_read_as_the_skills() -> None:
    """ "Excel and Word" point to no role and the advisor asks for other tools; the reply must
    replace them, not be ignored in favour of the remembered pair."""
    chat = Chat(FakeLLM.route("job_match", 0.9), ANSWER, ANSWER)
    chat.match.result = jobs_result() | {"reason": "generic_only", "occupations": []}
    chat.say("Which jobs am I a fit for?")

    stuck = chat.say("Excel and Word")
    assert "nearly every role" in stuck["answer"] and stuck["pending_field"] == "current_skills"

    chat.match.result = jobs_result()
    done = chat.say("Python and SQL")
    assert chat.match.calls[-1]["current_skills"] == ["Python", "SQL"]
    assert done["pending_field"] is None and "Software Developers" in done["answer"]


def test_the_students_skills_stay_out_of_the_models_next_prompt() -> None:
    chat = Chat(FakeLLM.route("help", 0.9), profile=RESUME)
    chat.say("What jobs fit my resume?")

    chat.say("ok, and what else can you tell me?")

    prompt = chat.llm.requests[-1]["messages"][0]["content"]
    assert "Software Developers" in prompt  # the answer is there to follow up on
    assert "You have:" not in prompt and "Python, SQL" not in prompt
