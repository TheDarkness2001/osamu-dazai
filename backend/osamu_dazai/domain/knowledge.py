"""Project knowledge base for consistency (spec §13).

Example: the user approves ``variable`` → uz "o'zgaruvchi"; every later chapter
must use it, and forbidden variants are flagged by QC.
"""

from __future__ import annotations

from pydantic import Field

from osamu_dazai.domain.common import Entity, Lang, Model, id_field


class TermTranslation(Model):
    lang: Lang
    preferred: str
    forbidden_variants: list[str] = Field(default_factory=list)
    approved: bool = False


class Term(Model):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9_\-]*$")  # language-neutral key, e.g. "variable"
    definition: str = ""
    translations: list[TermTranslation] = Field(default_factory=list)
    first_introduced_chapter: int | None = None
    concept_id: str | None = None

    def preferred(self, lang: Lang) -> str | None:
        for t in self.translations:
            if t.lang == lang:
                return t.preferred
        return None


class StyleRule(Model):
    key: str  # e.g. "tone", "reading_level", "decimal_separator", "code_style"
    value: str
    note: str = ""


class Decision(Model):
    id: str = id_field("dec")
    text: str  # e.g. "Recursion is out of scope for this level"
    reason: str = ""
    decided_by: str = ""


class ChapterSummary(Model):
    chapter_number: int
    summary: str
    concepts_introduced: list[str] = Field(default_factory=list)
    examples_used: list[str] = Field(default_factory=list)  # avoid repeating examples


class KnowledgeBase(Entity):
    ID_PREFIX = "kb"
    id: str = id_field(ID_PREFIX)
    project_id: str
    terms: list[Term] = Field(default_factory=list)
    style: list[StyleRule] = Field(default_factory=list)
    notation: list[StyleRule] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    chapter_summaries: list[ChapterSummary] = Field(default_factory=list)

    def term(self, key: str) -> Term | None:
        return next((t for t in self.terms if t.key == key), None)

    def approve_term(self, key: str, lang: Lang, preferred: str, forbidden: list[str] | None = None) -> Term:
        """Record an approved translation, creating the term if needed."""
        term = self.term(key)
        if term is None:
            term = Term(key=key)
            self.terms = [*self.terms, term]
        tr = TermTranslation(lang=lang, preferred=preferred, forbidden_variants=forbidden or [], approved=True)
        term.translations = [t for t in term.translations if t.lang != lang] + [tr]
        return term
