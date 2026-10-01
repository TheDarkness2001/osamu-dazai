"""LLM provider interface.

Concrete providers implement ``complete``. ``structured`` is shared: it asks for
JSON matching a Pydantic schema, validates, and retries with the validation
error fed back. It never "best-effort parses" — after the retries it fails.
"""

from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from typing import Literal, TypeVar

from pydantic import BaseModel, Field, ValidationError

from osamu_dazai.domain.documents import LLMCallRecord

T = TypeVar("T", bound=BaseModel)


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


Effort = Literal["low", "medium", "high", "xhigh", "max"]


class LLMRequest(BaseModel):
    messages: list[Message]
    system: str = ""
    model: str | None = None  # None → provider default
    # Sampling temperature. Providers whose models reject it (current Claude
    # models) ignore it; local models use it when set.
    temperature: float | None = None
    max_tokens: int = 16_000
    # Reasoning depth hint. Providers without an equivalent ignore it.
    effort: Effort | None = None
    json_mode: bool = False  # ask the provider for a bare JSON reply when it can
    stage: str = ""  # pipeline stage name, for routing/logging/mocks
    prompt_version: str | None = None


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class LLMResponse(BaseModel):
    text: str
    provider: str
    model: str  # the model that actually produced the text (may be a fallback)
    usage: Usage = Field(default_factory=Usage)
    duration_ms: int = 0
    stop_reason: str | None = None


class LLMError(RuntimeError):
    """Base for provider-neutral generation failures."""


class LLMRefusalError(LLMError):
    """The model declined the request (after any provider-side fallback)."""

    def __init__(self, provider: str, model: str, category: str | None, explanation: str | None) -> None:
        super().__init__(f"{provider}/{model} declined the request"
                         + (f" ({category})" if category else "") + (f": {explanation}" if explanation else ""))
        self.category = category
        self.explanation = explanation


class LLMTruncatedError(LLMError):
    """Output hit max_tokens — partial output is never treated as a result."""


class ProviderCaps(BaseModel):
    max_context_tokens: int = 32_000
    json_mode: bool = False
    tools: bool = False
    vision: bool = False


class StructuredOutputError(RuntimeError):
    def __init__(self, schema: str, attempts: int, last_error: str) -> None:
        super().__init__(f"{schema}: no valid output after {attempts} attempts — {last_error}")
        self.last_error = last_error


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> str:
    """Pull a JSON document out of a reply (handles ```json fences and chatter)."""
    m = _FENCE.search(text)
    if m:
        return m.group(1).strip()
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        return text.strip()
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]"))
    return text[start : end + 1] if end > start else text[start:]


class LLMProvider(ABC):
    name: str = "abstract"
    default_model: str = ""
    caps: ProviderCaps = ProviderCaps()

    def __init__(self) -> None:
        self.call_log: list[LLMCallRecord] = []

    @abstractmethod
    async def _complete(self, req: LLMRequest) -> LLMResponse: ...

    def _record(self, req: LLMRequest, resp: LLMResponse) -> None:
        self.call_log.append(
            LLMCallRecord(
                provider=resp.provider,
                model=resp.model,
                prompt_version=req.prompt_version,
                input_tokens=resp.usage.input_tokens,
                output_tokens=resp.usage.output_tokens,
                duration_ms=resp.duration_ms,
            )
        )

    async def complete(self, req: LLMRequest) -> LLMResponse:
        t0 = time.perf_counter()
        resp = await self._complete(req)
        resp.duration_ms = resp.duration_ms or int((time.perf_counter() - t0) * 1000)
        self._record(req, resp)
        return resp

    async def structured(self, req: LLMRequest, schema: type[T], *, max_attempts: int = 3) -> T:
        """Prompt-and-validate JSON. Providers with native structured output override this."""
        return await self._structured_by_prompt(req, schema, max_attempts=max_attempts)

    async def _structured_by_prompt(self, req: LLMRequest, schema: type[T], *, max_attempts: int) -> T:
        req = req.model_copy(update={"json_mode": True})
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        system = (
            f"{req.system}\n\nRespond with a single JSON document that validates against this "
            f"JSON Schema. No prose outside the JSON.\n{schema_json}"
        ).strip()
        messages = list(req.messages)
        last_error = ""
        for _ in range(max_attempts):
            resp = await self.complete(req.model_copy(update={"system": system, "messages": messages}))
            try:
                return schema.model_validate_json(extract_json(resp.text))
            except ValidationError as e:
                last_error = str(e)
                messages = [
                    *messages,
                    Message(role="assistant", content=resp.text),
                    Message(
                        role="user",
                        content=f"That JSON did not validate:\n{last_error}\nReturn corrected JSON only.",
                    ),
                ]
        raise StructuredOutputError(schema.__name__, max_attempts, last_error)
