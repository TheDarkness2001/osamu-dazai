"""Student-book generator (spec §9) built on the curriculum and learning graph.

* ``plan_chapters`` splits the lesson sequence into chapters (default: one per
  module) and works out, per chapter, which concepts are new, which are known,
  and which come later.
* Each chapter is one checked LLM stage. The model chooses and orders sections
  from the palette — chapters are *not* forced into one template — but every
  chapter must have objectives, practice and a review.
* Checks: required sections, every new concept actually explained, approved
  terminology, glossary consistency, code syntax (and, opt-in, expected
  output), language/script, length. Later-chapter concepts named in the prose
  are reported as warnings for the human reviewer.
* After each chapter its summary, examples and glossary go into the knowledge
  base so later chapters build on them consistently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from osamu_dazai.domain.common import Lang, Provenance, Severity
from osamu_dazai.domain.content import (
    Block,
    CalloutBlock,
    Chapter,
    CodeBlock,
    EquationBlock,
    GlossaryEntry,
    ListBlock,
    ParagraphBlock,
    QuestionRefBlock,
    Section,
    SectionKind,
    StudentBook,
    TableBlock,
    VisualRefBlock,
)
from osamu_dazai.domain.curriculum import Course, LearningObjective, Lesson
from osamu_dazai.domain.graph import ConceptGraph
from osamu_dazai.domain.knowledge import KnowledgeBase
from osamu_dazai.domain.questions import Answer, Option, Question, QuestionGroup, QuestionType
from osamu_dazai.domain.validation import Location, ValidationIssue
from osamu_dazai.domain.visuals import RenderStrategy, VisualKind, VisualSpec
from osamu_dazai.knowledge import (
    contains_term,
    find_forbidden,
    glossary_conflicts,
    learn_terms,
    previous_chapters_prompt,
    record_chapter,
    terminology_prompt,
)
from osamu_dazai.pipeline.curriculum import LANG_NAMES
from osamu_dazai.pipeline.llm_stage import generate_checked
from osamu_dazai.providers import ProviderRegistry
from osamu_dazai.quality.code import check_syntax, run_and_compare

STAGE = "book_writer"
PROMPT_VERSION = "book.chapter.v1"
SK = SectionKind
PRACTICE = {SK.GUIDED_PRACTICE, SK.INDEPENDENT_PRACTICE}
EXERCISE_SECTIONS = ("guided_practice", "independent_practice", "challenge", "mini_project", "quiz", "homework")


# ---------------------------------------------------------------------------
# Chapter planning (deterministic)
# ---------------------------------------------------------------------------
@dataclass
class ChapterPlan:
    number: int
    lessons: list[Lesson]
    introduces: list[str]  # concept ids, teaching order
    known: list[str]  # introduced in earlier chapters
    later: list[str]  # introduced in later chapters
    objectives: list[LearningObjective]


def plan_chapters(course: Course, graph: ConceptGraph, n_chapters: int | None = None) -> list[ChapterPlan]:
    lessons = course.all_lessons()
    if n_chapters is None:
        chunks = [m.lessons for m in course.modules if m.lessons]
    else:
        teach = [i for i, les in enumerate(lessons) if not (les.is_review or les.is_assessment)]
        if not 1 <= n_chapters <= len(teach):
            raise ValueError(f"cannot make {n_chapters} chapters from {len(teach)} teaching lessons")
        starts = [teach[k * len(teach) // n_chapters] for k in range(n_chapters)]
        starts[0] = 0
        chunks = [lessons[s:e] for s, e in zip(starts, [*starts[1:], len(lessons)], strict=True)]
    objectives = course.all_objectives()
    intro_by_chunk = [[c for les in ch for c in les.concept_ids] for ch in chunks]
    plans, seen = [], []
    for i, ch in enumerate(chunks):
        later = [c for rest in intro_by_chunk[i + 1:] for c in rest]
        plans.append(ChapterPlan(number=i + 1, lessons=ch, introduces=intro_by_chunk[i], known=list(seen),
                                 later=later, objectives=[objectives[o] for les in ch for o in les.objective_ids
                                                          if o in objectives]))
        seen += intro_by_chunk[i]
    return plans


# ---------------------------------------------------------------------------
# LLM-facing draft
# ---------------------------------------------------------------------------
class BlockDraft(BaseModel):
    kind: Literal["paragraph", "list", "code", "callout", "table", "equation", "visual"]
    text: str = Field(default="", description="paragraph/callout text, or LaTeX for equations")
    items: list[str] = Field(default_factory=list)
    ordered: bool = False
    code: str = ""
    language: str = Field(default="", description="programming language of a code block")
    expected_output: str = Field(default="", description="exact output of a runnable example, if any")
    style: Literal["note", "tip", "warning", "common_mistake", "definition", "example"] = "note"
    title: str = ""
    header: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    visual_kind: VisualKind | None = Field(default=None, description="for kind=visual")
    visual_purpose: str = Field(default="", description="why this visual helps learning")
    visual_description: str = Field(default="", description="what the visual shows (nodes, steps, data…)")


class SectionDraft(BaseModel):
    kind: SectionKind
    title: str
    blocks: list[BlockDraft]


class ExerciseDraft(BaseModel):
    section: Literal["guided_practice", "independent_practice", "challenge", "mini_project", "quiz", "homework"]
    kind: Literal["short_answer", "code", "multiple_choice"]
    prompt: str
    options: list[str] = Field(default_factory=list, description="multiple choice only, without letters")
    answer: str = Field(description="model answer; a letter for multiple choice")
    difficulty: int = Field(ge=1, le=5)


class GlossaryDraft(BaseModel):
    key: str = Field(description="language-neutral snake_case key, e.g. variable")
    term: str = Field(description="the term as used in this chapter's explanation language")
    definition: str


class ChapterDraft(BaseModel):
    title: str
    summary: str = Field(description="3-4 sentences for later chapters")
    sections: list[SectionDraft]
    exercises: list[ExerciseDraft]
    glossary: list[GlossaryDraft]
    examples_used: list[str] = Field(description="short labels of the worked examples used")


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
_WORD = re.compile(r"\w+", re.UNICODE)
_KEY = re.compile(r"^[a-z0-9][a-z0-9_]*$")


def _prose(d: ChapterDraft, *, skip_objectives: bool = False) -> str:
    parts = [d.title]
    for s in d.sections:
        if skip_objectives and s.kind is SK.OBJECTIVES:
            continue
        parts.append(s.title)
        for b in s.blocks:
            parts += [b.text, b.title, *b.items, *b.header, *(c for r in b.rows for c in r)]
    return "\n".join(p for p in parts if p)


def script_ok(text: str, lang: Lang) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 200:
        return True
    cyr = sum("Ѐ" <= ch <= "ӿ" for ch in letters) / len(letters)
    return cyr > 0.5 if lang in (Lang.RU, Lang.UZ_CYRL) else cyr < 0.2


@dataclass
class ChapterContext:
    plan: ChapterPlan
    graph: ConceptGraph
    kb: KnowledgeBase
    lang: Lang
    target_words: int
    execute_code: bool = False


def check_chapter(d: ChapterDraft, ctx: ChapterContext) -> list[str]:
    p: list[str] = []
    kinds = [s.kind for s in d.sections]
    if SK.OBJECTIVES not in kinds:
        p.append("add an 'objectives' section")
    if SK.REVIEW not in kinds:
        p.append("add a 'review' section")
    if not PRACTICE & set(kinds):
        p.append("add a guided_practice or independent_practice section")
    for e in d.exercises:
        if SK(e.section) not in kinds:
            p.append(f"an exercise belongs to section '{e.section}', but the chapter has no such section")
            break
    if len(d.exercises) < 3:
        p.append("give at least 3 exercises")
    for i, e in enumerate(d.exercises, start=1):
        if not e.answer.strip():
            p.append(f"exercise {i} has no model answer")
        if e.kind == "multiple_choice":
            letters = "ABCDEFGH"[: len(e.options)]
            if len(e.options) < 3 or e.answer.strip() not in letters:
                p.append(f"exercise {i}: multiple choice needs ≥3 options and a letter answer")

    for s in d.sections:
        if not s.blocks:
            p.append(f"section '{s.title}' is empty")
        for b in s.blocks:
            where = f"section '{s.title}'"
            if b.kind == "list" and not b.items:
                p.append(f"{where}: empty list")
            elif b.kind == "table" and (not b.header or any(len(r) != len(b.header) for r in b.rows)):
                p.append(f"{where}: table rows must match the header")
            elif b.kind == "visual" and (b.visual_kind is None or not b.visual_purpose.strip()):
                p.append(f"{where}: a visual needs visual_kind and visual_purpose")
            elif b.kind == "code":
                if not b.code.strip() or not b.language.strip():
                    p.append(f"{where}: code block needs code and language")
                    continue
                chk = check_syntax(b.language, b.code)
                if not chk.ok:
                    p.append(f"{where}: {chk.message}")
                elif ctx.execute_code and b.expected_output.strip():
                    run = run_and_compare(b.language, b.code, b.expected_output)
                    if not run.ok:
                        p.append(f"{where}: {run.message}")
            elif b.kind in ("paragraph", "callout") and not b.text.strip():
                p.append(f"{where}: empty {b.kind}")
    code_lang = _code_language(d)
    for i, e in enumerate(d.exercises, start=1):
        if e.kind == "code" and code_lang:
            chk = check_syntax(code_lang, e.answer)
            if not chk.ok:
                p.append(f"exercise {i} model answer: {chk.message}")

    prose = _prose(d, skip_objectives=True)
    by = ctx.graph.by_id()
    for cid in ctx.plan.introduces:
        c = by[cid]
        names = [*_name_variants(c.name), *_name_variants(cid.removeprefix("con_").replace("_", " ")),
                 *_kb_names(ctx.kb, cid, c.name, ctx.lang)]
        if not any(contains_term(prose, n) for n in names):
            p.append(f"the new concept '{c.name}' is never explained (name it explicitly)")

    for hit in find_forbidden(_prose(d), ctx.kb, ctx.lang):
        p.append(f"use the approved term '{hit.preferred}' instead of '{hit.found}'")
    bad_keys = [g.key for g in d.glossary if not _KEY.match(g.key)]
    if bad_keys:
        p.append(f"glossary keys must be snake_case: {bad_keys}")
    p += glossary_conflicts([(g.key, g.term) for g in d.glossary], ctx.kb, ctx.lang)

    words = len(_WORD.findall(prose))
    if words < ctx.target_words * 0.5:
        p.append(f"chapter is too short: {words} words, target about {ctx.target_words}")
    if not script_ok(prose, ctx.lang):
        p.append(f"write the chapter in {LANG_NAMES[ctx.lang]}")
    return p


def _code_language(d: ChapterDraft) -> str:
    langs = [b.language for s in d.sections for b in s.blocks if b.kind == "code" and b.language]
    return max(set(langs), key=langs.count) if langs else ""


def _name_variants(name: str) -> list[str]:
    """'Variables' → also 'Variable'; 'Lists and tuples' stays as is plus its singular head."""
    base = re.sub(r"\s*\(.*?\)", "", name).strip()
    out = [name, base]
    if base.endswith("es") and len(base) > 4:
        out.append(base[:-2])
    if base.endswith("s") and len(base) > 3:
        out.append(base[:-1])
    return [n for n in dict.fromkeys(out) if n]


def _kb_names(kb: KnowledgeBase, concept_id: str, name: str, lang: Lang) -> list[str]:
    out = []
    for t in kb.terms:
        if t.concept_id == concept_id or t.key == concept_id.removeprefix("con_"):
            out += [tr.preferred for tr in t.translations if tr.lang == lang]
    return out


def later_concept_warnings(d: ChapterDraft, ctx: ChapterContext) -> list[ValidationIssue]:
    prose = _prose(d, skip_objectives=True)
    by = ctx.graph.by_id()
    return [
        ValidationIssue(code="book.concept_before_introduction", severity=Severity.WARNING,
                        location=Location(chapter=ctx.plan.number, excerpt=by[c].name),
                        problem=f"Chapter {ctx.plan.number} mentions '{by[c].name}', which is taught in a later "
                                "chapter — check it is not used before it is explained")
        for c in ctx.plan.later if len(by[c].name) > 3 and contains_term(prose, by[c].name)
    ]


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
_QTYPE = {"short_answer": QuestionType.SHORT_ANSWER, "code": QuestionType.CODE,
          "multiple_choice": QuestionType.MULTIPLE_CHOICE}


def assemble_chapter(d: ChapterDraft, ctx: ChapterContext) -> Chapter:
    n, lang = ctx.plan.number, ctx.lang
    common = {"lang": lang, "provenance": Provenance.AI_GENERATED}
    visual_specs: dict[str, VisualSpec] = {}

    def block(b: BlockDraft) -> Block:
        if b.kind == "paragraph":
            return ParagraphBlock(text=b.text, **common)
        if b.kind == "list":
            return ListBlock(items=b.items, ordered=b.ordered, **common)
        if b.kind == "code":
            return CodeBlock(language=b.language.lower(), code=b.code, expected_output=b.expected_output or None,
                             runnable=bool(b.expected_output), **common)
        if b.kind == "callout":
            return CalloutBlock(style=b.style, title=b.title, text=b.text, **common)
        if b.kind == "table":
            return TableBlock(caption=b.title, header=b.header, rows=b.rows, **common)
        if b.kind == "equation":
            return EquationBlock(latex=b.text, **common)
        vid = f"vis_ch{n}_{len(visual_specs) + 1}"
        image = b.visual_kind is VisualKind.ILLUSTRATION
        visual_specs[vid] = VisualSpec(kind=b.visual_kind, purpose=b.visual_purpose, title=b.title,
                                       alt_text=b.visual_description[:300],
                                       render_strategy=RenderStrategy.IMAGE_GEN if image else RenderStrategy.MERMAID,
                                       data={"description": b.visual_description},
                                       image_prompt=b.visual_description if image else None)
        return VisualRefBlock(visual_id=vid, caption=b.title, **common)

    sections = [Section(kind=s.kind, title=s.title, blocks=[block(b) for b in s.blocks]) for s in d.sections]

    groups: list[QuestionGroup] = []
    number = 0
    for sec_kind in EXERCISE_SECTIONS:
        items = [e for e in d.exercises if e.section == sec_kind]
        if not items:
            continue
        questions = []
        for e in items:
            number += 1
            qtype = _QTYPE[e.kind]
            questions.append(Question(
                number=number, type=qtype, stem=e.prompt, difficulty=e.difficulty,
                options=[Option(label="ABCDEFGH"[k], text=t) for k, t in enumerate(e.options)],
                answer=Answer(accepted=[e.answer]), concept_ids=list(ctx.plan.introduces),
                provenance=Provenance.AI_GENERATED))
        group = QuestionGroup(id=f"qg_ch{n}_{sec_kind}", type=questions[0].type, title=sec_kind,
                              questions=questions)
        groups.append(group)
        target = next(s for s in sections if s.kind.value == sec_kind)
        target.blocks = [*target.blocks, QuestionRefBlock(question_group_id=group.id, **common)]
    by = ctx.graph.by_id()
    uses = sorted({p for c in ctx.plan.introduces for p in by[c].prerequisites if p in ctx.plan.known})
    return Chapter(number=n, title=d.title, summary=d.summary, sections=sections, exercises=groups,
                   visual_specs=visual_specs, introduces_concepts=list(ctx.plan.introduces), uses_concepts=uses,
                   lesson_ids=[les.id for les in ctx.plan.lessons],
                   objective_ids=[o.id for o in ctx.plan.objectives])


# ---------------------------------------------------------------------------
# Prompt + orchestration
# ---------------------------------------------------------------------------
SYSTEM = """You write chapters of a student textbook. Students read this text themselves: never address the
teacher or include teaching instructions. Explain clearly for the stated audience, introduce every new concept
explicitly by name, give worked examples before practice, and anticipate common mistakes. Use only concepts the
students already know or that this chapter introduces. Choose and order sections to fit the subject — not every
chapter needs every section type — but always include objectives, practice and a review. Ask for a visual only
when it genuinely helps understanding, and describe it precisely. Never invent statistics, quotations or
sources. Exercises need model answers (they are printed only in the teacher's answer key)."""


def chapter_prompt(ctx: ChapterContext, course: Course, terminology_lang: Lang) -> str:
    by = ctx.graph.by_id()
    pl = ctx.plan
    new = "\n".join(f"- {by[c].name}: {by[c].description}" for c in pl.introduces) or "- (practice chapter)"
    known = ", ".join(by[c].name for c in pl.known) or "nothing yet"
    lessons = "\n".join(f"- {les.title}" for les in pl.lessons)
    objectives = "\n".join(f"- {o.text}" for o in pl.objectives) or "- (see lessons)"
    age = f"{course.age_range[0]}-{course.age_range[1]}" if course.age_range else "unspecified"
    parts = [
        f"Course: {course.title} ({course.subject}, {course.level}, learners aged {age}).",
        f"Write chapter {pl.number} in {LANG_NAMES[ctx.lang]}. Technical terms in {LANG_NAMES[terminology_lang]}"
        + ("." if terminology_lang == ctx.lang else f", with the {LANG_NAMES[ctx.lang]} term first and the "
                                                     f"{LANG_NAMES[terminology_lang]} term in parentheses."),
        f"Lessons covered:\n{lessons}",
        f"Learning objectives:\n{objectives}",
        f"New concepts (explain each, in this order):\n{new}",
        f"Students already know: {known}.",
        f"Length: about {ctx.target_words} words of text.",
        "Section kinds available: " + ", ".join(k.value for k in SK if k is not SK.CUSTOM) + ", custom.",
        terminology_prompt(ctx.kb, ctx.lang),
        previous_chapters_prompt(ctx.kb, pl.number),
    ]
    return "\n\n".join(x for x in parts if x)


@dataclass
class BookResult:
    book: StudentBook
    kb: KnowledgeBase
    warnings: list[ValidationIssue] = field(default_factory=list)
    attempts: dict[int, int] = field(default_factory=dict)


class BookWriter:
    def __init__(self, registry: ProviderRegistry, *, max_attempts: int = 3, execute_code: bool = False) -> None:
        self.registry = registry
        self.max_attempts = max_attempts
        self.execute_code = execute_code

    async def write(self, course: Course, graph: ConceptGraph, kb: KnowledgeBase, *, n_chapters: int | None = None,
                    words_per_chapter: int = 2500, only: list[int] | None = None) -> BookResult:
        lang, term_lang = course.languages.explanation, course.languages.terminology
        kb = kb.model_copy(deep=True)
        result = BookResult(book=StudentBook(course_id=course.id, title=course.title, lang=lang), kb=kb)
        chapters: list[Chapter] = []
        glossary: dict[str, GlossaryEntry] = {}
        for plan in plan_chapters(course, graph, n_chapters):
            if only and plan.number not in only:
                continue
            ctx = ChapterContext(plan=plan, graph=graph, kb=kb, lang=lang, target_words=words_per_chapter,
                                 execute_code=self.execute_code)
            out = await generate_checked(
                self.registry, STAGE, system=SYSTEM, prompt=chapter_prompt(ctx, course, term_lang),
                schema=ChapterDraft, check=lambda d, ctx=ctx: check_chapter(d, ctx),
                prompt_version=PROMPT_VERSION, max_attempts=self.max_attempts, max_tokens=64_000)
            draft = out.value
            result.attempts[plan.number] = out.attempts
            result.warnings += later_concept_warnings(draft, ctx)
            chapters.append(assemble_chapter(draft, ctx))
            learn_terms(kb, [(g.key, g.term, g.definition) for g in draft.glossary], lang, plan.number)
            record_chapter(kb, plan.number, draft.summary, plan.introduces, draft.examples_used)
            for g in draft.glossary:
                glossary.setdefault(g.key, GlossaryEntry(term_key=g.key, term=g.term, definition=g.definition,
                                                         lang=lang, first_chapter=plan.number))
        result.book = result.book.model_copy(update={
            "chapters": chapters,
            "glossary": sorted(glossary.values(), key=lambda e: e.term.casefold())})
        return result
