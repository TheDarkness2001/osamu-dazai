"""Claude (Anthropic) adapter — the CloudProvider for Claude models.

Uses the official ``anthropic`` SDK:

* streaming for every call (long outputs never hit HTTP timeouts),
* explicit ``effort`` (Claude Opus 5.5 defaults to ``medium``; content
  generation here defaults to ``high``),
* no ``temperature`` — current Claude models reject sampling parameters,
* server-side refusal fallbacks (``fallbacks: "default"``) on by default,
* native structured outputs (``output_format=<Pydantic model>``) with a
  prompt-and-validate fallback for schemas structured outputs can't express.

Credentials resolve the SDK's usual way (``ANTHROPIC_API_KEY``, an
``ant auth login`` profile, …). Nothing is hard-coded.
"""

from __future__ import annotations

import logging
import time
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel

from osamu_dazai.providers.llm.base import (
    Effort,
    LLMProvider,
    LLMRefusalError,
    LLMRequest,
    LLMResponse,
    LLMTruncatedError,
    ProviderCaps,
    Usage,
)

T = TypeVar("T", bound=BaseModel)
log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"  # gates fallbacks="default"


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    default_model = DEFAULT_MODEL
    caps = ProviderCaps(max_context_tokens=1_000_000, json_mode=True, tools=True, vision=True)

    def __init__(
        self,
        client: anthropic.AsyncAnthropic | None = None,
        *,
        model: str = DEFAULT_MODEL,
        default_effort: Effort = "high",
        refusal_fallbacks: bool = True,
    ) -> None:
        super().__init__()
        self.client = client or anthropic.AsyncAnthropic()
        self.default_model = model
        self.default_effort = default_effort
        self.refusal_fallbacks = refusal_fallbacks

    # ------------------------------------------------------------------
    def _params(self, req: LLMRequest) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": req.model or self.default_model,
            "max_tokens": req.max_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in req.messages],
            "output_config": {"effort": req.effort or self.default_effort},
        }
        if req.system:
            params["system"] = req.system
        if self.refusal_fallbacks:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        return params

    def _to_response(self, msg: Any, req: LLMRequest, started: float) -> LLMResponse:
        model = getattr(msg, "model", None) or req.model or self.default_model
        if msg.stop_reason == "refusal":
            details = getattr(msg, "stop_details", None)
            raise LLMRefusalError(self.name, model, getattr(details, "category", None),
                                  getattr(details, "explanation", None))
        if msg.stop_reason == "max_tokens":
            raise LLMTruncatedError(f"{model} hit max_tokens={req.max_tokens} (stage {req.stage!r})")
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        return LLMResponse(
            text=text,
            provider=self.name,
            model=model,
            usage=Usage(input_tokens=msg.usage.input_tokens, output_tokens=msg.usage.output_tokens),
            duration_ms=int((time.perf_counter() - started) * 1000),
            stop_reason=msg.stop_reason,
        )

    async def _complete(self, req: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        async with self.client.beta.messages.stream(**self._params(req)) as stream:
            msg = await stream.get_final_message()
        return self._to_response(msg, req, started)

    async def structured(self, req: LLMRequest, schema: type[T], *, max_attempts: int = 3) -> T:
        """Native structured output; prompt-and-validate if the schema isn't supported."""
        started = time.perf_counter()
        try:
            async with self.client.beta.messages.stream(**self._params(req), output_format=schema) as stream:
                msg = await stream.get_final_message()
        except anthropic.BadRequestError as e:
            log.warning("structured output rejected for %s (%s); falling back to prompt+validate",
                        schema.__name__, e.message)
            return await self._structured_by_prompt(req, schema, max_attempts=max_attempts)
        resp = self._to_response(msg, req, started)
        self._record(req, resp)
        parsed = getattr(msg, "parsed_output", None)
        if isinstance(parsed, schema):
            return parsed
        return schema.model_validate_json(resp.text)
