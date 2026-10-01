"""LocalResearchProvider: searches the user's own reference files.

Documents are split into paragraph passages and ranked with BM25. A candidate
from a user file is verified by construction — the file exists and the quoted
passage is in it.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from osamu_dazai.domain.sources import SourceKind, VerificationMethod
from osamu_dazai.providers.research import ResearchProvider, SourceCandidate, Verification

_WORD = re.compile(r"\w+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _WORD.findall(text) if len(t) > 2]


@dataclass
class _Passage:
    doc: str
    index: int
    text: str
    terms: Counter[str]


def read_text_file(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        import docx

        return "\n\n".join(p.text for p in docx.Document(str(path)).paragraphs)
    return path.read_text(encoding="utf-8", errors="replace")


class LocalResearchProvider(ResearchProvider):
    name = "local"

    def __init__(self, documents: dict[str, str] | None = None, *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.docs: dict[str, str] = {}
        self.passages: list[_Passage] = []
        for name, text in (documents or {}).items():
            self.add(name, text)

    def add(self, name: str, text: str) -> None:
        self.docs[name] = text
        for i, para in enumerate(p.strip() for p in re.split(r"\n\s*\n", text)):
            if para:
                self.passages.append(_Passage(name, i, para, Counter(_tokens(para))))

    def add_file(self, path: str | Path) -> None:
        p = Path(path)
        self.add(p.name, read_text_file(p))

    async def search(self, query: str, *, limit: int = 5) -> list[SourceCandidate]:
        q = set(_tokens(query))
        if not q or not self.passages:
            return []
        n = len(self.passages)
        avg = sum(sum(p.terms.values()) for p in self.passages) / n
        df = {t: sum(1 for p in self.passages if t in p.terms) for t in q}
        scored = []
        for p in self.passages:
            length = sum(p.terms.values())
            score = 0.0
            for t in q:
                f = p.terms.get(t, 0)
                if f:
                    idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                    score += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * length / avg))
            if score > 0:
                scored.append((score, p))
        scored.sort(key=lambda s: -s[0])
        return [
            SourceCandidate(kind=SourceKind.USER_FILE, citation=f"{p.doc}, paragraph {p.index + 1}",
                            title=p.doc, url=None, snippet=p.text[:500])
            for _, p in scored[:limit]
        ]

    async def verify(self, c: SourceCandidate) -> Verification:
        text = self.docs.get(c.title)
        if text is None:
            return Verification(verified=False, note=f"no uploaded file named {c.title!r}")
        if c.snippet and c.snippet[:200] not in text:
            return Verification(verified=False, note="quoted passage not found in the file")
        return Verification(verified=True, method=VerificationMethod.USER_FILE, canonical_title=c.title)
