"""Live provider smoke tests — real network calls, real cost. Skipped by default.

    DAZAI_LIVE_TESTS=1 uv run pytest tests/test_live_providers.py
"""

import asyncio
import os

import pytest
from pydantic import BaseModel

from osamu_dazai.domain.sources import SourceKind
from osamu_dazai.providers.llm import LLMRequest, Message
from osamu_dazai.providers.research import SourceCandidate

pytestmark = pytest.mark.skipif(os.environ.get("DAZAI_LIVE_TESTS") != "1", reason="live tests are opt-in")


class Capital(BaseModel):
    country: str
    capital: str


def test_claude_structured_output():
    from osamu_dazai.providers.llm.claude import AnthropicProvider

    p = AnthropicProvider(default_effort="low")
    out = asyncio.run(p.structured(
        LLMRequest(messages=[Message(role="user", content="Capital of Uzbekistan?")], max_tokens=2000), Capital))
    assert "tashkent" in out.capital.lower()


def test_crossref_verification():
    from osamu_dazai.providers.research.web import WebResearchProvider

    c = SourceCandidate(kind=SourceKind.DOI, citation="Karpicke & Blunt 2011", doi="10.1126/science.1199327",
                        title="Retrieval Practice Produces More Learning than Elaborative Studying with Concept Mapping")
    assert asyncio.run(WebResearchProvider().verify(c)).verified
