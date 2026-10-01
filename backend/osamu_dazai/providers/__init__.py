"""Provider registry with per-stage routing, built from configuration.

Stages ask for ``registry.llm("curriculum_architect")``; config decides which
provider/model serves it. Swapping vendors never touches pipeline code.

    [llm.claude]            kind = "anthropic", model = "claude-opus-5-5"
    [llm.ollama]            kind = "local", base_url = "http://localhost:11434/v1", model = "qwen2.5"
    [stage_routes.glossary] provider = "ollama"

See ``config/providers.example.toml``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel, Field

from osamu_dazai.providers.image import ImageProvider, MockImageProvider
from osamu_dazai.providers.llm import Effort, LLMProvider, LLMRequest, LLMResponse, MockProvider
from osamu_dazai.providers.research import MockResearchProvider, ResearchProvider

T = TypeVar("T", bound=BaseModel)


class StageRoute(BaseModel):
    provider: str
    model: str | None = None
    effort: Effort | None = None


class LLMSpec(BaseModel):
    kind: Literal["anthropic", "local", "mock"]
    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None  # env var holding a key (local servers that need one)
    effort: Effort | None = None
    refusal_fallbacks: bool = True


class ImageSpec(BaseModel):
    kind: Literal["cloud", "local", "mock"] = "mock"
    model: str | None = None
    base_url: str | None = None


class ResearchSpec(BaseModel):
    kind: Literal["web", "local", "mock"] = "mock"
    claude_web_search: bool = False  # add Claude's web_search tool to academic search
    contact_email: str | None = None  # enables Unpaywall open-access lookups
    local_paths: list[str] = Field(default_factory=list)


class ProviderConfig(BaseModel):
    llm: dict[str, LLMSpec] = Field(default_factory=lambda: {"mock": LLMSpec(kind="mock")})
    default_llm: str = "mock"
    stage_routes: dict[str, StageRoute] = Field(default_factory=dict)
    image: ImageSpec = Field(default_factory=ImageSpec)
    research: ResearchSpec = Field(default_factory=ResearchSpec)

    @classmethod
    def load(cls, path: str | Path) -> ProviderConfig:
        with open(path, "rb") as f:
            return cls.model_validate(tomllib.load(f))


class ProviderRegistry:
    def __init__(self, config: ProviderConfig | None = None) -> None:
        self.config = config or ProviderConfig()
        self._llms: dict[str, LLMProvider] = {}
        self._image: ImageProvider | None = None
        self._research: ResearchProvider | None = None

    @classmethod
    def mock(cls) -> ProviderRegistry:
        reg = cls()
        reg.register_llm(MockProvider())
        reg.register_image(MockImageProvider())
        reg.register_research(MockResearchProvider())
        return reg

    @classmethod
    def from_config(cls, config: ProviderConfig) -> ProviderRegistry:
        """Instantiate every configured provider. Network SDKs are imported lazily."""
        import os

        reg = cls(config)
        for name, spec in config.llm.items():
            if spec.kind == "mock":
                p: LLMProvider = MockProvider()
            elif spec.kind == "anthropic":
                from osamu_dazai.providers.llm.claude import DEFAULT_MODEL, AnthropicProvider

                p = AnthropicProvider(model=spec.model or DEFAULT_MODEL, default_effort=spec.effort or "high",
                                      refusal_fallbacks=spec.refusal_fallbacks)
            else:
                from osamu_dazai.providers.llm.local import LocalProvider

                key = os.environ.get(spec.api_key_env) if spec.api_key_env else None
                p = LocalProvider(base_url=spec.base_url or "http://localhost:11434/v1",
                                  model=spec.model or "llama3.1", api_key=key)
            p.name = name  # registry name, so routes and logs agree
            reg._llms[name] = p

        img = config.image
        if img.kind == "mock":
            reg._image = MockImageProvider()
        else:
            from osamu_dazai.providers.image.remote import CloudImageProvider, LocalImageProvider

            if img.kind == "cloud":
                kw = {k: v for k, v in (("model", img.model), ("base_url", img.base_url)) if v}
                reg._image = CloudImageProvider(**kw)
            else:
                reg._image = LocalImageProvider(img.base_url or "http://127.0.0.1:7860")

        rs = config.research
        if rs.kind == "mock":
            reg._research = MockResearchProvider()
        elif rs.kind == "local":
            from osamu_dazai.providers.research.local import LocalResearchProvider

            local = LocalResearchProvider()
            for path in rs.local_paths:
                local.add_file(path)
            reg._research = local
        else:
            from osamu_dazai.providers.research.academic import AcademicClient
            from osamu_dazai.providers.research.web import ClaudeWebSearch, WebResearchProvider

            web_search = None
            if rs.claude_web_search:
                import anthropic

                web_search = ClaudeWebSearch(anthropic.AsyncAnthropic())
            reg._research = WebResearchProvider(AcademicClient(contact_email=rs.contact_email), web_search)
        return reg

    # ---- registration (tests / manual wiring) ------------------------------
    def register_llm(self, p: LLMProvider) -> None:
        self._llms[p.name] = p

    def register_image(self, p: ImageProvider) -> None:
        self._image = p

    def register_research(self, p: ResearchProvider) -> None:
        self._research = p

    # ---- lookup -------------------------------------------------------------
    def llm(self, stage: str = "") -> tuple[LLMProvider, StageRoute]:
        """Provider and the effective route (model / effort overrides) for a stage."""
        route = self.config.stage_routes.get(stage) or StageRoute(provider=self.config.default_llm)
        if route.provider not in self._llms:
            raise KeyError(f"LLM provider {route.provider!r} not registered (stage {stage!r})")
        return self._llms[route.provider], route

    def _routed(self, stage: str, req: LLMRequest) -> tuple[LLMProvider, LLMRequest]:
        provider, route = self.llm(stage)
        update: dict = {"stage": stage}
        if route.model and req.model is None:
            update["model"] = route.model
        if route.effort and req.effort is None:
            update["effort"] = route.effort
        return provider, req.model_copy(update=update)

    async def complete(self, stage: str, req: LLMRequest) -> LLMResponse:
        provider, req = self._routed(stage, req)
        return await provider.complete(req)

    async def structured(self, stage: str, req: LLMRequest, schema: type[T], *, max_attempts: int = 3) -> T:
        provider, req = self._routed(stage, req)
        return await provider.structured(req, schema, max_attempts=max_attempts)

    def image(self) -> ImageProvider:
        if self._image is None:
            raise KeyError("no image provider configured")
        return self._image

    def research(self) -> ResearchProvider:
        if self._research is None:
            raise KeyError("no research provider configured")
        return self._research


__all__ = ["ImageSpec", "LLMSpec", "ProviderConfig", "ProviderRegistry", "ResearchSpec", "StageRoute"]
