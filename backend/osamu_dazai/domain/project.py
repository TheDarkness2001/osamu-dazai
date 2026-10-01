"""Project and the planner's course brief (spec §7, §42)."""

from __future__ import annotations

from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import Field

from osamu_dazai.domain.common import Entity, LanguageSettings, Model, ReviewStatus, id_field

T = TypeVar("T")


class ProjectKind(StrEnum):
    COURSE = "course"  # curriculum + student book + teacher guide + assessments
    TEXTBOOK = "textbook"
    IELTS = "ielts"
    ASSESSMENT = "assessment"
    IMPORTED = "imported"  # started from an existing document


class Project(Entity):
    ID_PREFIX = "prj"
    id: str = id_field(ID_PREFIX)
    name: str = Field(min_length=1)
    kind: ProjectKind
    description: str = ""
    languages: LanguageSettings = Field(default_factory=LanguageSettings)
    status: ReviewStatus = ReviewStatus.DRAFT
    owner: str = ""


class FieldOrigin(StrEnum):
    INFERRED = "inferred"  # guessed by the planner — must be shown to the user
    CONFIRMED = "confirmed"  # explicitly given or approved by the user


class BriefField(Model, Generic[T]):
    """A brief value that remembers whether the user confirmed it."""

    value: T
    origin: FieldOrigin = FieldOrigin.INFERRED


class Schedule(Model):
    duration_weeks: int = Field(gt=0)
    lessons_per_week: int = Field(gt=0)
    minutes_per_lesson: int = Field(default=45, gt=0)

    @property
    def total_lessons(self) -> int:
        return self.duration_weeks * self.lessons_per_week


class CourseBrief(Model):
    """Output of the Educational Planner: everything needed before curriculum design."""

    request: str  # the user's original idea, verbatim
    subject: BriefField[str]
    level: BriefField[str]  # e.g. "beginner"
    age_range: BriefField[tuple[int, int]] | None = None
    schedule: BriefField[Schedule] | None = None
    languages: BriefField[LanguageSettings]
    goal: BriefField[str]
    teaching_style: BriefField[str] | None = None
    target_book_pages: BriefField[int] | None = None
    outputs: list[str] = Field(default_factory=list)  # e.g. ["student_book", "teacher_guide"]

    def unconfirmed_fields(self) -> list[str]:
        """Names of fields the user still has to confirm."""
        out = []
        for name in type(self).model_fields:
            v = getattr(self, name)
            if isinstance(v, BriefField) and v.origin is FieldOrigin.INFERRED:
                out.append(name)
        return out
