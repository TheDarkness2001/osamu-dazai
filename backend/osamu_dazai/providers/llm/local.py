"""LocalProvider — locally hosted open models (not Claude).

Talks to any server exposing the widely used ``/v1/chat/completions`` HTTP
interface: Ollama (``http://localhost:11434/v1``), llama.cpp server, LM Studio,
vLLM. Structured output uses the shared prompt-and-validate loop, with the
server's JSON mode switched on when ``json_mode`` is requested.
"""

from __future__ import annotations

import time

import httpx

from osamu_dazai.providers.llm.base import (
    LLMError,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMTruncatedError,
    ProviderCaps,
    Usage,
)


class LocalProvider(LLMProvider):
    name = "local"
    caps = ProviderCaps(max_context_tokens=32_000, json_mode=True)

    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        model: str = "llama3.1",
        *,
        api_key: str | None = None,
        timeout_s: float = 600.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.default_model = model
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.client = client or httpx.AsyncClient(timeout=timeout_s, headers=headers)

    async def _complete(self, req: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        messages = [{"role": "system", "content": req.system}] if req.system else []
        messages += [{"role": m.role, "content": m.content} for m in req.messages]
        body: dict = {
            "model": req.model or self.default_model,
            "messages": messages,
            "max_tokens": req.max_tokens,
            "stream": False,
        }
        if req.temperature is not None:
            body["temperature"] = req.temperature
        if req.json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            r = await self.client.post(f"{self.base_url}/chat/completions", json=body)
        except httpx.HTTPError as e:
            raise LLMError(f"local model server unreachable at {self.base_url}: {e}") from e
        if r.status_code >= 400:
            raise LLMError(f"local model server error {r.status_code}: {r.text[:300]}")
        data = r.json()
        choice = data["choices"][0]
        if choice.get("finish_reason") == "length":
            raise LLMTruncatedError(f"{body['model']} hit max_tokens={req.max_tokens} (stage {req.stage!r})")
        usage = data.get("usage") or {}
        return LLMResponse(
            text=choice["message"].get("content") or "",
            provider=self.name,
            model=data.get("model", body["model"]),
            usage=Usage(input_tokens=usage.get("prompt_tokens", 0), output_tokens=usage.get("completion_tokens", 0)),
            duration_ms=int((time.perf_counter() - started) * 1000),
            stop_reason=choice.get("finish_reason"),
        )

    async def aclose(self) -> None:
        await self.client.aclose()
