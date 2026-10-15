"""Versioned prompt files.

Each prompt is a `<name>.md` file in this directory: a front-matter block carrying its
`prompt_version`, then a `string.Template` body (`$placeholders`, so literal JSON braces need
no escaping). Bump `prompt_version` whenever the body changes; the version goes on the
Langfuse span of every call that uses the prompt, so traces and evals can tell versions apart.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from string import Template

PROMPTS_DIR = Path(__file__).parent


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str  # "<name>@<prompt_version>", e.g. "router_intent@1"
    template: Template

    def render(self, **values: str) -> str:
        return self.template.substitute(values)


@lru_cache
def load_prompt(name: str) -> Prompt:
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    head, sep, body = text.removeprefix("---\n").partition("\n---\n")
    if not text.startswith("---\n") or not sep:
        raise ValueError(f"prompt {name!r} has no front-matter block")
    meta = dict(
        (key.strip(), value.strip())
        for key, _, value in (line.partition(":") for line in head.splitlines())
    )
    if not meta.get("prompt_version"):
        raise ValueError(f"prompt {name!r} has no prompt_version")
    return Prompt(name, f"{name}@{meta['prompt_version']}", Template(body.rstrip("\n")))
