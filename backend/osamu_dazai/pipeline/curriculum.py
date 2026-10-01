"""Curriculum Architect (spec §7) + learning graph construction (spec §8).

Two checked LLM stages:

1. ``concept_graph``  — concepts and prerequisite links → validated DAG.
2. ``curriculum``     — modules, lessons, objectives, assessment plan, built
   *on* that graph: every concept introduced exactly once, never before its
   prerequisites, lesson count equal to the confirmed schedule, every course
   objective taught and assessed, regular review points.

The LLM works with short keys; code assigns ids, numbers and minutes.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from osamu_dazai.domain.common import BloomLevel, Lang, Severity
from osamu_dazai.domain.curriculum import AssessmentPlanItem, Course, LearningObjective, Lesson, Module
from osamu_dazai.domain.graph import Concept, ConceptGraph
from osamu_dazai.domain.project import CourseBrief
from osamu_dazai.domain.validation import Location, ValidationIssue, ValidationResult
from osamu_dazai.graph import prerequisite_violations, validate_graph
from osamu_dazai.pipeline.llm_stage import generate_checked
from osamu_dazai.providers import ProviderRegistry

GRAPH_STAGE, CURRICULUM_STAGE = "concept_graph", "curriculum_architect"
GRAPH_PROMPT_VERSION, CURRICULUM_PROMPT_VERSION = "graph.v1", "curriculum.v1"
E, W = Severity.ERROR, Severity.WARNING

KEY = re.compile(r"^[a-z0-9][a-z0-9_]*$")
VAGUE_VERBS = {"understand", "know", "learn", "appreciate", "be aware", "be familiar", "realize", "grasp"}
LANG_NAMES = {Lang.EN: "English", Lang.UZ: "Uzbek (Latin script)", Lang.UZ_CYRL: "Uzbek (Cyrillic script)",
              Lang.RU: "Russian"}


class BriefNotConfirmed(ValueError):
    pass


# ---------------------------------------------------------------------------
# LLM-facing drafts
# ---------------------------------------------------------------------------
class ConceptDraft(BaseModel):
    key: str = Field(description="short snake_case id, e.g. for_loop")
    name: str
    description: str
    difficulty: int = Field(ge=1, le=5)
    prerequisites: list[str] = Field(description="keys of concepts that must be learned first")
    group: str = Field(description="topic cluster, e.g. 'control flow'")


class GraphDraft(BaseModel):
    concepts: list[ConceptDraft]


class ObjectiveDraft(BaseModel):
    key: str
    text: str
    bloom_level: BloomLevel
    verb: str = Field(description="the measurable verb used, e.g. write, explain, compare")


class LessonObjectiveDraft(BaseModel):
    text: str
    bloom_level: BloomLevel
    verb: str
    supports: list[str] = Field(description="keys of course objectives this serves")


class LessonDraft(BaseModel):
    title: str
    kind: Literal["teach", "review", "assessment", "project"]
    introduces: list[str] = Field(description="concept keys first taught here, prerequisites first")
    objectives: list[LessonObjectiveDraft]


class ModuleDraft(BaseModel):
    title: str
    summary: str
    lessons: list[LessonDraft]
    project_title: str = ""


class AssessmentDraft(BaseModel):
    title: str
    kind: Literal["quiz", "exam", "project", "homework"]
    after_lesson: int = Field(description="global lesson number (1-based) after which it happens")
    objectives: list[str] = Field(description="course objective keys assessed")


class CurriculumDraft(BaseModel):
    title: str
    course_objectives: list[ObjectiveDraft]
    modules: list[ModuleDraft]
    assessments: list[AssessmentDraft]


# ---------------------------------------------------------------------------
# Graph stage
# ---------------------------------------------------------------------------
def concept_range(total_lessons: int) -> tuple[int, int]:
    lo = max(5, round(total_lessons * 0.3))
    return lo, max(lo + 5, total_lessons)


def build_graph(draft: GraphDraft, course_id: str) -> tuple[ConceptGraph, dict[str, str]]:
    ids = {c.key: f"con_{c.key}" for c in draft.concepts}
    concepts = [Concept(id=ids[c.key], name=c.name.strip(), description=c.description.strip(),
                        difficulty=c.difficulty, prerequisites=[ids[p] for p in dict.fromkeys(c.prerequisites)],
                        taxonomy_group=c.group.strip() or None)
                for c in draft.concepts]
    return ConceptGraph(course_id=course_id, concepts=concepts), ids


def check_graph(draft: GraphDraft, total_lessons: int) -> list[str]:
    problems = []
    keys = [c.key for c in draft.concepts]
    lo, hi = concept_range(total_lessons)
    if not lo <= len(keys) <= hi:
        problems.append(f"give between {lo} and {hi} concepts (got {len(keys)})")
    if bad := [k for k in keys if not KEY.match(k)]:
        problems.append(f"keys must be snake_case: {bad}")
    if dup := sorted({k for k in keys if keys.count(k) > 1}):
        problems.append(f"duplicate keys: {dup}")
    known = set(keys)
    for c in draft.concepts:
        if c.key in c.prerequisites:
            problems.append(f"{c.key} lists itself as a prerequisite")
        if missing := [p for p in c.prerequisites if p not in known]:
            problems.append(f"{c.key}: unknown prerequisites {missing}")
    if problems:
        return problems
    graph, _ = build_graph(draft, "check")
    return [f"{i.problem}" + (f" — {i.suggestion}" if i.suggestion else "")
            for i in validate_graph(graph) if i.severity is E]


# ---------------------------------------------------------------------------
# Curriculum stage
# ---------------------------------------------------------------------------
def assemble_course(draft: CurriculumDraft, brief: CourseBrief, project_id: str, graph: ConceptGraph,
                    concept_ids: dict[str, str]) -> Course:
    lang = brief.languages.value.explanation
    sched = brief.schedule.value if brief.schedule else None
    minutes = sched.minutes_per_lesson if sched else 45
    co = {o.key: LearningObjective(id=f"lo_{o.key}", text=o.text, bloom_level=o.bloom_level,
                                   measurable_verb=o.verb, lang=lang) for o in draft.course_objectives}
    lesson_objs: list[LearningObjective] = []
    modules, n = [], 0
    for mi, m in enumerate(draft.modules, start=1):
        lessons = []
        for ld in m.lessons:
            n += 1
            cids = [concept_ids[k] for k in ld.introduces if k in concept_ids]
            objs = [LearningObjective(id=f"lo_l{n}_{k + 1}", text=o.text, bloom_level=o.bloom_level,
                                      measurable_verb=o.verb, concept_ids=cids, lang=lang,
                                      supports=[co[s].id for s in o.supports if s in co])
                    for k, o in enumerate(ld.objectives)]
            lesson_objs += objs
            lessons.append(Lesson(id=f"les_{n}", number=n, title=ld.title, minutes=minutes, concept_ids=cids,
                                  objective_ids=[o.id for o in objs], is_review=ld.kind == "review",
                                  is_assessment=ld.kind in ("assessment", "project")))
        modules.append(Module(id=f"mod_{mi}", number=mi, title=m.title, summary=m.summary, lessons=lessons,
                              project_title=m.project_title or None))
    plan = [AssessmentPlanItem(title=a.title, kind=a.kind, after_lesson=a.after_lesson,
                               objective_ids=[co[k].id for k in a.objectives if k in co])
            for a in draft.assessments]
    return Course(project_id=project_id, title=draft.title, subject=brief.subject.value, level=brief.level.value,
                  age_range=brief.age_range.value if brief.age_range else None,
                  languages=brief.languages.value, schedule=sched,
                  course_objectives=list(co.values()), lesson_objectives=lesson_objs, modules=modules,
                  assessment_plan=plan, concept_graph_id=graph.id)


def validate_course(course: Course, graph: ConceptGraph, *, max_review_gap: int = 8) -> ValidationResult:
    """Deterministic curriculum checks (spec §14 'Curriculum')."""
    issues: list[ValidationIssue] = []

    def add(code: str, sev: Severity, problem: str, excerpt: str = "", suggestion: str = "") -> None:
        issues.append(ValidationIssue(code=code, severity=sev, problem=problem, suggestion=suggestion,
                                      location=Location(excerpt=excerpt)))

    lessons = course.all_lessons()
    if course.schedule and len(lessons) != course.schedule.total_lessons:
        add("curriculum.lesson_count", E, f"{len(lessons)} lessons, but the schedule has "
            f"{course.schedule.total_lessons} ({course.schedule.duration_weeks} weeks × "
            f"{course.schedule.lessons_per_week})")
    by = graph.by_id()
    introduced: dict[str, tuple[int, int]] = {}
    for les in lessons:
        for pos, cid in enumerate(les.concept_ids):
            if cid not in by:
                add("curriculum.unknown_concept", E, f"Lesson {les.number} introduces unknown concept {cid}")
            elif cid in introduced:
                add("curriculum.concept_reintroduced", E,
                    f"'{by[cid].name}' is introduced in lesson {introduced[cid][0]} and again in lesson {les.number}",
                    suggestion="Introduce each concept once; later lessons practise or review it")
            else:
                introduced[cid] = (les.number, pos)
        if (les.is_review or les.is_assessment) and les.concept_ids:
            add("curriculum.review_introduces", W, f"Lesson {les.number} is a review/assessment lesson but "
                                                  "introduces new concepts")
        if not les.is_review and not les.is_assessment and not les.objective_ids:
            add("curriculum.lesson_without_objective", E, f"Lesson {les.number} '{les.title}' has no objective")
    for c in graph.concepts:
        if c.id not in introduced:
            add("curriculum.concept_missing", E, f"Concept '{c.name}' is never taught",
                suggestion="Introduce it in a lesson after its prerequisites")
    for cid, pid in prerequisite_violations(graph, introduced):
        add("curriculum.prerequisite_violation", E,
            f"'{by[cid].name}' (lesson {introduced[cid][0]}) is taught before its prerequisite "
            f"'{by[pid].name}' (lesson {introduced[pid][0]})",
            suggestion=f"Move '{by[pid].name}' earlier or '{by[cid].name}' later")

    supported = {s for lo in course.lesson_objectives for s in lo.supports}
    assessed = {o for a in course.assessment_plan for o in a.objective_ids}
    for co in course.course_objectives:
        if co.id not in supported:
            add("curriculum.objective_untaught", E, f"Course objective '{co.text}' is not served by any lesson")
        if co.id not in assessed:
            add("curriculum.objective_unassessed", E, f"Course objective '{co.text}' is never assessed")
    for lo in (*course.course_objectives, *course.lesson_objectives):
        if lo.measurable_verb.strip().lower() in VAGUE_VERBS:
            add("curriculum.vague_objective", E, f"Objective '{lo.text}' uses non-measurable verb "
                                                f"'{lo.measurable_verb}'", suggestion="Use e.g. explain, write, compare")
    for a in course.assessment_plan:
        if not 1 <= a.after_lesson <= len(lessons):
            add("curriculum.assessment_out_of_range", E, f"Assessment '{a.title}' is placed after lesson "
                                                        f"{a.after_lesson}, which does not exist")
    gap = 0
    for les in lessons:
        gap = 0 if (les.is_review or les.is_assessment) else gap + 1
        if gap > max_review_gap:
            add("curriculum.review_gap", E, f"Lessons {les.number - gap + 1}-{les.number}: more than "
                                          f"{max_review_gap} lessons without review or assessment",
                suggestion="Insert a review lesson")
            gap = 0
    return ValidationResult(target_id=course.id, profile="curriculum", issues=issues)


def check_curriculum(draft: CurriculumDraft, brief: CourseBrief, graph: ConceptGraph,
                     concept_ids: dict[str, str]) -> list[str]:
    problems = []
    co_keys = [o.key for o in draft.course_objectives]
    if not 3 <= len(co_keys) <= 12:
        problems.append(f"give 3-12 course objectives (got {len(co_keys)})")
    if dup := sorted({k for k in co_keys if co_keys.count(k) > 1}):
        problems.append(f"duplicate objective keys {dup}")
    for m in draft.modules:
        for ld in m.lessons:
            if bad := [k for k in ld.introduces if k not in concept_ids]:
                problems.append(f"lesson '{ld.title}' introduces unknown concept keys {bad}")
            for o in ld.objectives:
                if bad := [s for s in o.supports if s not in co_keys]:
                    problems.append(f"lesson '{ld.title}' objective supports unknown course objectives {bad}")
    for a in draft.assessments:
        if bad := [k for k in a.objectives if k not in co_keys]:
            problems.append(f"assessment '{a.title}' refers to unknown objectives {bad}")
    if problems:
        return problems
    course = assemble_course(draft, brief, "check", graph, concept_ids)
    return [i.problem + (f" — {i.suggestion}" if i.suggestion else "")
            for i in validate_course(course, graph).issues if i.severity is E]


# ---------------------------------------------------------------------------
# Prompts and orchestration
# ---------------------------------------------------------------------------
SYSTEM = """You are a senior curriculum designer. Design for the stated learners, schedule and languages.
Sequence concepts so that nothing is used before it is taught. Objectives must be measurable (Bloom's
taxonomy, observable verbs). Plan regular review and assessment. Do not invent official standards or
institutional requirements."""


def _brief_text(brief: CourseBrief) -> str:
    lv = brief.languages.value
    lines = [f"Subject: {brief.subject.value}", f"Level: {brief.level.value}", f"Goal: {brief.goal.value}",
             f"Explanation language: {LANG_NAMES[lv.explanation]}",
             f"Technical terminology language: {LANG_NAMES[lv.terminology]}",
             f"Assessment language: {LANG_NAMES[lv.assessment]}"]
    if brief.age_range:
        lines.append(f"Learner age: {brief.age_range.value[0]}-{brief.age_range.value[1]}")
    if brief.schedule:
        s = brief.schedule.value
        lines.append(f"Schedule: {s.duration_weeks} weeks × {s.lessons_per_week} lessons of {s.minutes_per_lesson} "
                     f"minutes = {s.total_lessons} lessons")
    if brief.teaching_style:
        lines.append(f"Teaching style: {brief.teaching_style.value}")
    return "\n".join(lines)


class CourseDesign(BaseModel):
    course: Course
    graph: ConceptGraph
    validation: ValidationResult
    graph_warnings: list[ValidationIssue]
    attempts: dict[str, int]


class CurriculumArchitect:
    def __init__(self, registry: ProviderRegistry, *, max_attempts: int = 3) -> None:
        self.registry = registry
        self.max_attempts = max_attempts

    async def design(self, brief: CourseBrief, project_id: str, *, accept_inferred: bool = False) -> CourseDesign:
        if brief.unconfirmed_fields() and not accept_inferred:
            raise BriefNotConfirmed(f"confirm these brief fields first: {brief.unconfirmed_fields()}")
        if brief.schedule is None:
            raise BriefNotConfirmed("the brief has no schedule")
        total = brief.schedule.value.total_lessons
        lo, hi = concept_range(total)
        lang = LANG_NAMES[brief.languages.value.terminology]

        g = await generate_checked(
            self.registry, GRAPH_STAGE, system=SYSTEM, schema=GraphDraft, prompt_version=GRAPH_PROMPT_VERSION,
            max_attempts=self.max_attempts, check=lambda d: check_graph(d, total),
            prompt=f"{_brief_text(brief)}\n\nBuild the learning graph: {lo}-{hi} concepts in teaching order, "
                   f"each with prerequisites (keys). Concept names in {lang}; if explanations use another "
                   "language, add the translation in the description.",
        )
        course_id_placeholder = "pending"
        graph, ids = build_graph(g.value, course_id_placeholder)
        concept_list = "\n".join(f"- {c.key}: {c.name} (prerequisites: {', '.join(c.prerequisites) or 'none'})"
                                 for c in g.value.concepts)

        c = await generate_checked(
            self.registry, CURRICULUM_STAGE, system=SYSTEM, schema=CurriculumDraft,
            prompt_version=CURRICULUM_PROMPT_VERSION, max_attempts=self.max_attempts, max_tokens=64_000,
            check=lambda d: check_curriculum(d, brief, graph, ids),
            prompt=f"{_brief_text(brief)}\n\nConcepts (introduce each exactly once, never before its "
                   f"prerequisites):\n{concept_list}\n\nDesign exactly {total} lessons grouped into modules. "
                   "Include review lessons (no gap longer than 8 teaching lessons), assessments covering every "
                   "course objective, and a project per module where suitable. Write titles and objectives in "
                   f"{LANG_NAMES[brief.languages.value.explanation]}.",
        )
        course = assemble_course(c.value, brief, project_id, graph, ids)
        graph = graph.model_copy(update={"course_id": course.id})
        _link_concepts(graph, course)
        return CourseDesign(course=course, graph=graph, validation=validate_course(course, graph),
                            graph_warnings=[i for i in validate_graph(graph) if i.severity is W],
                            attempts={GRAPH_STAGE: g.attempts, CURRICULUM_STAGE: c.attempts})


def _link_concepts(graph: ConceptGraph, course: Course) -> None:
    """Back-links: concept → objectives that teach it."""
    by_concept: dict[str, list[str]] = {}
    for lo in course.lesson_objectives:
        for cid in lo.concept_ids:
            by_concept.setdefault(cid, []).append(lo.id)
    for concept in graph.concepts:
        concept.learning_objectives = by_concept.get(concept.id, [])
