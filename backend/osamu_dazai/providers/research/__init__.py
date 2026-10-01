"""Research provider interface (spec §6, §44).

Search returns *candidates*; nothing becomes a ``Source`` with ``verified=True``
unless ``verify`` confirmed it against a real record. Never fabricate sources.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

from osamu_dazai.domain.sources import SourceKind, VerificationMethod


class SourceCandidate(BaseModel):
    kind: SourceKind
    citation: str
    title: str = ""
    authors: str = ""
    year: str = ""
    doi: str | None = None
    url: str | None = None
    snippet: str = ""


class Verification(BaseModel):
    verified: bool
    method: VerificationMethod = VerificationMethod.NONE
    canonical_title: str = ""
    note: str = ""


class ResearchProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    async def search(self, query: str, *, limit: int = 5) -> list[SourceCandidate]: ...

    @abstractmethod
    async def verify(self, candidate: SourceCandidate) -> Verification: ...


class MockResearchProvider(ResearchProvider):
    """Returns only the fixtures it was given; verifies only DOIs/URLs marked real."""

    name = "mock"

    def __init__(
        self,
        corpus: list[SourceCandidate] | None = None,
        known_real: set[str] | None = None,
    ) -> None:
        self.corpus = corpus or []
        self.known_real = known_real or set()

    async def search(self, query: str, *, limit: int = 5) -> list[SourceCandidate]:
        words = {w.lower() for w in query.split() if len(w) > 2}
        scored = [
            (sum(w in f"{c.title} {c.snippet}".lower() for w in words), c) for c in self.corpus
        ]
        return [c for score, c in sorted(scored, key=lambda t: -t[0]) if score > 0][:limit]

    async def verify(self, candidate: SourceCandidate) -> Verification:
        key = candidate.doi or candidate.url
        if key and key in self.known_real:
            method = VerificationMethod.CROSSREF if candidate.doi else VerificationMethod.URL_FETCH
            return Verification(verified=True, method=method, canonical_title=candidate.title)
        return Verification(verified=False, note="not found in any reference database")


__all__ = [
    "MockResearchProvider",
    "ResearchProvider",
    "SourceCandidate",
    "Verification",
]
