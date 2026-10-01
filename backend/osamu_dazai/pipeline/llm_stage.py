"""The shared generate → check → feedback loop used by every AI stage.

The LLM returns a structured draft; a deterministic ``check`` lists problems;
problems go back to the model verbatim; after ``max_attempts`` the stage fails
loudly with the remaining problems. Drafts that fail checks are never used.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel

from osamu_dazai.providers import ProviderRegistry
from osamu_dazai.providers.llm import LLMRequest, Message

T = TypeVar("T", bound=BaseModel)


class StageFailed(RuntimeError):
    def __init__(self, stage: str, problems: list[str]) -> None:
        shown = "\n- ".join(problems[:15])
        super().__init__(f"{stage}: draft still failing checks after retries:\n- {shown}")
        self.stage = stage
        self.problems = problems


@dataclass
class Checked(Generic[T]):
    value: T
    attempts: int


async def generate_checked(
    registry: ProviderRegistry,
    stage: str,
    *,
    system: str,
    prompt: str,
    schema: type[T],
    check: Callable[[T], list[str]],
    prompt_version: str,
    max_attempts: int = 3,
    max_tokens: int = 32_000,
    failure: type[StageFailed] = StageFailed,
) -> Checked[T]:
    messages = [Message(role="user", content=prompt)]
    problems: list[str] = []
    for attempt in range(1, max_attempts + 1):
        draft = await registry.structured(
            stage,
            LLMRequest(system=system, messages=messages, prompt_version=prompt_version, max_tokens=max_tokens),
            schema,
        )
        problems = check(draft)
        if not problems:
            return Checked(draft, attempt)
        messages = [
            *messages,
            Message(role="assistant", content=draft.model_dump_json()),
            Message(role="user", content="Fix these problems and return the complete corrected result:\n- "
                                         + "\n- ".join(problems)),
        ]
    raise failure(stage, problems)
