"""IELTS Reading test generator (LLM writes content; code owns structure).

Per passage:

1. A deterministic *plan* fixes question types, counts and word limits.
2. The LLM returns a ``GenSection`` (passage + items) via structured output.
   It never chooses question numbers, ranges, labels or instruction wording.
3. Deterministic content checks (answers present in the passage, word limits,
   option letters valid, headings unique…). Failures are fed back and the
   passage is regenerated (bounded).
4. Code assembles the numbered ``ReadingSection``; the whole test is then
   rendered and validated by the same gate used for export.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from osamu_dazai.domain.common import Provenance
from osamu_dazai.domain.questions import Answer, Option, Question, QuestionGroup, WordLimit
from osamu_dazai.domain.questions import CompletionForm as CF
from osamu_dazai.domain.questions import QuestionType as QT
from osamu_dazai.domain.validation import ValidationResult
from osamu_dazai.ielts import contract as C
from osamu_dazai.ielts.instructions import CHOOSE_WORDS, WORD_LIMIT_PHRASES, instructions, letters
from osamu_dazai.ielts.model import IELTSModule, IELTSReadingTest, Passage, PassageParagraph, ReadingSection
from osamu_dazai.ielts.render import render_test
from osamu_dazai.ielts.validators import IELTSDocumentValidator
from osamu_dazai.pipeline.llm_stage import StageFailed, generate_checked
from osamu_dazai.providers import ProviderRegistry

PROMPT_VERSION = "ielts.reading.v1"
STAGE = "ielts_reading_generator"


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GroupSpec:
    type: QT
    count: int  # answer boxes
    form: CF | None = None
    word_limit: int | None = None  # completion / short answer
    options: int = 0  # size of the shared list (features, endings, compound options)

    @property
    def choose(self) -> int | None:
        return self.count if self.type is QT.MULTIPLE_CHOICE_MULTI else None

    @property
    def items(self) -> int:
        return 1 if self.type is QT.MULTIPLE_CHOICE_MULTI else self.count


@dataclass(frozen=True)
class PassageSpec:
    topic: str
    paragraphs: int
    groups: tuple[GroupSpec, ...]
    words: tuple[int, int] = (650, 900)

    @property
    def count(self) -> int:
        return sum(g.count for g in self.groups)


@dataclass
class ReadingPlan:
    title: str
    passages: list[PassageSpec]
    module: IELTSModule = IELTSModule.ACADEMIC

    @property
    def count(self) -> int:
        return sum(p.count for p in self.passages)


def default_plan(
    topics: tuple[str, str, str],
    title: str = "Academic Reading Practice Test",
    words: tuple[tuple[int, int], tuple[int, int], tuple[int, int]] = ((650, 900), (650, 900), (750, 1000)),
) -> ReadingPlan:
    """3 passages, 40 questions, 11 question formats (13 + 13 + 14)."""
    t1, t2, t3 = topics
    w1, w2, w3 = words
    return ReadingPlan(title=title, passages=[
        PassageSpec(t1, 5, (GroupSpec(QT.MATCHING_HEADINGS, 5, options=8),
                            GroupSpec(QT.MULTIPLE_CHOICE_MULTI, 2, options=5),
                            GroupSpec(QT.TRUE_FALSE_NOT_GIVEN, 6)), words=w1),
        PassageSpec(t2, 5, (GroupSpec(QT.MULTIPLE_CHOICE, 4),
                            GroupSpec(QT.MATCHING_INFORMATION, 4),
                            GroupSpec(QT.MATCHING_FEATURES, 3, options=3),
                            GroupSpec(QT.COMPLETION, 2, form=CF.SENTENCE, word_limit=2)), words=w2),
        PassageSpec(t3, 5, (GroupSpec(QT.YES_NO_NOT_GIVEN, 5),
                            GroupSpec(QT.COMPLETION, 4, form=CF.SUMMARY, word_limit=1),
                            GroupSpec(QT.MATCHING_SENTENCE_ENDINGS, 3, options=5),
                            GroupSpec(QT.SHORT_ANSWER, 2, word_limit=3)), words=w3),
    ])


# ---------------------------------------------------------------------------
# LLM-facing schema (no numbers, no labels, no instructions)
# ---------------------------------------------------------------------------
class GenItem(BaseModel):
    stem: str = Field(description="Statement, question, sentence (with ______ for sentence completion) "
                                  "or sentence beginning. Empty for heading items and summary blanks.")
    options: list[str] = Field(default_factory=list, description="Only for single-answer multiple choice: "
                                                                 "exactly four option texts, without letters.")
    answers: list[str] = Field(description="Accepted answers. Letters (A, B…) for choices/matching, roman "
                                           "numerals for headings, TRUE/FALSE/NOT GIVEN or YES/NO/NOT GIVEN, "
                                           "exact passage words for completion and short answers "
                                           "(alternatives allowed). Compound multiple choice: one letter per box.")
    evidence: str = Field(description="Short quotation from the passage that justifies the answer "
                                      "(empty for NOT GIVEN).")


class GenGroup(BaseModel):
    shared_options: list[str] = Field(default_factory=list,
                                      description="Heading list, list of people/features, sentence endings, or "
                                                  "the options of a compound multiple-choice question. No labels.")
    stem: str = Field(default="", description="Compound multiple choice only: the single question stem.")
    summary_title: str = ""
    summary_text: str = Field(default="", description="Summary completion only: one paragraph with blanks "
                                                      "written as {1}, {2}, … in order.")
    items: list[GenItem]


class GenSection(BaseModel):
    title: str
    paragraphs: list[str] = Field(description="Passage paragraphs in order (labelled A, B, C… by the system).")
    groups: list[GenGroup] = Field(description="One entry per planned question group, in plan order.")


# ---------------------------------------------------------------------------
# Content checks (deterministic)
# ---------------------------------------------------------------------------
def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^\w\s'-]", " ", s.lower()).split())


def _words(s: str) -> int:
    return len([w for w in re.split(r"\s+", s.strip()) if w and not re.fullmatch(r"\d+([.,]\d+)?", w)])


def check_section(gen: GenSection, spec: PassageSpec) -> list[str]:
    problems: list[str] = []
    if len(gen.paragraphs) != spec.paragraphs:
        problems.append(f"passage must have exactly {spec.paragraphs} paragraphs (got {len(gen.paragraphs)})")
    n_words = sum(len(p.split()) for p in gen.paragraphs)
    lo, hi = spec.words
    if not lo * 0.85 <= n_words <= hi * 1.15:
        problems.append(f"passage length {n_words} words is outside {lo}-{hi}")
    if len(gen.groups) != len(spec.groups):
        problems.append(f"expected {len(spec.groups)} question groups, got {len(gen.groups)}")
        return problems
    text = _norm(" ".join(gen.paragraphs))
    para_letters = set(letters(len(gen.paragraphs)))

    for gi, (g, s) in enumerate(zip(gen.groups, spec.groups, strict=True), start=1):
        where = f"group {gi} ({s.type.value})"
        if len(g.items) != s.items:
            problems.append(f"{where}: expected {s.items} items, got {len(g.items)}")
            continue
        opt_letters = set(letters(len(g.shared_options)))
        for k, it in enumerate(g.items, start=1):
            ans = [a.strip() for a in it.answers if a.strip()]
            loc = f"{where} item {k}"
            if not ans:
                problems.append(f"{loc}: no answer")
                continue
            if s.type is QT.MATCHING_HEADINGS:
                if ans[0] not in C.ROMANS[: len(g.shared_options)]:
                    problems.append(f"{loc}: answer {ans[0]!r} is not a heading numeral")
            elif s.type is QT.MULTIPLE_CHOICE:
                if len(it.options) != 4:
                    problems.append(f"{loc}: needs exactly 4 options")
                if ans[0] not in "ABCD" or len(ans) != 1:
                    problems.append(f"{loc}: answer must be one letter A-D")
            elif s.type is QT.MULTIPLE_CHOICE_MULTI:
                if len(set(ans)) != s.count or not set(ans) <= opt_letters:
                    problems.append(f"{loc}: needs {s.count} different letters from {sorted(opt_letters)}")
            elif s.type in (QT.TRUE_FALSE_NOT_GIVEN, QT.YES_NO_NOT_GIVEN):
                allowed = C.TFNG_VALUES if s.type is QT.TRUE_FALSE_NOT_GIVEN else C.YNNG_VALUES
                if ans[0] not in allowed:
                    problems.append(f"{loc}: answer must be one of {sorted(allowed)}")
            elif s.type is QT.MATCHING_INFORMATION:
                if ans[0] not in para_letters:
                    problems.append(f"{loc}: answer must be a paragraph letter {sorted(para_letters)}")
            elif s.type in (QT.MATCHING_FEATURES, QT.MATCHING_SENTENCE_ENDINGS):
                if ans[0] not in opt_letters:
                    problems.append(f"{loc}: answer must be a letter from {sorted(opt_letters)}")
            elif s.type in (QT.COMPLETION, QT.SHORT_ANSWER):
                for a in ans:
                    if _norm(a) not in text:
                        problems.append(f"{loc}: answer {a!r} does not appear in the passage")
                    if s.word_limit and _words(a) > s.word_limit:
                        problems.append(f"{loc}: answer {a!r} exceeds {WORD_LIMIT_PHRASES[s.word_limit]}")
                if s.form is CF.SENTENCE and len(C.find_blanks(it.stem)) != 1:
                    problems.append(f"{loc}: sentence must contain exactly one ______ blank")
                if s.type is QT.SHORT_ANSWER and not it.stem.rstrip().endswith("?"):
                    problems.append(f"{loc}: short-answer question must end with '?'")

        if s.type is QT.MATCHING_HEADINGS:
            if len(g.shared_options) < spec.paragraphs + 2:
                problems.append(f"{where}: give at least {spec.paragraphs + 2} headings (distractors included)")
            if len({it.answers[0] for it in g.items if it.answers}) != len(g.items):
                problems.append(f"{where}: each paragraph needs a different heading")
        if s.type in (QT.MATCHING_FEATURES, QT.MATCHING_SENTENCE_ENDINGS, QT.MULTIPLE_CHOICE_MULTI) \
                and len(g.shared_options) != s.options:
            problems.append(f"{where}: shared list must have exactly {s.options} entries")
        if s.form is CF.SUMMARY:
            found = [int(x) for x in re.findall(r"\{(\d+)\}", g.summary_text)]
            if found != list(range(1, s.count + 1)):
                problems.append(f"{where}: summary_text must contain {{1}}…{{{s.count}}} in order")
        if s.type in (QT.TRUE_FALSE_NOT_GIVEN, QT.YES_NO_NOT_GIVEN):
            used = {it.answers[0] for it in g.items if it.answers}
            if len(used) < 3:
                problems.append(f"{where}: use each of the three answers at least once")
    return problems


# ---------------------------------------------------------------------------
# Assembly (deterministic numbering)
# ---------------------------------------------------------------------------
def assemble_section(gen: GenSection, spec: PassageSpec, number: int, first_q: int) -> ReadingSection:
    paragraph_letters = letters(len(gen.paragraphs))
    passage = Passage(
        number=number, title=gen.title.strip(), provenance=Provenance.AI_GENERATED,
        source_note=f"original passage generated by Osamu Dazai ({PROMPT_VERSION}); requires human review",
        paragraphs=[PassageParagraph(label=paragraph_letters[i], text=p.strip())
                    for i, p in enumerate(gen.paragraphs)],
    )
    groups: list[QuestionGroup] = []
    n = first_q
    for g, s in zip(gen.groups, spec.groups, strict=True):
        a, b = n, n + s.count - 1
        common = {"type": s.type, "range": (a, b),
                  "instructions": instructions(s.type, passage=number, paragraphs=len(gen.paragraphs),
                                               options=len(g.shared_options), choose=s.choose, form=s.form,
                                               word_limit=s.word_limit)}
        wl = WordLimit(max_words=s.word_limit, raw=WORD_LIMIT_PHRASES[s.word_limit]) if s.word_limit else None

        def q(num: int, stem: str, it: GenItem, qtype: QT = s.type, options: list[Option] | None = None) -> Question:
            return Question(number=num, type=qtype, stem=stem, options=options or [],
                            answer=Answer(accepted=[x.strip() for x in it.answers], evidence=it.evidence),
                            provenance=Provenance.AI_GENERATED)

        if s.type is QT.MATCHING_HEADINGS:
            grp = QuestionGroup(**common, list_title="List of Headings",
                                shared_options=[Option(label=C.ROMANS[i], text=t) for i, t in enumerate(g.shared_options)],
                                questions=[q(a + i, f"Paragraph {paragraph_letters[i]}", it)
                                           for i, it in enumerate(g.items)])
        elif s.type is QT.MULTIPLE_CHOICE_MULTI:
            it = g.items[0]
            grp = QuestionGroup(**common, questions=[Question(
                number_range=(a, b), choose=s.count, type=s.type, stem=g.stem or it.stem,
                options=[Option(label=letters(len(g.shared_options))[i], text=t)
                         for i, t in enumerate(g.shared_options)],
                answer=Answer(accepted=sorted(x.strip() for x in it.answers), unordered=True, evidence=it.evidence),
                provenance=Provenance.AI_GENERATED)])
        elif s.type is QT.MULTIPLE_CHOICE:
            grp = QuestionGroup(**common, questions=[
                q(a + i, it.stem, it, options=[Option(label="ABCD"[k], text=t) for k, t in enumerate(it.options)])
                for i, it in enumerate(g.items)])
        elif s.type is QT.MATCHING_INFORMATION:
            grp = QuestionGroup(**common, shared_options=[Option(label=c, text=f"Paragraph {c}")
                                                          for c in paragraph_letters],
                                questions=[q(a + i, it.stem, it) for i, it in enumerate(g.items)])
        elif s.type in (QT.MATCHING_FEATURES, QT.MATCHING_SENTENCE_ENDINGS):
            grp = QuestionGroup(**common, list_title="List" if s.type is QT.MATCHING_FEATURES else "",
                                shared_options=[Option(label=letters(len(g.shared_options))[i], text=t)
                                                for i, t in enumerate(g.shared_options)],
                                questions=[q(a + i, it.stem, it) for i, it in enumerate(g.items)])
        elif s.form is CF.SUMMARY:
            body = re.sub(r"\{(\d+)\}", lambda m: "{" + str(a + int(m.group(1)) - 1) + "}", g.summary_text)
            grp = QuestionGroup(**common, completion_form=CF.SUMMARY, word_limit=wl, list_title=g.summary_title,
                                body=[body], questions=[q(a + i, "", it) for i, it in enumerate(g.items)])
        else:  # sentence completion, short answer
            grp = QuestionGroup(**common, completion_form=s.form, word_limit=wl,
                                questions=[q(a + i, it.stem, it) for i, it in enumerate(g.items)])
        groups.append(grp)
        n = b + 1
    return ReadingSection(passage=passage, groups=groups)


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------
SYSTEM = """You write original IELTS Academic Reading material for an educational publisher.

Rules:
- Write an ORIGINAL passage. Never reproduce or paraphrase published IELTS or Cambridge test material.
- Academic register, factual and neutral, suitable for an international audience. Do not invent statistics,
  studies, quotations or named researchers presented as real; if people are needed for matching questions,
  use clearly fictional names.
- Every answer must be fully determined by the passage. Completion and short answers must be copied exactly
  from the passage and respect the word limit. NOT GIVEN statements must be plausible but unaddressed.
- Distractors must be plausible but clearly wrong according to the passage.
- Do not number anything and do not add letters to options; the system adds numbering and labels."""


def _describe(spec: PassageSpec) -> str:
    lines = [f"Topic: {spec.topic}",
             f"Passage: a title and exactly {spec.paragraphs} paragraphs, {spec.words[0]}-{spec.words[1]} words.",
             "Question groups, in this order:"]
    for i, g in enumerate(spec.groups, start=1):
        t = g.type
        if t is QT.MATCHING_HEADINGS:
            d = (f"Matching headings: shared_options = {g.options} headings (one per paragraph plus distractors); "
                 f"items = {g.count} (one per paragraph, in order, stem empty); answer = roman numeral of the "
                 "heading (i = first heading).")
        elif t is QT.MULTIPLE_CHOICE_MULTI:
            d = (f"Choose {CHOOSE_WORDS[g.count]} letters: stem = one question; shared_options = {g.options} "
                 f"statements; items = 1 with answers = the {g.count} correct letters.")
        elif t is QT.MULTIPLE_CHOICE:
            d = f"Multiple choice: {g.count} items, each with a question stem, 4 options and one letter answer."
        elif t is QT.TRUE_FALSE_NOT_GIVEN:
            d = f"TRUE/FALSE/NOT GIVEN: {g.count} factual statements; use all three answers."
        elif t is QT.YES_NO_NOT_GIVEN:
            d = (f"YES/NO/NOT GIVEN: {g.count} statements about the WRITER'S views (the passage must express "
                 "opinions); use all three answers.")
        elif t is QT.MATCHING_INFORMATION:
            d = f"Which paragraph contains…: {g.count} items naming specific information; answer = paragraph letter."
        elif t is QT.MATCHING_FEATURES:
            d = (f"Matching features: shared_options = {g.options} fictional people or named things from the passage; "
                 f"{g.count} statements; answer = letter of the list entry.")
        elif t is QT.MATCHING_SENTENCE_ENDINGS:
            d = (f"Sentence endings: {g.count} sentence beginnings as stems; shared_options = {g.options} endings "
                 "(including distractors); answer = letter of the ending.")
        elif g.form is CF.SUMMARY:
            d = (f"Summary completion: summary_title and summary_text with blanks {{1}}…{{{g.count}}}; "
                 f"{g.count} items with empty stems; answers {WORD_LIMIT_PHRASES[g.word_limit or 1]} from the passage.")
        elif g.form is CF.SENTENCE:
            d = (f"Sentence completion: {g.count} sentences each containing one ______ blank; answers "
                 f"{WORD_LIMIT_PHRASES[g.word_limit or 2]} copied from the passage.")
        else:
            d = (f"Short answer: {g.count} questions ending with '?'; answers "
                 f"{WORD_LIMIT_PHRASES[g.word_limit or 3]} copied from the passage.")
        lines.append(f"{i}. {d}")
    return "\n".join(lines)


class GenerationFailed(StageFailed):
    def __init__(self, passage: int, problems: list[str]) -> None:
        super().__init__(f"{STAGE} (passage {passage})", problems)
        self.passage = passage


@dataclass
class GenerationReport:
    test: IELTSReadingTest
    validation: ValidationResult
    attempts: dict[int, int] = field(default_factory=dict)  # passage -> LLM attempts


class IELTSReadingGenerator:
    def __init__(self, registry: ProviderRegistry, *, max_attempts: int = 3) -> None:
        self.registry = registry
        self.max_attempts = max_attempts

    async def _section(self, spec: PassageSpec, number: int, first_q: int,
                       report: GenerationReport) -> ReadingSection:
        try:
            result = await generate_checked(
                self.registry, STAGE, system=SYSTEM, prompt=_describe(spec), schema=GenSection,
                check=lambda g: check_section(g, spec), prompt_version=PROMPT_VERSION,
                max_attempts=self.max_attempts,
            )
        except StageFailed as e:
            report.attempts[number] = self.max_attempts
            raise GenerationFailed(number, e.problems) from e
        report.attempts[number] = result.attempts
        return assemble_section(result.value, spec, number, first_q)

    async def generate(self, plan: ReadingPlan) -> GenerationReport:
        report = GenerationReport(test=None, validation=None)  # type: ignore[arg-type]
        sections = []
        first = 1
        for k, spec in enumerate(plan.passages, start=1):
            sections.append(await self._section(spec, k, first, report))
            first += spec.count
        report.test = IELTSReadingTest(title=plan.title, module=plan.module, sections=sections)
        report.validation = IELTSDocumentValidator().validate_lines(render_test(report.test), target_id=report.test.id)
        return report
