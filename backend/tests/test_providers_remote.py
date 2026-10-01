"""Network providers, tested offline (fake Claude client, httpx MockTransport)."""

import asyncio
import base64
import json
from pathlib import Path
from types import SimpleNamespace as NS

import anthropic
import httpx
import httpx2
import pytest
from pydantic import BaseModel

from osamu_dazai.domain.sources import SourceKind, VerificationMethod
from osamu_dazai.providers import ProviderConfig, ProviderRegistry
from osamu_dazai.providers.image import ImageRequest, solid_png
from osamu_dazai.providers.image.remote import CloudImageProvider, LocalImageProvider, closest_size
from osamu_dazai.providers.llm import LLMRefusalError, LLMRequest, LLMTruncatedError, Message
from osamu_dazai.providers.llm.claude import FALLBACK_BETA, AnthropicProvider
from osamu_dazai.providers.llm.local import LocalProvider
from osamu_dazai.providers.research import SourceCandidate
from osamu_dazai.providers.research.academic import AcademicClient, normalize_doi, titles_match
from osamu_dazai.providers.research.local import LocalResearchProvider
from osamu_dazai.providers.research.web import ClaudeWebSearch, WebResearchProvider

run = asyncio.run


def req(**kw) -> LLMRequest:
    return LLMRequest(messages=[Message(role="user", content="Write an outline")], **kw)


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------
def message(text="ok", stop="end_turn", model="claude-opus-5-5", parsed=None, details=None):
    return NS(content=[NS(type="text", text=text)], stop_reason=stop, model=model,
              usage=NS(input_tokens=10, output_tokens=5), parsed_output=parsed, stop_details=details)


class FakeStream:
    def __init__(self, result):
        self.result = result

    async def __aenter__(self):
        if isinstance(self.result, Exception):
            raise self.result
        return self

    async def __aexit__(self, *a):
        return False

    async def get_final_message(self):
        return self.result


class FakeClaude:
    def __init__(self, *results):
        self.results = list(results)
        self.calls: list[dict] = []
        self.beta = NS(messages=NS(stream=self._stream, create=self._create))

    def _stream(self, **kw):
        self.calls.append(kw)
        return FakeStream(self.results.pop(0))

    async def _create(self, **kw):
        self.calls.append(kw)
        return self.results.pop(0)


def test_claude_request_shape():
    fake = FakeClaude(message("Hello"))
    p = AnthropicProvider(fake)
    resp = run(p.complete(req(system="You write textbooks.", temperature=0.9, stage="writer")))
    call = fake.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert "temperature" not in call  # rejected by current Claude models
    assert call["output_config"] == {"effort": "high"}
    assert call["betas"] == [FALLBACK_BETA] and call["fallbacks"] == "default"
    assert call["system"] == "You write textbooks."
    assert resp.text == "Hello" and resp.usage.output_tokens == 5
    assert p.call_log[0].provider == "anthropic"


def test_claude_effort_and_model_override():
    fake = FakeClaude(message())
    run(AnthropicProvider(fake, refusal_fallbacks=False).complete(req(effort="low", model="claude-sonnet-5-5")))
    call = fake.calls[0]
    assert call["output_config"] == {"effort": "low"} and call["model"] == "claude-sonnet-5-5"
    assert "fallbacks" not in call and "betas" not in call


def test_claude_refusal_raises_typed_error():
    fake = FakeClaude(message("", stop="refusal", details=NS(category="cyber", explanation="declined")))
    with pytest.raises(LLMRefusalError) as e:
        run(AnthropicProvider(fake).complete(req()))
    assert e.value.category == "cyber"


def test_claude_truncation_is_an_error():
    with pytest.raises(LLMTruncatedError):
        run(AnthropicProvider(FakeClaude(message("partial", stop="max_tokens"))).complete(req()))


def test_claude_reports_fallback_model():
    resp = run(AnthropicProvider(FakeClaude(message(model="claude-opus-4-8"))).complete(req()))
    assert resp.model == "claude-opus-4-8"


class Outline(BaseModel):
    title: str
    chapters: list[str]


def test_claude_native_structured_output():
    parsed = Outline(title="Python", chapters=["Variables"])
    fake = FakeClaude(message(json.dumps(parsed.model_dump()), parsed=parsed))
    out = run(AnthropicProvider(fake).structured(req(stage="outline"), Outline))
    assert out == parsed
    assert fake.calls[0]["output_format"] is Outline


def test_claude_structured_falls_back_when_schema_rejected():
    bad = anthropic.BadRequestError(
        "schema not supported",
        response=httpx2.Response(400, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")),
        body=None,
    )
    fake = FakeClaude(bad, message('{"title": "Python", "chapters": ["Loops"]}'))
    out = run(AnthropicProvider(fake).structured(req(), Outline))
    assert out.chapters == ["Loops"]
    assert "output_format" not in fake.calls[1] and "JSON Schema" in fake.calls[1]["system"]


# ---------------------------------------------------------------------------
# Local LLM (Ollama-style /v1/chat/completions)
# ---------------------------------------------------------------------------
def test_local_provider_request_and_response():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"model": "qwen2.5", "choices": [
            {"message": {"content": '{"title": "T", "chapters": []}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3}})

    p = LocalProvider(model="qwen2.5", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    out = run(p.structured(req(system="sys", temperature=0.2), Outline))
    assert out.title == "T"
    assert seen["url"] == "http://localhost:11434/v1/chat/completions"
    assert seen["messages"][0]["role"] == "system" and seen["temperature"] == 0.2
    assert seen["response_format"] == {"type": "json_object"}
    assert p.call_log[0].input_tokens == 7


def test_local_provider_errors():
    def length(_r):
        return httpx.Response(200, json={"choices": [{"message": {"content": "…"}, "finish_reason": "length"}]})

    p = LocalProvider(client=httpx.AsyncClient(transport=httpx.MockTransport(length)))
    with pytest.raises(LLMTruncatedError):
        run(p.complete(req()))


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------
PNG = solid_png(4, 4, (1, 2, 3))


def test_cloud_image_provider():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(PNG).decode()}]})

    p = CloudImageProvider(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    res = run(p.generate(ImageRequest(prompt="water cycle diagram", width=1600, height=900, style="flat")))
    assert res.data == PNG and (res.width, res.height) == (1536, 1024)
    assert seen["size"] == "1536x1024" and "Style: flat" in seen["prompt"]
    assert closest_size(800, 1200) == (1024, 1536)


def test_local_image_provider():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        seen["path"] = request.url.path
        return httpx.Response(200, json={"images": [base64.b64encode(PNG).decode()]})

    p = LocalImageProvider(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    res = run(p.generate(ImageRequest(prompt="a tulip", width=1001, height=750, negative_prompt="text")))
    assert res.data == PNG and seen["path"] == "/sdapi/v1/txt2img"
    assert (seen["width"], seen["height"]) == (1000, 744) and seen["negative_prompt"] == "text"


# ---------------------------------------------------------------------------
# Research
# ---------------------------------------------------------------------------
CROSSREF_REAL = {"message": {"DOI": "10.1037/a0021017", "title": ["Retrieval practice produces more learning"],
                             "author": [{"given": "Jeffrey", "family": "Karpicke"}, {"given": "J", "family": "Blunt"}],
                             "issued": {"date-parts": [[2011]]}, "container-title": ["Science"]}}
S2_HIT = {"data": [{"title": "Sleep and memory consolidation", "authors": [{"name": "A. Researcher"}],
                    "year": 2019, "externalIds": {"DOI": "10.1/sleep"}, "url": "https://s2/sleep"}]}


def academic_transport(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "api.crossref.org/works/10.1037" in url:
        return httpx.Response(200, json=CROSSREF_REAL)
    if "api.crossref.org" in url:
        return httpx.Response(404)
    if "semanticscholar" in url:
        return httpx.Response(200, json=S2_HIT if "sleep" in url.lower() else {"data": []})
    if url.startswith("https://example.edu/tulips"):
        return httpx.Response(200, text="<html><title>History of the Tulip</title><p>The tulip trade…</p></html>")
    return httpx.Response(404)


def web_provider() -> WebResearchProvider:
    t = httpx.MockTransport(academic_transport)
    return WebResearchProvider(AcademicClient(httpx.AsyncClient(transport=t)), http=httpx.AsyncClient(transport=t))


def test_doi_helpers():
    assert normalize_doi("https://doi.org/10.1037/a0021017.") == "10.1037/a0021017"
    assert titles_match("Retrieval Practice Produces More Learning", "Retrieval practice produces more learning")
    assert not titles_match("Bees in cities", "Retrieval practice produces more learning")


def test_verify_real_doi():
    c = SourceCandidate(kind=SourceKind.DOI, citation="Karpicke 2011", doi="10.1037/a0021017",
                        title="Retrieval practice produces more learning")
    v = run(web_provider().verify(c))
    assert v.verified and v.method is VerificationMethod.CROSSREF


def test_fabricated_doi_detected():
    c = SourceCandidate(kind=SourceKind.DOI, citation="Fake 2020", doi="10.1037/a0021017",
                        title="Urban beekeeping doubles pollination")
    v = run(web_provider().verify(c))
    assert not v.verified and "different work" in v.note


def test_unknown_doi_and_title_unverified():
    c = SourceCandidate(kind=SourceKind.DOI, citation="X", doi="10.9999/nope", title="An invented study of nothing")
    assert not run(web_provider().verify(c)).verified


def test_title_verified_via_semantic_scholar():
    c = SourceCandidate(kind=SourceKind.BOOK, citation="Researcher 2019", title="Sleep and memory consolidation")
    v = run(web_provider().verify(c))
    assert v.verified and v.method is VerificationMethod.SEMANTIC_SCHOLAR


def test_url_verification_checks_claimed_title():
    p = web_provider()
    ok = run(p.verify(SourceCandidate(kind=SourceKind.URL, citation="x", url="https://example.edu/tulips",
                                      title="History of the Tulip")))
    assert ok.verified and ok.method is VerificationMethod.URL_FETCH
    wrong = run(p.verify(SourceCandidate(kind=SourceKind.URL, citation="x", url="https://example.edu/tulips",
                                         title="Quantum chromodynamics lecture notes")))
    assert not wrong.verified
    dead = run(p.verify(SourceCandidate(kind=SourceKind.URL, citation="x", url="https://example.edu/gone")))
    assert not dead.verified


def test_academic_search_candidates():
    out = run(web_provider().search("sleep memory"))
    assert out[0].doi == "10.1/sleep" and out[0].kind is SourceKind.DOI


def test_claude_web_search_parses_results_and_errors():
    result = NS(type="web_search_tool_result", content=[
        NS(type="web_search_result", url="https://a.org/x", title="A"),
        NS(type="web_search_result", url="https://a.org/x", title="A dup"),
        NS(type="web_search_result", url="https://b.org/y", title="B")])
    error = NS(type="web_search_tool_result", content=NS(type="web_search_tool_result_error",
                                                         error_code="max_uses_exceeded"))
    fake = FakeClaude(NS(content=[result, error, NS(type="text", text="summary")]))
    out = run(ClaudeWebSearch(fake).search("tulip history", 5))
    assert [c.url for c in out] == ["https://a.org/x", "https://b.org/y"]
    call = fake.calls[0]
    assert call["tools"][0]["type"] == "web_search_20260209" and call["output_config"] == {"effort": "low"}


def test_local_research_provider():
    p = LocalResearchProvider({
        "syllabus.md": "Unit 1 covers variables and data types.\n\nUnit 2 covers loops and conditions.",
        "notes.txt": "Loops repeat code. A for loop iterates over a sequence.",
    })
    hits = run(p.search("for loops"))
    assert hits[0].title == "notes.txt"
    assert run(p.verify(hits[0])).verified
    fake = SourceCandidate(kind=SourceKind.USER_FILE, citation="x", title="missing.pdf")
    assert not run(p.verify(fake)).verified


# ---------------------------------------------------------------------------
# Config-driven registry
# ---------------------------------------------------------------------------
def test_example_config_builds_registry(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    cfg = ProviderConfig.load(Path(__file__).parents[1] / "config" / "providers.example.toml")
    reg = ProviderRegistry.from_config(cfg)
    claude, route = reg.llm("writer")
    assert isinstance(claude, AnthropicProvider) and claude.name == "claude" and route.provider == "claude"
    local, route = reg.llm("terminology_check")
    assert isinstance(local, LocalProvider) and local.name == "ollama"
    assert reg.llm("glossary")[1].effort == "low"
    assert isinstance(reg.research(), WebResearchProvider)


def test_registry_applies_stage_route():
    fake = FakeClaude(message("x"), message("y"))
    cfg = ProviderConfig.model_validate({"default_llm": "claude", "llm": {"claude": {"kind": "anthropic"}},
                                         "stage_routes": {"glossary": {"provider": "claude", "effort": "low"}}})
    reg = ProviderRegistry(cfg)
    p = AnthropicProvider(fake)
    p.name = "claude"
    reg.register_llm(p)
    run(reg.complete("glossary", req()))
    run(reg.complete("writer", req()))
    assert fake.calls[0]["output_config"] == {"effort": "low"}
    assert fake.calls[1]["output_config"] == {"effort": "high"}
