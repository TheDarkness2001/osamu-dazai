"""Terminology & consistency enforcement over a project's KnowledgeBase (spec §13).

* Approved terms are given to every generation prompt and enforced afterwards:
  a forbidden variant in generated text is a blocking problem.
* Terms the model introduces (from chapter glossaries) are recorded as
  *proposed* so later chapters stay consistent until an editor approves them.
* Uzbek apostrophes (o' / o‘ / oʻ, g' …, tutuq belgisi ʼ) are normalised for
  *matching only* — text is never rewritten here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from osamu_dazai.domain.common import Lang
from osamu_dazai.domain.knowledge import ChapterSummary, KnowledgeBase, Term, TermTranslation

_APOSTROPHES = "'’‘`ʻʼ´"
_APOS_RE = re.compile(f"[{_APOSTROPHES}]")


def normalize_for_match(text: str) -> str:
    """Case-fold and unify apostrophe variants (o‘zgaruvchi == o'zgaruvchi == oʻzgaruvchi)."""
    return _APOS_RE.sub("'", text).casefold()


def _term_pattern(term: str) -> re.Pattern[str]:
    t = re.escape(normalize_for_match(term))
    return re.compile(rf"(?<![\w']){t}(?![\w])", re.UNICODE)


def contains_term(text: str, term: str) -> bool:
    return bool(_term_pattern(term).search(normalize_for_match(text)))


@dataclass(frozen=True)
class TermHit:
    key: str
    found: str
    preferred: str


def find_forbidden(text: str, kb: KnowledgeBase, lang: Lang) -> list[TermHit]:
    """Forbidden variants of approved terms used in ``text``."""
    hits = []
    norm = normalize_for_match(text)
    for term in kb.terms:
        for tr in term.translations:
            if tr.lang != lang or not tr.approved:
                continue
            for bad in tr.forbidden_variants:
                if _term_pattern(bad).search(norm):
                    hits.append(TermHit(term.key, bad, tr.preferred))
    return hits


def terminology_prompt(kb: KnowledgeBase, lang: Lang) -> str:
    """Term table for prompts: approved terms are mandatory, proposed ones keep consistency."""
    approved, proposed = [], []
    for term in kb.terms:
        tr = next((t for t in term.translations if t.lang == lang), None)
        if tr is None:
            continue
        line = f"- {term.key} → {tr.preferred}"
        if tr.forbidden_variants:
            line += f" (never: {', '.join(tr.forbidden_variants)})"
        (approved if tr.approved else proposed).append(line)
    out = []
    if approved:
        out.append("Approved terminology (mandatory):\n" + "\n".join(approved))
    if proposed:
        out.append("Terminology already used in earlier chapters (keep consistent):\n" + "\n".join(proposed))
    return "\n\n".join(out)


def glossary_conflicts(entries: list[tuple[str, str]], kb: KnowledgeBase, lang: Lang) -> list[str]:
    """(key, term) pairs that contradict an approved or previously used translation."""
    problems = []
    for key, term in entries:
        known = kb.term(key)
        tr = next((t for t in known.translations if t.lang == lang), None) if known else None
        if tr and normalize_for_match(tr.preferred) != normalize_for_match(term):
            status = "approved" if tr.approved else "already used"
            problems.append(f"glossary term '{key}' is '{term}', but the {status} term is '{tr.preferred}'")
    return problems


def learn_terms(kb: KnowledgeBase, entries: list[tuple[str, str, str]], lang: Lang, chapter: int) -> None:
    """Record (key, term, definition) entries not yet in the KB as proposed terms."""
    for key, term, definition in entries:
        existing = kb.term(key)
        if existing is None:
            kb.terms = [*kb.terms, Term(key=key, definition=definition, first_introduced_chapter=chapter,
                                        translations=[TermTranslation(lang=lang, preferred=term)])]
        elif not any(t.lang == lang for t in existing.translations):
            existing.translations = [*existing.translations, TermTranslation(lang=lang, preferred=term)]


def record_chapter(kb: KnowledgeBase, number: int, summary: str, concepts: list[str], examples: list[str]) -> None:
    kb.chapter_summaries = [s for s in kb.chapter_summaries if s.chapter_number != number] + [
        ChapterSummary(chapter_number=number, summary=summary, concepts_introduced=concepts, examples_used=examples)]


def previous_chapters_prompt(kb: KnowledgeBase, before: int) -> str:
    prev = sorted((s for s in kb.chapter_summaries if s.chapter_number < before), key=lambda s: s.chapter_number)
    if not prev:
        return ""
    lines = ["Earlier chapters (build on them; do not repeat their examples):"]
    for s in prev:
        ex = f" Examples used: {'; '.join(s.examples_used)}." if s.examples_used else ""
        lines.append(f"- Chapter {s.chapter_number}: {s.summary}{ex}")
    return "\n".join(lines)
