"""Course, modules, lessons and learning objectives (spec §7)."""

from __future__ import annotations

from pydantic import Field

from osamu_dazai.domain.common import BloomLevel, Entity, Lang, LanguageSettings, Model, id_field
from osamu_dazai.domain.project import Schedule


class LearningObjective(Entity):
    ID_PREFIX = "lo"
    id: str = id_field(ID_PREFIX)
    text: str = Field(min_length=1)
    bloom_level: BloomLevel
    measurable_verb: str = ""  # e.g. "explain", "write", "compare"
    concept_ids: list[str] = Field(default_factory=list)
    supports: list[str] = Field(default_factory=list)  # course-objective ids a lesson objective serves
    lang: Lang = Lang.EN


class Lesson(Entity):
    ID_PREFIX = "les"
    id: str = id_field(ID_PREFIX)
    number: int = Field(gt=0)  # global order within the course
    title: str
    objective_ids: list[str] = Field(default_factory=list)
    concept_ids: list[str] = Field(default_factory=list)  # concepts introduced here
    minutes: int = Field(default=45, gt=0)
    is_review: bool = False
    is_assessment: bool = False
    chapter_id: str | None = None


class Module(Entity):
    ID_PREFIX = "mod"
    id: str = id_field(ID_PREFIX)
    number: int = Field(gt=0)
    title: str
    summary: str = ""
    objective_ids: list[str] = Field(default_factory=list)
    lessons: list[Lesson] = Field(default_factory=list)
    project_title: str | None = None  # module capstone project, if any


class AssessmentPlanItem(Model):
    title: str
    kind: str  # "quiz" | "exam" | "project" | "homework" ...
    after_lesson: int
    objective_ids: list[str] = Field(default_factory=list)


class Course(Entity):
    ID_PREFIX = "crs"
    id: str = id_field(ID_PREFIX)
    project_id: str
    title: str
    subject: str
    level: str
    age_range: tuple[int, int] | None = None
    languages: LanguageSettings = Field(default_factory=LanguageSettings)
    schedule: Schedule | None = None
    course_objectives: list[LearningObjective] = Field(default_factory=list)
    lesson_objectives: list[LearningObjective] = Field(default_factory=list)
    modules: list[Module] = Field(default_factory=list)
    assessment_plan: list[AssessmentPlanItem] = Field(default_factory=list)
    concept_graph_id: str | None = None

    def all_lessons(self) -> list[Lesson]:
        return [les for m in self.modules for les in m.lessons]

    def all_objectives(self) -> dict[str, LearningObjective]:
        return {lo.id: lo for lo in (*self.course_objectives, *self.lesson_objectives)}
