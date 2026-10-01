"""Deterministic LLM provider for tests and offline development."""

from __future__ import annotations

import hashlib
from collections import deque
from collections.abc import Callable

from osamu_dazai.providers.llm.base import LLMProvider, LLMRequest, LLMResponse, ProviderCaps, Usage

Responder = Callable[[LLMRequest], str]


class MockProvider(LLMProvider):
    """Answers from registered fixtures.

    Lookup order: a queued reply for the request's stage → a responder function
    for the stage → a fixture keyed by prompt hash → ``default`` → error.
    Unknown requests raise instead of inventing content.
    """

    name = "mock"
    default_model = "mock-1"
    caps = ProviderCaps(max_context_tokens=1_000_000, json_mode=True)

    def __init__(self, default: str | None = None) -> None:
        super().__init__()
        self._queues: dict[str, deque[str]] = {}
        self._responders: dict[str, Responder] = {}
        self._by_hash: dict[str, str] = {}
        self._default = default
        self.requests: list[LLMRequest] = []

    # ---- fixture registration ------------------------------------------
    def queue(self, stage: str, *replies: str) -> MockProvider:
        self._queues.setdefault(stage, deque()).extend(replies)
        return self

    def on(self, stage: str, responder: Responder) -> MockProvider:
        self._responders[stage] = responder
        return self

    def fixture(self, req: LLMRequest, reply: str) -> MockProvider:
        self._by_hash[self.request_hash(req)] = reply
        return self

    @staticmethod
    def request_hash(req: LLMRequest) -> str:
        key = req.system + "\x00" + "\x00".join(f"{m.role}:{m.content}" for m in req.messages)
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

    # ---- provider --------------------------------------------------------
    async def _complete(self, req: LLMRequest) -> LLMResponse:
        self.requests.append(req)
        text = self._lookup(req)
        words_in = sum(len(m.content.split()) for m in req.messages) + len(req.system.split())
        return LLMResponse(
            text=text,
            provider=self.name,
            model=req.model or self.default_model,
            usage=Usage(input_tokens=words_in, output_tokens=len(text.split())),
        )

    def _lookup(self, req: LLMRequest) -> str:
        q = self._queues.get(req.stage)
        if q:
            return q.popleft()
        if req.stage in self._responders:
            return self._responders[req.stage](req)
        h = self.request_hash(req)
        if h in self._by_hash:
            return self._by_hash[h]
        if self._default is not None:
            return self._default
        raise LookupError(f"MockProvider has no fixture for stage={req.stage!r} hash={h}")
