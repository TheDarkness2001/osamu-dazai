"""Educational Planner (spec §42): free-text idea → CourseBrief.

The LLM *infers* a complete brief and lists what it would ask a teacher.
Nothing it infers counts as confirmed: only values the user supplies (now or
later via ``confirm``) are ``CONFIRMED``. Curriculum design refuses an
unconfirmed brief unless the user explicitly accepts the inferences.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from osamu_dazai.domain.common import Lang, LanguageSettings
from osamu_dazai.domain.project import BriefField, CourseBrief, FieldOrigin, Schedule
from osamu_dazai.pipeline.llm_stage import generate_checked
from osamu_dazai.providers import ProviderRegistry

STAGE = "educational_planner"
PROMPT_VERSION = "planner.v1"

LangCode = Literal["en", "uz", "uz-Cyrl", "ru"]
OUTPUTS = ("student_book", "teacher_guide", "exercises", "projects", "assessments", "visuals", "glossary",
           "answer_key", "slides")


class BriefDraft(BaseModel):
    subject: str
    level: str = Field(description="beginner / intermediate / advanced, or an exam band")
    age_min: int = Field(ge=5, le=99)
    age_max: int = Field(ge=5, le=99)
    duration_weeks: int = Field(ge=1, le=104)
    lessons_per_week: int = Field(ge=1, le=10)
    minutes_per_lesson: int = Field(ge=15, le=240)
    explanation_language: LangCode
    terminology_language: LangCode
    assessment_language: LangCode
    goal: str
    teaching_style: str
    target_book_pages: int = Field(ge=10, le=2000)
    outputs: list[str]
    questions_for_teacher: list[str] = Field(description="What you would ask the teacher before designing, "
                                                         "most important first (max 6).")


SYSTEM = """You are an experienced curriculum planner. From a short request, infer a complete, realistic
course brief. Prefer the explicit details in the request; fill gaps with sensible defaults for the audience
and say what you would confirm with the teacher. Do not invent institutional requirements.
Languages use codes: en, uz (Uzbek, Latin script), uz-Cyrl, ru. Technical terminology may stay in English
while explanations are in another language when that is common practice for the subject."""


def check_draft(d: BriefDraft) -> list[str]:
    problems = []
    if d.age_min > d.age_max:
        problems.append("age_min is greater than age_max")
    unknown = [o for o in d.outputs if o not in OUTPUTS]
    if unknown:
        problems.append(f"unknown outputs {unknown}; choose from {list(OUTPUTS)}")
    if len(d.questions_for_teacher) > 6:
        problems.append("ask at most 6 questions")
    return problems


# Fields a user can supply directly (as already-known facts).
KNOWN_KEYS = {
    "subject", "level", "age_range", "schedule", "languages", "goal", "teaching_style", "target_book_pages",
}


def _bf(value: Any, key: str, known: dict[str, Any]) -> BriefField:
    if key in known:
        return BriefField(value=known[key], origin=FieldOrigin.CONFIRMED)
    return BriefField(value=value, origin=FieldOrigin.INFERRED)


def brief_from_draft(request: str, d: BriefDraft, known: dict[str, Any] | None = None) -> CourseBrief:
    known = dict(known or {})
    bad = set(known) - KNOWN_KEYS
    if bad:
        raise ValueError(f"unknown brief fields {sorted(bad)}")
    return CourseBrief(
        request=request,
        subject=_bf(d.subject, "subject", known),
        level=_bf(d.level, "level", known),
        age_range=_bf((d.age_min, d.age_max), "age_range", known),
        schedule=_bf(Schedule(duration_weeks=d.duration_weeks, lessons_per_week=d.lessons_per_week,
                              minutes_per_lesson=d.minutes_per_lesson), "schedule", known),
        languages=_bf(LanguageSettings(explanation=Lang(d.explanation_language),
                                       terminology=Lang(d.terminology_language),
                                       assessment=Lang(d.assessment_language)), "languages", known),
        goal=_bf(d.goal, "goal", known),
        teaching_style=_bf(d.teaching_style, "teaching_style", known),
        target_book_pages=_bf(d.target_book_pages, "target_book_pages", known),
        outputs=[o for o in d.outputs if o in OUTPUTS],
    )


def confirm(brief: CourseBrief, **values: Any) -> CourseBrief:
    """Confirm fields — with a new value, or ``True`` to accept the inferred one."""
    update = {}
    for key, v in values.items():
        current = getattr(brief, key, None)
        if key not in KNOWN_KEYS or current is None:
            raise ValueError(f"cannot confirm {key!r}")
        update[key] = BriefField(value=current.value if v is True else v, origin=FieldOrigin.CONFIRMED)
    return brief.model_copy(update=update)


def accept_all(brief: CourseBrief) -> CourseBrief:
    return confirm(brief, **dict.fromkeys(brief.unconfirmed_fields(), True))


class PlannerResult(BaseModel):
    brief: CourseBrief
    questions: list[str]
    attempts: int


class EducationalPlanner:
    def __init__(self, registry: ProviderRegistry) -> None:
        self.registry = registry

    async def plan(self, request: str, known: dict[str, Any] | None = None) -> PlannerResult:
        hints = ""
        if known:
            hints = "\nAlready confirmed by the teacher (keep exactly):\n" + "\n".join(
                f"- {k}: {v.model_dump() if isinstance(v, BaseModel) else v}" for k, v in known.items())
        result = await generate_checked(
            self.registry, STAGE, system=SYSTEM, prompt=f"Request: {request}{hints}", schema=BriefDraft,
            check=check_draft, prompt_version=PROMPT_VERSION, max_tokens=8_000,
        )
        brief = brief_from_draft(request, result.value, known)
        return PlannerResult(brief=brief, questions=result.value.questions_for_teacher, attempts=result.attempts)
