"""WebResearchProvider: academic search + optional Claude web search + verification.

Search returns candidates only. ``verify`` decides whether a candidate is real:

* DOI → Crossref; the resolved title must match the claimed title, otherwise
  the DOI is treated as fabricated and the source stays unverified.
* title only → Semantic Scholar; a title match counts as verified.
* URL → fetched; it must resolve, and a claimed title must appear on the page.

Nothing is ever marked verified because a model said so.
"""

from __future__ import annotations

import html
import logging
import re
from typing import Any

import httpx

from osamu_dazai.domain.sources import SourceKind, VerificationMethod
from osamu_dazai.providers.research import ResearchProvider, SourceCandidate, Verification
from osamu_dazai.providers.research.academic import AcademicClient, normalize_title, titles_match

log = logging.getLogger(__name__)

WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search"}


class ClaudeWebSearch:
    """Web search through Claude's server-side web_search tool."""

    def __init__(self, client: Any, *, model: str = "claude-opus-5-5", max_uses: int = 3) -> None:
        self.client = client  # anthropic.AsyncAnthropic
        self.model = model
        self.max_uses = max_uses

    async def search(self, query: str, limit: int) -> list[SourceCandidate]:
        from osamu_dazai.providers.llm.claude import FALLBACK_BETA

        msg = await self.client.beta.messages.create(
            model=self.model,
            max_tokens=4000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            output_config={"effort": "low"},
            tools=[{**WEB_SEARCH_TOOL, "max_uses": self.max_uses}],
            messages=[{"role": "user", "content":
                       f"Search the web for reliable educational sources about: {query}\n"
                       "Prefer primary sources, academic and official publications."}],
        )
        out: list[SourceCandidate] = []
        for block in msg.content:
            if getattr(block, "type", None) != "web_search_tool_result":
                continue
            content = block.content
            if not isinstance(content, list):  # an error object, e.g. max_uses_exceeded
                log.warning("web search error: %s", getattr(content, "error_code", content))
                continue
            for r in content:
                if getattr(r, "type", None) == "web_search_result":
                    out.append(SourceCandidate(kind=SourceKind.URL, citation=r.title or r.url,
                                               title=r.title or "", url=r.url))
        seen: set[str] = set()
        unique = [c for c in out if not (c.url in seen or seen.add(c.url))]
        return unique[:limit]


_TITLE_TAG = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TAGS = re.compile(r"<[^>]+>")


class WebResearchProvider(ResearchProvider):
    name = "web"

    def __init__(
        self,
        academic: AcademicClient | None = None,
        web_search: ClaudeWebSearch | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.academic = academic or AcademicClient()
        self.web_search = web_search
        self.http = http or httpx.AsyncClient(timeout=20.0, follow_redirects=True,
                                              headers={"User-Agent": "OsamuDazai/0.1"})

    async def search(self, query: str, *, limit: int = 5) -> list[SourceCandidate]:
        papers = await self.academic.search_papers(query, limit=limit)
        out = [
            SourceCandidate(
                kind=SourceKind.DOI if w.doi else SourceKind.URL,
                citation=f"{w.authors} ({w.year}). {w.title}. {w.container}".strip(". "),
                title=w.title, authors=w.authors, year=w.year, doi=w.doi,
                url=w.open_access_url or w.url, snippet=w.abstract[:500],
            )
            for w in papers
        ]
        if self.web_search is not None and len(out) < limit:
            out += await self.web_search.search(query, limit - len(out))
        return out[:limit]

    async def verify(self, c: SourceCandidate) -> Verification:
        if c.doi:
            work = await self.academic.crossref(c.doi)
            if work and work.title:
                if c.title and not titles_match(c.title, work.title):
                    return Verification(verified=False, note=f"DOI {c.doi} resolves to a different work: "
                                                             f"'{work.title}' — likely fabricated")
                return Verification(verified=True, method=VerificationMethod.CROSSREF, canonical_title=work.title)
        if c.title and len(c.title) > 8:
            for w in await self.academic.search_papers(c.title, limit=3):
                if w.title and titles_match(c.title, w.title):
                    return Verification(verified=True, method=VerificationMethod.SEMANTIC_SCHOLAR,
                                        canonical_title=w.title)
        if c.url:
            return await self._verify_url(c)
        return Verification(verified=False, note="not found in Crossref or Semantic Scholar")

    async def _verify_url(self, c: SourceCandidate) -> Verification:
        try:
            r = await self.http.get(c.url)  # type: ignore[arg-type]
        except httpx.HTTPError as e:
            return Verification(verified=False, note=f"URL did not resolve: {e.__class__.__name__}")
        if r.status_code >= 400:
            return Verification(verified=False, note=f"URL returned HTTP {r.status_code}")
        page = r.text
        m = _TITLE_TAG.search(page)
        page_title = html.unescape(m.group(1)).strip() if m else ""
        if c.title:
            body = normalize_title(html.unescape(_TAGS.sub(" ", page)))
            if not (titles_match(c.title, page_title) or normalize_title(c.title) in body):
                return Verification(verified=False, canonical_title=page_title,
                                    note="page exists but does not contain the claimed title")
        return Verification(verified=True, method=VerificationMethod.URL_FETCH, canonical_title=page_title,
                            note="page exists; content claims still need human review")
