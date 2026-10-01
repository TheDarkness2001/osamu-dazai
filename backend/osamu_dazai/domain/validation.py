"""Validation issues and results (spec §14, §32)."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from osamu_dazai.domain.common import Entity, Model, Severity, id_field, utcnow


class Location(Model):
    """Where an issue is. All fields optional; fill what is known."""

    document_id: str | None = None
    chapter: int | None = None
    section_id: str | None = None
    passage: int | None = None
    question_group: str | None = None  # e.g. "Questions 7-8"
    question: int | None = None
    line: int | None = None  # 1-based line in the line IR
    paragraph_index: int | None = None  # 0-based w:p index in a DOCX
    excerpt: str = ""

    def describe(self) -> str:
        parts = []
        for label, value in (
            ("Passage", self.passage),
            ("Chapter", self.chapter),
            ("Group", self.question_group),
            ("Question", self.question),
            ("Line", self.line),
            ("Paragraph", self.paragraph_index),
        ):
            if value is not None:
                parts.append(f"{label} {value}")
        return ", ".join(parts) or "document"


class ValidationIssue(Model):
    code: str  # stable machine id, e.g. "ielts.question.glued"
    severity: Severity
    location: Location = Field(default_factory=Location)
    problem: str
    expected: str = ""
    suggestion: str = ""
    method: str = "deterministic"  # or "llm" — llm findings never block export alone

    def render(self) -> str:
        """Human-readable block in the format of spec §32."""
        lines = [
            f"{self.severity.value.upper()} [{self.code}]",
            f"Location: {self.location.describe()}",
            f"Problem: {self.problem}",
        ]
        if self.location.excerpt:
            lines.append(f"Excerpt: {self.location.excerpt}")
        if self.expected:
            lines.append(f"Expected structure: {self.expected}")
        if self.suggestion:
            lines.append(f"Suggested correction: {self.suggestion}")
        return "\n".join(lines)


class ValidationResult(Entity):
    ID_PREFIX = "val"
    id: str = id_field(ID_PREFIX)
    target_id: str  # document / chapter / assessment id
    target_version: int | None = None
    profile: str  # e.g. "ielts_reading", "student_book"
    issues: list[ValidationIssue] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=utcnow)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [
            i for i in self.issues if i.severity is Severity.ERROR and i.method == "deterministic"
        ]

    @property
    def passed(self) -> bool:
        """True when nothing blocks export."""
        return not self.errors
