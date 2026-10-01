import asyncio

import pytest
from pydantic import BaseModel

from osamu_dazai.providers import ProviderConfig, ProviderRegistry, StageRoute
from osamu_dazai.providers.image import ImageRequest, MockImageProvider
from osamu_dazai.providers.llm import LLMRequest, Message, MockProvider, StructuredOutputError, extract_json
from osamu_dazai.providers.research import MockResearchProvider, SourceCandidate
from osamu_dazai.domain.sources import SourceKind


class Outline(BaseModel):
    title: str
    chapters: list[str]


def req(stage: str = "planner", text: str = "hi") -> LLMRequest:
    return LLMRequest(messages=[Message(role="user", content=text)], stage=stage, prompt_version="t.v1")


def test_mock_queue_and_call_log():
    p = MockProvider().queue("planner", "one", "two")
    assert asyncio.run(p.complete(req())).text == "one"
    assert asyncio.run(p.complete(req())).text == "two"
    assert [c.prompt_version for c in p.call_log] == ["t.v1", "t.v1"]


def test_mock_refuses_to_invent():
    with pytest.raises(LookupError):
        asyncio.run(MockProvider().complete(req()))


def test_structured_retries_with_feedback():
    p = MockProvider().queue(
        "outline",
        '{"title": "Python"}',  # missing chapters → invalid
        'Sure!\n```json\n{"title": "Python", "chapters": ["Variables", "Loops"]}\n```',
    )
    out = asyncio.run(p.structured(req("outline"), Outline))
    assert out.chapters == ["Variables", "Loops"]
    retry_msgs = p.requests[1].messages
    assert retry_msgs[-1].role == "user" and "did not validate" in retry_msgs[-1].content
    assert "JSON Schema" in p.requests[0].system


def test_structured_fails_loudly():
    p = MockProvider(default="not json")
    with pytest.raises(StructuredOutputError):
        asyncio.run(p.structured(req("outline"), Outline, max_attempts=2))


def test_extract_json_variants():
    assert extract_json('noise {"a": 1} noise') == '{"a": 1}'
    assert extract_json("```json\n[1,2]\n```") == "[1,2]"


def test_registry_stage_routing():
    reg = ProviderRegistry(
        ProviderConfig(default_llm="mock", stage_routes={"glossary": StageRoute(provider="mock", model="cheap")})
    )
    reg.register_llm(MockProvider())
    assert reg.llm("glossary")[1].model == "cheap"
    assert reg.llm("planner")[1].model is None
    reg.config.stage_routes["x"] = StageRoute(provider="cloud")
    with pytest.raises(KeyError):
        reg.llm("x")


def test_mock_image_is_valid_png_and_deterministic():
    p = MockImageProvider()
    a = asyncio.run(p.generate(ImageRequest(prompt="water cycle", width=64, height=32)))
    b = asyncio.run(p.generate(ImageRequest(prompt="water cycle", width=64, height=32)))
    assert a.data.startswith(b"\x89PNG\r\n\x1a\n") and a.data == b.data
    assert (a.width, a.height) == (64, 32)


def test_research_never_verifies_unknown_sources():
    real = SourceCandidate(kind=SourceKind.DOI, citation="Real 2020", title="Retrieval practice", doi="10.1/real")
    fake = SourceCandidate(kind=SourceKind.DOI, citation="Fake 2021", title="Retrieval magic", doi="10.1/fake")
    r = MockResearchProvider(corpus=[real, fake], known_real={"10.1/real"})
    assert len(asyncio.run(r.search("retrieval"))) == 2
    assert asyncio.run(r.verify(real)).verified
    assert not asyncio.run(r.verify(fake)).verified


def test_mock_registry_builds():
    reg = ProviderRegistry.mock()
    assert reg.llm()[0].name == "mock"
    assert reg.image().name == "mock"
    assert reg.research().name == "mock"
