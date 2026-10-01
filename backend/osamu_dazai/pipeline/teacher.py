"""Teacher Guide generator (spec §10).

One checked LLM stage per chapter produces a plan for every lesson in it.
The guide must add *teaching* value, so the checks reject:

* timing that does not add up to the lesson length,
* teaching lessons without questions + expected answers, misconceptions,
  differentiation or preparation,
* homework without a key,
* text copied from the student book (shingle overlap / long verbatim runs),
* unapproved terminology or the wrong language/script.

Exercise answers are *not* generated here: the student book already holds
them, and the renderer prints them from there, so they can never disagree.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from osamu_dazai.domain.common import Lang, Provenance
from osamu_dazai.domain.content import Chapter, StudentBook
from osamu_dazai.domain.curriculum import Course, Lesson
from osamu_dazai.domain.graph import ConceptGraph
from osamu_dazai.domain.knowledge import KnowledgeBase
from osamu_dazai.domain.teacher import (
    Differentiation,
    Misconception,
    QuestionWithAnswer,
    TeacherGuide,
    TeacherLesson,
    TimedStep,
)
from osamu_dazai.knowledge import find_forbidden, terminology_prompt
from osamu_dazai.pipeline.book import ChapterPlan, plan_chapters, script_ok
from osamu_dazai.pipeline.curriculum import LANG_NAMES
from osamu_dazai.pipeline.llm_stage import generate_checked
from osamu_dazai.providers import ProviderRegistry

STAGE = "teacher_guide"
PROMPT_VERSION = "teacher.chapter.v1"


# ---------------------------------------------------------------------------
# Draft schema
# ---------------------------------------------------------------------------
class StepDraft(BaseModel):
    minutes: int = Field(ge=1)
    activity: str
    teacher_actions: str
    student_actions: str


class QADraft(BaseModel):
    question: str
    expected_answer: str
    follow_up: str = ""


class MisconceptionDraft(BaseModel):
    misconception: str
    why_it_happens: str
    how_to_address: str


class TeacherLessonDraft(BaseModel):
    lesson_number: int
    preparation: list[str]
    resources: list[str]
    sequence: list[StepDraft]
    explanation_points: list[str]
    demonstrations: list[str]
    activities: list[str]
    questions: list[QADraft]
    misconceptions: list[MisconceptionDraft]
    support: list[str] = Field(description="differentiation for students who need more help")
    extension: list[str] = Field(description="differentiation for students who are ahead")
    assessment: list[str] = Field(description="how the teacher checks understanding during the lesson")
    homework: str = ""
    homework_key: str = Field(default="", description="answers / marking guidance for the homework")
    extension_activities: list[str] = Field(default_factory=list)


class TeacherChapterDraft(BaseModel):
    lessons: list[TeacherLessonDraft]


# ---------------------------------------------------------------------------
# Copy detection
# ---------------------------------------------------------------------------
_TOKEN = re.compile(r"\w+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return [t.casefold() for t in _TOKEN.findall(text)]


def shingles(text: str, n: int = 8) -> set[tuple[str, ...]]:
    t = _tokens(text)
    return {tuple(t[i:i + n]) for i in range(len(t) - n + 1)}


def longest_copied_run(text: str, source_shingles: set[tuple[str, ...]], n: int = 8) -> int:
    """Length (in words) of the longest run of ``text`` that appears verbatim in the source."""
    t = _tokens(text)
    best = run = 0
    for i in range(len(t) - n + 1):
        if tuple(t[i:i + n]) in source_shingles:
            run = run + 1 if run else n
            best = max(best, run)
        else:
            run = 0
    return best


def chapter_text(ch: Chapter) -> str:
    parts = [ch.title]
    for s in ch.sections:
        parts.append(s.title)
        for b in s.blocks:
            for attr in ("text", "title", "caption"):
                if isinstance(getattr(b, attr, None), str):
                    parts.append(getattr(b, attr))
            parts += getattr(b, "items", []) or []
    parts += [q.stem for g in ch.exercises for q in g.questions]
    return "\n".join(p for p in parts if p)


def _draft_fields(d: TeacherLessonDraft) -> list[str]:
    parts = [*d.preparation, *d.resources, *d.explanation_points, *d.demonstrations, *d.activities,
             *d.support, *d.extension, *d.assessment, d.homework, d.homework_key, *d.extension_activities]
    parts += [x for s in d.sequence for x in (s.activity, s.teacher_actions, s.student_actions)]
    parts += [x for q in d.questions for x in (q.question, q.expected_answer, q.follow_up)]
    parts += [x for m in d.misconceptions for x in (m.misconception, m.why_it_happens, m.how_to_address)]
    return [p for p in parts if p]


def restated_fields(fields: list[str], source: set[tuple[str, ...]], *, min_words: int = 12,
                    threshold: float = 0.6) -> list[str]:
    """Fields that are mostly student-book text (e.g. a copied sentence as an 'explanation point')."""
    out = []
    for f in fields:
        if len(_tokens(f)) < min_words:
            continue
        mine = shingles(f)
        if mine and len(mine & source) / len(mine) >= threshold:
            out.append(f)
    return out


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
@dataclass
class TeacherContext:
    plan: ChapterPlan
    chapter: Chapter
    kb: KnowledgeBase
    lang: Lang
    max_copied_fraction: float = 0.2
    max_copied_run: int = 20


def check_teacher_chapter(d: TeacherChapterDraft, ctx: TeacherContext) -> list[str]:
    p: list[str] = []
    lessons = {les.number: les for les in ctx.plan.lessons}
    got = [x.lesson_number for x in d.lessons]
    if sorted(got) != sorted(lessons):
        p.append(f"give exactly one plan per lesson {sorted(lessons)} (got {got})")
        return p
    source = shingles(chapter_text(ctx.chapter))
    for x in d.lessons:
        les = lessons[x.lesson_number]
        where = f"lesson {les.number}"
        teaching = not (les.is_review or les.is_assessment)
        total = sum(s.minutes for s in x.sequence)
        if total != les.minutes:
            p.append(f"{where}: timed steps add up to {total} minutes, the lesson is {les.minutes} minutes")
        if len(x.sequence) < 3:
            p.append(f"{where}: give at least 3 timed steps")
        if not x.preparation:
            p.append(f"{where}: list the teacher's preparation")
        if any(not q.expected_answer.strip() for q in x.questions):
            p.append(f"{where}: every question needs an expected answer")
        if teaching:
            if len(x.questions) < 2:
                p.append(f"{where}: give at least 2 questions with expected answers")
            if not x.misconceptions:
                p.append(f"{where}: describe at least one likely misconception and how to address it")
            if not x.support or not x.extension:
                p.append(f"{where}: give differentiation for both support and extension")
            if not x.assessment:
                p.append(f"{where}: say how understanding will be checked")
        elif not x.questions:
            p.append(f"{where}: give at least 1 question with an expected answer")
        if x.homework.strip() and not x.homework_key.strip():
            p.append(f"{where}: homework needs a key (answers or marking guidance)")

        fields = _draft_fields(x)
        text = "\n".join(fields)
        mine = shingles(text)
        if mine:
            frac = len(mine & source) / len(mine)
            if frac > ctx.max_copied_fraction:
                p.append(f"{where}: {frac:.0%} of the guide repeats the student book — explain how to teach it "
                         "instead of restating it")
        run = longest_copied_run(text, source)
        if run > ctx.max_copied_run:
            p.append(f"{where}: contains a {run}-word passage copied from the student book")
        for f in restated_fields(fields, source)[:3]:
            p.append(f"{where}: this just restates the student book — say how to teach it instead: "
                     f"'{f[:80]}…'")
        for hit in find_forbidden(text, ctx.kb, ctx.lang):
            p.append(f"{where}: use the approved term '{hit.preferred}' instead of '{hit.found}'")
        if not script_ok(text, ctx.lang):
            p.append(f"{where}: write in {LANG_NAMES[ctx.lang]}")
    return p


# ---------------------------------------------------------------------------
# Assembly, prompt, orchestration
# ---------------------------------------------------------------------------
def assemble_lessons(d: TeacherChapterDraft, ctx: TeacherContext) -> list[TeacherLesson]:
    lessons = {les.number: les for les in ctx.plan.lessons}
    out = []
    for x in sorted(d.lessons, key=lambda x: x.lesson_number):
        les: Lesson = lessons[x.lesson_number]
        out.append(TeacherLesson(
            lesson_id=les.id, chapter_id=ctx.chapter.id, objectives=list(les.objective_ids),
            preparation=x.preparation, resources=x.resources,
            sequence=[TimedStep(**s.model_dump()) for s in x.sequence],
            explanation_points=x.explanation_points, demonstrations=x.demonstrations, activities=x.activities,
            questions=[QuestionWithAnswer(**q.model_dump()) for q in x.questions],
            misconceptions=[Misconception(**m.model_dump()) for m in x.misconceptions],
            differentiation=Differentiation(support=x.support, extension=x.extension),
            assessment=x.assessment, homework=x.homework, homework_key=x.homework_key,
            extension_activities=x.extension_activities, provenance=Provenance.AI_GENERATED))
    return out


SYSTEM = """You are an experienced teacher educator writing the TEACHER'S GUIDE that accompanies a student
textbook. The teacher already has the student book: do not restate its content. Add what a teacher needs to
teach it well — timing, preparation, how to explain and demonstrate, questions to ask with the answers to
expect, misconceptions and how to address them, support and extension, how to check understanding, homework
with a key. Be concrete and practical for a real classroom. Never invent statistics, studies or sources."""


def teacher_prompt(ctx: TeacherContext, course: Course, graph: ConceptGraph, teaching_style: str = "") -> str:
    by = graph.by_id()
    objectives = course.all_objectives()
    lesson_lines = []
    for les in ctx.plan.lessons:
        kind = "review" if les.is_review else "assessment/project" if les.is_assessment else "teaching"
        objs = "; ".join(objectives[o].text for o in les.objective_ids if o in objectives) or "—"
        new = ", ".join(by[c].name for c in les.concept_ids if c in by) or "—"
        lesson_lines.append(f"- Lesson {les.number} ({kind}, {les.minutes} min): {les.title}. "
                            f"New concepts: {new}. Objectives: {objs}")
    ch = ctx.chapter
    mistakes = [b.text for s in ch.sections if s.kind.value == "common_mistakes" for b in s.blocks
                if getattr(b, "text", "")]
    age = f"{course.age_range[0]}-{course.age_range[1]}" if course.age_range else "unspecified"
    parts = [
        f"Course: {course.title} ({course.subject}, {course.level}, learners aged {age}).",
        f"Write the teacher's guide for chapter {ch.number} '{ch.title}' in {LANG_NAMES[ctx.lang]}.",
        f"Teaching style: {teaching_style}" if teaching_style else "",
        "Lessons (one plan each; timed steps must add up exactly to the lesson length):\n" + "\n".join(lesson_lines),
        f"What the student book chapter covers (summary): {ch.summary}",
        "Student book sections: " + "; ".join(f"{s.kind.value}: {s.title}" for s in ch.sections),
        ("Common mistakes the book already mentions (go deeper — why they happen and how to address them):\n- "
         + "\n- ".join(mistakes)) if mistakes else "",
        "Exercise answers are printed from the student book automatically; do not repeat them.",
        terminology_prompt(ctx.kb, ctx.lang),
    ]
    return "\n\n".join(x for x in parts if x)


@dataclass
class TeacherGuideResult:
    guide: TeacherGuide
    attempts: dict[int, int] = field(default_factory=dict)


class TeacherGuideWriter:
    def __init__(self, registry: ProviderRegistry, *, max_attempts: int = 3) -> None:
        self.registry = registry
        self.max_attempts = max_attempts

    async def write(self, course: Course, graph: ConceptGraph, book: StudentBook, kb: KnowledgeBase, *,
                    n_chapters: int | None = None, teaching_style: str = "") -> TeacherGuideResult:
        lang = course.languages.explanation
        plans = {p.number: p for p in plan_chapters(course, graph, n_chapters)}
        result = TeacherGuideResult(guide=TeacherGuide(course_id=course.id, student_book_id=book.id,
                                                       title=course.title, lang=lang))
        lessons: list[TeacherLesson] = []
        for ch in book.chapters:
            plan = plans.get(ch.number)
            if plan is None or [les.id for les in plan.lessons] != ch.lesson_ids:
                raise ValueError(f"chapter {ch.number} does not match the course's chapter plan; "
                                 "use the same n_chapters as when the book was written")
            ctx = TeacherContext(plan=plan, chapter=ch, kb=kb, lang=lang)
            out = await generate_checked(
                self.registry, STAGE, system=SYSTEM, prompt=teacher_prompt(ctx, course, graph, teaching_style),
                schema=TeacherChapterDraft, check=lambda d, ctx=ctx: check_teacher_chapter(d, ctx),
                prompt_version=PROMPT_VERSION, max_attempts=self.max_attempts, max_tokens=64_000)
            result.attempts[ch.number] = out.attempts
            lessons += assemble_lessons(out.value, ctx)
        result.guide = result.guide.model_copy(update={"lessons": lessons})
        return result
