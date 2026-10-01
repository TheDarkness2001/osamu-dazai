"""Teacher guide (spec §10). Must add teaching value, not duplicate the student book."""

from __future__ import annotations

from pydantic import Field

from osamu_dazai.domain.common import Entity, Lang, Model, Provenance, ReviewStatus, id_field


class TimedStep(Model):
    minutes: int = Field(gt=0)
    activity: str
    teacher_actions: str = ""
    student_actions: str = ""


class QuestionWithAnswer(Model):
    question: str
    expected_answer: str
    follow_up: str = ""


class Misconception(Model):
    misconception: str
    why_it_happens: str = ""
    how_to_address: str


class Differentiation(Model):
    support: list[str] = Field(default_factory=list)  # for struggling learners
    extension: list[str] = Field(default_factory=list)  # for advanced learners


class TeacherLesson(Model):
    id: str = id_field("tls")
    lesson_id: str
    chapter_id: str | None = None
    objectives: list[str] = Field(default_factory=list)  # LearningObjective ids
    preparation: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)
    sequence: list[TimedStep] = Field(default_factory=list)
    explanation_points: list[str] = Field(default_factory=list)
    demonstrations: list[str] = Field(default_factory=list)
    activities: list[str] = Field(default_factory=list)
    questions: list[QuestionWithAnswer] = Field(default_factory=list)
    misconceptions: list[Misconception] = Field(default_factory=list)
    differentiation: Differentiation = Field(default_factory=Differentiation)
    assessment: list[str] = Field(default_factory=list)
    homework: str = ""
    homework_key: str = ""
    extension_activities: list[str] = Field(default_factory=list)
    provenance: Provenance = Provenance.AI_GENERATED

    @property
    def planned_minutes(self) -> int:
        return sum(s.minutes for s in self.sequence)


class TeacherGuide(Entity):
    ID_PREFIX = "tgd"
    id: str = id_field(ID_PREFIX)
    course_id: str
    student_book_id: str | None = None
    title: str
    lang: Lang = Lang.EN
    lessons: list[TeacherLesson] = Field(default_factory=list)
    status: ReviewStatus = ReviewStatus.DRAFT
