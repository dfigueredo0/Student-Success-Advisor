import re
from collections.abc import Callable
from typing import Any

from agents.base import Agent, Field, Scaffold

class CareerAdvisor(Agent):
    name = "career_advisor"

    def __init__(self, check: Callable[..., dict[str, Any]] = None) -> None:
        self.scaffolds = {
            "career_advice": Scaffold(
                intent="career_advice",
                fields=(
                    Field(
                        "career_goal",
                        "What is your career goal? (e.g. software engineer, data scientist)",
                        lambda text, asked: text.strip() or None,
                    ),
                    Field(
                        "current_skills",
                        "What are your current skills? List them, or say 'none'.",
                        lambda text, asked: text.strip() or None,
                    ),
                    Field(
                        "desired_skills",
                        "What skills do you want to develop for this career goal?",
                        lambda text, asked: text.strip() or None,
                    ),
                ),
            )
        }