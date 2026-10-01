"""Assessment generator (spec §9 'Question/assessment engine').

For each item in the course's assessment plan, a deterministic *blueprint*
fixes the question-type mix, time, objectives to cover and the concepts
students have been taught by then. One checked LLM stage writes the items;
checks enforce the blueprint, prerequisite order (no untaught concepts),
objective coverage, cognitive level (Bloom) and difficulty spread, item
quality (via ``validate_assessment``, including the longest-answer leak),
rubrics for extended tasks, language and terminology. Code numbers and groups
the questions.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from osamu_dazai.domain.common import BloomLevel, Lang, Provenance, Severity
from osamu_dazai.domain.curriculum import AssessmentPlanItem, Course, LearningObjective
from osamu_dazai.domain.graph import ConceptGraph
from osamu_dazai.domain.knowledge import KnowledgeBase
from osamu_dazai.domain.questions import (
    Answer,
    Assessment,
    AssessmentKind,
    Option,
    Question,
    QuestionGroup,
    QuestionType,
    Rubric,
    RubricCriterion,
    RubricLevel,
)
from osamu_dazai.knowledge import find_forbidden, terminology_prompt
from osamu_dazai.pipeline.book import script_ok
from osamu_dazai.pipeline.curriculum import LANG_NAMES
from osamu_dazai.pipeline.llm_stage import generate_checked
from osamu_dazai.providers import ProviderRegistry
from osamu_dazai.questions.shuffle import rebalanced
from osamu_dazai.questions.validate import validate_assessment

STAGE = "assessment_generator"
PROMPT_VERSION = "assessment.v1"
QT = QuestionType
HIGHER_ORDER = {BloomLevel.APPLY, BloomLevel.ANALYZE, BloomLevel.EVALUATE, BloomLevel.CREATE}
DraftType = Literal["multiple_choice", "true_false", "completion", "short_answer", "code", "essay"]
TYPE_ORDER: list[str] = ["multiple_choice", "true_false", "completion", "short_answer", "code", "essay"]
TYPE_MAP = {"multiple_choice": QT.MULTIPLE_CHOICE, "true_false": QT.TRUE_FALSE, "completion": QT.COMPLETION,
            "short_answer": QT.SHORT_ANSWER, "code": QT.CODE, "essay": QT.ESSAY}
KIND_MAP = {"quiz": AssessmentKind.QUIZ, "exam": AssessmentKind.EXAM, "homework": AssessmentKind.HOMEWORK,
            "project": AssessmentKind.PROJECT}

DEFAULTS: dict[str, dict] = {
    "quiz": {"mix": {"multiple_choice": 7, "short_answer": 3}, "code_mix": {"multiple_choice": 7, "short_answer": 1,
                                                                            "code": 2}, "minutes": 20, "higher": 0.3},
    "exam": {"mix": {"multiple_choice": 12, "true_false": 3, "short_answer": 4, "essay": 1},
             "code_mix": {"multiple_choice": 12, "true_false": 3, "short_answer": 2, "code": 2, "essay": 1},
             "minutes": 45, "higher": 0.4},
    "homework": {"mix": {"completion": 2, "short_answer": 4}, "code_mix": {"completion": 2, "short_answer": 1, "code": 3},
                 "minutes": 30, "higher": 0.3},
    "project": {"mix": {"essay": 1}, "code_mix": {"essay": 1}, "minutes": 90, "higher": 1.0},
}


# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------
@dataclass
class Blueprint:
    item: AssessmentPlanItem
    kind: str
    mix: dict[str, int]
    minutes: int
    objectives: list[LearningObjective]
    taught: dict[str, str]  # concept id -> name, taught by item.after_lesson
    higher_order_share: float

    @property
    def total(self) -> int:
        return sum(self.mix.values())


def blueprint(course: Course, graph: ConceptGraph, item: AssessmentPlanItem, *, include_code: bool = False,
              mix: dict[str, int] | None = None) -> Blueprint:
    kind = item.kind if item.kind in DEFAULTS else "quiz"
    d = DEFAULTS[kind]
    by = graph.by_id()
    taught = {c: by[c].name for les in course.all_lessons() if les.number <= item.after_lesson
              for c in les.concept_ids if c in by}
    objs = course.all_objectives()
    return Blueprint(item=item, kind=kind, mix=dict(mix or (d["code_mix"] if include_code else d["mix"])),
                     minutes=d["minutes"], objectives=[objs[o] for o in item.objective_ids if o in objs],
                     taught=taught, higher_order_share=d["higher"])


# ---------------------------------------------------------------------------
# Draft schema
# ---------------------------------------------------------------------------
class QDraft(BaseModel):
    type: DraftType
    stem: str = Field(description="question text; completion items contain a ______ blank")
    options: list[str] = Field(default_factory=list, description="multiple choice: 4 options, no letters")
    answer: str = Field(description="letter for multiple choice; TRUE/FALSE; model answer otherwise")
    alternatives: list[str] = Field(default_factory=list, description="other acceptable answers")
    explanation: str = Field(description="why the answer is correct (for the teacher)")
    objectives: list[str] = Field(description="ids of the objectives assessed")
    concepts: list[str] = Field(description="ids of the concepts used")
    bloom_level: BloomLevel
    difficulty: int = Field(ge=1, le=5)
    points: float = Field(default=1, gt=0)


class LevelDraft(BaseModel):
    score: float
    descriptor: str


class CriterionDraft(BaseModel):
    name: str
    weight: float = 1
    levels: list[LevelDraft]


class RubricDraft(BaseModel):
    title: str
    criteria: list[CriterionDraft]


class AssessmentDraft(BaseModel):
    title: str
    instructions: str
    questions: list[QDraft]
    rubrics: list[RubricDraft] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Assembly + checks
# ---------------------------------------------------------------------------
def assemble(d: AssessmentDraft, bp: Blueprint, course: Course) -> Assessment:
    groups, number = [], 0
    for t in TYPE_ORDER:
        items = [q for q in d.questions if q.type == t]
        if not items:
            continue
        qs = []
        for q in items:
            number += 1
            qs.append(Question(
                number=number, type=TYPE_MAP[t], stem=q.stem,
                options=[Option(label="ABCDEFGH"[i], text=o) for i, o in enumerate(q.options)],
                answer=Answer(accepted=[q.answer.strip(), *[a.strip() for a in q.alternatives if a.strip()]],
                              explanation=q.explanation),
                concept_ids=list(q.concepts), objective_ids=list(q.objectives), bloom_level=q.bloom_level,
                difficulty=q.difficulty, points=q.points, provenance=Provenance.AI_GENERATED))
        groups.append(QuestionGroup(id=f"qg_{t}", type=TYPE_MAP[t], title=t, questions=qs))
    rubrics = [Rubric(title=r.title, criteria=[
        RubricCriterion(name=c.name, weight=c.weight, levels=[RubricLevel(score=lv.score, descriptor=lv.descriptor)
                                                               for lv in c.levels]) for c in r.criteria])
        for r in d.rubrics if r.criteria and all(c.levels for c in r.criteria)]
    return Assessment(project_id=course.project_id, course_id=course.id, kind=KIND_MAP[bp.kind], title=d.title,
                      instructions=d.instructions, duration_minutes=bp.minutes, groups=groups, rubrics=rubrics)


def check_draft(d: AssessmentDraft, bp: Blueprint, course: Course, kb: KnowledgeBase, lang: Lang,
                code_language: str = "") -> list[str]:
    p: list[str] = []
    counts = Counter(q.type for q in d.questions)
    if dict(counts) != {k: v for k, v in bp.mix.items() if v}:
        p.append(f"question types must be exactly {bp.mix} (got {dict(counts)})")
    obj_ids = {o.id for o in bp.objectives}
    for i, q in enumerate(d.questions, start=1):
        if bad := [o for o in q.objectives if o not in obj_ids]:
            p.append(f"question {i}: objectives {bad} are not part of this assessment")
        if not q.objectives:
            p.append(f"question {i}: name the objective(s) it assesses")
        if untaught := [c for c in q.concepts if c not in bp.taught]:
            p.append(f"question {i}: uses concepts not yet taught by lesson {bp.item.after_lesson}: {untaught}")
        if q.type == "multiple_choice" and len(q.options) != 4:
            p.append(f"question {i}: multiple choice needs exactly 4 options")
    covered = {o for q in d.questions for o in q.objectives}
    for o in bp.objectives:
        if o.id not in covered:
            p.append(f"objective '{o.text}' ({o.id}) is not assessed by any question")
    n = len(d.questions)
    if n:
        higher = sum(q.bloom_level in HIGHER_ORDER for q in d.questions) / n
        if higher + 1e-9 < bp.higher_order_share:
            p.append(f"only {higher:.0%} of questions are apply-level or higher; need at least "
                     f"{bp.higher_order_share:.0%}")
        if n >= 4 and len({q.difficulty for q in d.questions}) < 2:
            p.append("vary question difficulty (all items have the same difficulty)")
    if counts.get("essay") and not any(len(r.criteria) >= 3 for r in d.rubrics):
        p.append("extended tasks need a rubric with at least 3 criteria")
    if p:
        return p
    a = assemble(d, bp, course)
    result = validate_assessment(a, code_language=code_language)
    p += [f"question {i.location.question}: {i.problem}" if i.location.question else i.problem
          for i in result.issues if i.severity is Severity.ERROR or i.code == "question.longest_answer_bias"]
    text = " ".join([d.title, d.instructions, *(q.stem for q in d.questions),
                     *(o for q in d.questions for o in q.options)])
    for hit in find_forbidden(text, kb, lang):
        p.append(f"use the approved term '{hit.preferred}' instead of '{hit.found}'")
    if not script_ok(text, lang):
        p.append(f"write the assessment in {LANG_NAMES[lang]}")
    return p


# ---------------------------------------------------------------------------
# Prompt + orchestration
# ---------------------------------------------------------------------------
SYSTEM = """You write fair, valid assessment items for a course. Assess only what has been taught. Each
item targets a stated objective; vary cognitive level (Bloom) and difficulty as required. Multiple-choice
items have one clearly correct answer and plausible distractors of similar length and form; avoid 'all of
the above' / 'none of the above', trick wording and clues in the stem. Short and code answers include a model
answer; extended tasks come with a rubric. Explanations are for the teacher."""


def prompt(bp: Blueprint, course: Course, kb: KnowledgeBase, lang: Lang, code_language: str) -> str:
    objectives = "\n".join(f"- {o.id}: {o.text} ({o.bloom_level.value})" for o in bp.objectives)
    concepts = "\n".join(f"- {cid}: {name}" for cid, name in bp.taught.items())
    mix = ", ".join(f"{v} × {k}" for k, v in bp.mix.items() if v)
    parts = [
        f"Course: {course.title} ({course.subject}, {course.level}).",
        f"Write the {bp.kind} '{bp.item.title}' (after lesson {bp.item.after_lesson}, about {bp.minutes} minutes) "
        f"in {LANG_NAMES[lang]}.",
        f"Exactly these question types: {mix}.",
        f"Objectives to assess (each at least once):\n{objectives}",
        f"Concepts taught so far — use only these:\n{concepts}",
        f"At least {bp.higher_order_share:.0%} of questions at apply level or higher; vary difficulty.",
        f"Code answers are written in {code_language}." if code_language else "",
        "True/false answers are written as TRUE or FALSE. Multiple-choice answers are the option letter (A-D).",
        terminology_prompt(kb, lang),
    ]
    return "\n\n".join(x for x in parts if x)


@dataclass
class AssessmentResult:
    assessments: list[Assessment] = field(default_factory=list)
    attempts: dict[str, int] = field(default_factory=dict)


class AssessmentGenerator:
    def __init__(self, registry: ProviderRegistry, *, max_attempts: int = 3) -> None:
        self.registry = registry
        self.max_attempts = max_attempts

    async def generate(self, course: Course, graph: ConceptGraph, item: AssessmentPlanItem, kb: KnowledgeBase, *,
                       code_language: str = "", mix: dict[str, int] | None = None) -> tuple[Assessment, int]:
        lang = course.languages.assessment
        bp = blueprint(course, graph, item, include_code=bool(code_language), mix=mix)
        out = await generate_checked(
            self.registry, STAGE, system=SYSTEM, prompt=prompt(bp, course, kb, lang, code_language),
            schema=AssessmentDraft, prompt_version=PROMPT_VERSION, max_attempts=self.max_attempts,
            check=lambda d: check_draft(d, bp, course, kb, lang, code_language), max_tokens=64_000)
        return rebalanced(assemble(out.value, bp, course)), out.attempts

    async def generate_all(self, course: Course, graph: ConceptGraph, kb: KnowledgeBase, *,
                           code_language: str = "") -> AssessmentResult:
        res = AssessmentResult()
        for item in course.assessment_plan:
            a, attempts = await self.generate(course, graph, item, kb, code_language=code_language)
            res.assessments.append(a)
            res.attempts[item.title] = attempts
        return res
