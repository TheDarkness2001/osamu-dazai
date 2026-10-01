# Portions of this file are a Python port of ClassBuild's academic
# verification services (src/services/academic/{crossref,semanticScholar,
# unpaywall,enrich}.ts, https://github.com/jtangen/classbuild).
#
# Copyright (c) 2026 Jason Tangen
# Licensed under the MIT License — see licenses/classbuild-MIT.txt.
#
# Changes for Osamu Dazai: translated from TypeScript to async Python (httpx);
# results mapped to Osamu Dazai's SourceCandidate / Verification models; Unpaywall
# made optional (needs a real contact e-mail); a DOI whose Crossref title does
# not match the claimed title is reported as unverified rather than silently
# rewritten.
"""Bibliographic verification against Crossref, Semantic Scholar and Unpaywall."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote

import httpx

CROSSREF = "https://api.crossref.org/works/"
S2 = "https://api.semanticscholar.org/graph/v1"
S2_FIELDS = "title,authors,year,journal,externalIds,openAccessPdf,abstract,url"
UNPAYWALL = "https://api.unpaywall.org/v2/"


def normalize_doi(doi: str) -> str:
    d = doi.strip()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d, flags=re.IGNORECASE)
    d = re.sub(r"^doi:\s*", "", d, flags=re.IGNORECASE)
    return re.sub(r"[.,;]+$", "", d)


def normalize_title(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower()).split())


def titles_match(a: str, b: str) -> bool:
    A, B = normalize_title(a), normalize_title(b)
    if not A or not B:
        return False
    if A == B:
        return True
    if len(A) >= 20 and len(B) >= 20 and (A in B or B in A):
        return True
    ta = {t for t in A.split() if len(t) > 3}
    tb = {t for t in B.split() if len(t) > 3}
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= 0.6


def format_authors(authors: list[dict] | None) -> str:
    if not authors:
        return ""
    names = []
    for a in authors:
        if a.get("literal"):
            names.append(a["literal"])
            continue
        family = a.get("family") or ""
        given = (a.get("given") or "")[:1]
        given = f"{given}." if given else ""
        names.append(f"{family}, {given}" if family and given else family or given)
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} & {names[1]}"
    return f"{names[0]} et al."


@dataclass
class Work:
    title: str
    authors: str = ""
    year: str = ""
    container: str = ""
    doi: str | None = None
    url: str | None = None
    open_access_url: str | None = None
    abstract: str = ""


class AcademicClient:
    def __init__(self, client: httpx.AsyncClient | None = None, *, contact_email: str | None = None) -> None:
        ua = "OsamuDazai/0.1 (educational publishing engine" + (f"; mailto:{contact_email})" if contact_email else ")")
        self.client = client or httpx.AsyncClient(timeout=20.0, headers={"User-Agent": ua})
        self.contact_email = contact_email

    async def _get_json(self, url: str) -> dict | None:
        try:
            r = await self.client.get(url)
        except httpx.HTTPError:
            return None
        if r.status_code != 200:
            return None
        try:
            return r.json()
        except ValueError:
            return None

    async def crossref(self, doi: str) -> Work | None:
        d = normalize_doi(doi)
        if "/" not in d:
            return None
        data = await self._get_json(CROSSREF + quote(d, safe=""))
        m = (data or {}).get("message")
        if not m:
            return None
        parts = (m.get("issued") or {}).get("date-parts") or [[None]]
        return Work(
            title=(m.get("title") or [""])[0],
            authors=format_authors(m.get("author")),
            year=str(parts[0][0]) if parts and parts[0] and parts[0][0] else "",
            container=(m.get("container-title") or [""])[0],
            doi=m.get("DOI") or d,
            url=m.get("URL"),
        )

    @staticmethod
    def _s2_work(p: dict) -> Work:
        return Work(
            title=p.get("title") or "",
            authors=", ".join(a.get("name", "") for a in (p.get("authors") or [])[:3] if a.get("name")),
            year=str(p["year"]) if p.get("year") else "",
            container=((p.get("journal") or {}).get("name") or ""),
            doi=(p.get("externalIds") or {}).get("DOI"),
            url=p.get("url"),
            open_access_url=(p.get("openAccessPdf") or {}).get("url"),
            abstract=p.get("abstract") or "",
        )

    async def search_papers(self, query: str, limit: int = 5) -> list[Work]:
        data = await self._get_json(f"{S2}/paper/search?query={quote(query)}&limit={limit}&fields={S2_FIELDS}")
        return [self._s2_work(p) for p in (data or {}).get("data") or []]

    async def open_access(self, doi: str) -> str | None:
        if not self.contact_email:
            return None  # Unpaywall requires a real contact address
        data = await self._get_json(f"{UNPAYWALL}{quote(normalize_doi(doi), safe='')}?email={self.contact_email}")
        if not data or not data.get("is_oa"):
            return None
        best = data.get("best_oa_location") or {}
        return best.get("url_for_pdf") or best.get("url")

    async def aclose(self) -> None:
        await self.client.aclose()
