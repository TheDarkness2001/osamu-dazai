"""Pre-export document checks (spec §14 'Documents').

Missing headings, broken references (figures, exercises), missing images,
incorrect numbering (chapters, exercises, glossary order), broken inline
formatting and malformed tables.
"""

from __future__ import annotations

from osamu_dazai.documents.figures import Figure
from osamu_dazai.documents.inline import unbalanced
from osamu_dazai.domain.common import Severity
from osamu_dazai.domain.content import StudentBook
from osamu_dazai.domain.validation import Location, ValidationIssue, ValidationResult

E, W = Severity.ERROR, Severity.WARNING


def check_student_book(book: StudentBook, figures: dict[str, Figure] | None = None, *,
                       require_figures: bool = False) -> ValidationResult:
    issues: list[ValidationIssue] = []

    def add(code: str, sev: Severity, problem: str, chapter: int | None = None, excerpt: str = "") -> None:
        issues.append(ValidationIssue(code=code, severity=sev, problem=problem,
                                      location=Location(chapter=chapter, excerpt=excerpt[:80])))

    if not book.chapters:
        add("document.empty", E, "The book has no chapters")
    numbers = [c.number for c in book.chapters]
    if numbers != list(range(1, len(numbers) + 1)):
        add("document.chapter_numbering", E, f"Chapters are numbered {numbers}, expected 1…{len(numbers)}")
    for ch in book.chapters:
        n = ch.number
        if not ch.title.strip():
            add("document.missing_heading", E, "Chapter has no title", n)
        if not ch.sections:
            add("document.missing_heading", E, "Chapter has no sections", n)
        groups = {g.id for g in ch.exercises}
        q_numbers = [q.number for g in ch.exercises for q in g.questions]
        if q_numbers != list(range(1, len(q_numbers) + 1)):
            add("document.exercise_numbering", E, f"Exercises are numbered {q_numbers}", n)
        for s in ch.sections:
            if not s.title.strip():
                add("document.missing_heading", E, "Section without a heading", n)
            if not s.blocks:
                add("document.empty_section", W, f"Section '{s.title}' is empty", n, s.title)
            for b in s.blocks:
                k = b.kind
                if k == "visual_ref":
                    if b.visual_id not in ch.visual_specs:
                        add("document.broken_figure_ref", E, f"Figure reference '{b.visual_id}' has no visual", n)
                    elif figures is not None and b.visual_id not in figures:
                        add("document.missing_image", E if require_figures else W,
                            f"Figure '{b.visual_id}' has not been rendered yet (run the visuals step)", n)
                    elif figures is not None and not figures[b.visual_id].path.exists():
                        add("document.missing_image", E, f"Figure file missing: {figures[b.visual_id].path}", n)
                elif k == "question_ref" and b.question_group_id not in groups:
                    add("document.broken_exercise_ref", E, f"Exercise reference '{b.question_group_id}' is broken", n)
                elif k == "table" and any(len(r) != len(b.header) for r in b.rows):
                    add("document.table_shape", E, "Table rows do not match the header", n, b.caption)
                texts = [getattr(b, "text", "")] + list(getattr(b, "items", []) or [])
                for t in texts:
                    if t and unbalanced(t):
                        add("document.broken_formatting", W, "Unbalanced ** or ` markup", n, t)
    terms = [g.term.casefold() for g in book.glossary]
    if terms != sorted(terms):
        add("document.glossary_order", W, "Glossary is not in alphabetical order")
    return ValidationResult(target_id=book.id, profile="student_book_document", issues=issues)
