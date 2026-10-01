"""IELTS Listening (spec §15): audio scripts + question papers.

Each of the four parts is one checked LLM stage producing a transcript and its
questions. Deterministic checks enforce what makes Listening items fair:

* every answer is actually *heard*: completion answers occur verbatim in the
  transcript (and respect the word limit); choice/matching/map answers carry
  an evidence quote that occurs verbatim;
* answers are heard in question order (positions in the script never go back);
* part shape: parts 1 and 3 are dialogues, parts 2 and 4 monologues; script length.

The question paper reuses the Reading line contract with ``PART N`` sections,
so numbering, glued-number and answer-key validation (and DOCX export gating)
are shared. Audio is produced from the script by a TTS provider later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from osamu_dazai.domain.common import Model, Provenance, id_field
from osamu_dazai.domain.questions import Answer, CompletionForm, Option, Question, QuestionGroup, QuestionType, WordLimit
from osamu_dazai.domain.validation import ValidationResult
from osamu_dazai.ielts import contract as C
from osamu_dazai.ielts.instructions import letters, listening_instructions
from osamu_dazai.ielts.lines import Line
from osamu_dazai.ielts.render import _answer_line, render_group
from osamu_dazai.ielts.validators import IELTSDocumentValidator
from osamu_dazai.pipeline.llm_stage import generate_checked
from osamu_dazai.providers import ProviderRegistry

STAGE = "ielts_listening_generator"
PROMPT_VERSION = "ielts.listening.v1"
QT, CF = QuestionType, CompletionForm
GroupKind = Literal["form", "note", "table", "sentence", "mc", "map", "matching"]


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
class Turn(Model):
    speaker: str
    text: str


class PlanItem(Model):
    """A box on a map / floor plan (grid units 0–12). Letters mark answer locations."""

    label: str
    x: int = Field(ge=0, le=12)
    y: int = Field(ge=0, le=12)
    w: int = Field(ge=1, le=12)
    h: int = Field(ge=1, le=12)


class ListeningPart(Model):
    number: int = Field(ge=1, le=4)
    context: str  # the line under PART N, e.g. "A conversation between a receptionist and a caller."
    speakers: list[str]
    transcript: list[Turn]
    groups: list[QuestionGroup]
    plan: list[PlanItem] = Field(default_factory=list)
    plan_title: str = ""


class IELTSListeningTest(Model):
    id: str = id_field("ilt")
    title: str
    parts: list[ListeningPart] = Field(min_length=1, max_length=4)

    def question_count(self) -> int:
        return sum(len(g.numbers()) for p in self.parts for g in p.groups)


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LGroupSpec:
    kind: GroupKind
    count: int
    word_limit: str = ""  # e.g. "ONE WORD AND/OR A NUMBER"
    options: int = 0  # MC options per question / matching list size / plan letters


@dataclass(frozen=True)
class PartSpec:
    number: int
    topic: str
    dialogue: bool
    groups: tuple[LGroupSpec, ...]
    words: tuple[int, int] = (450, 900)

    @property
    def count(self) -> int:
        return sum(g.count for g in self.groups)


def default_plan(topics: tuple[str, str, str, str]) -> list[PartSpec]:
    """Standard 4 × 10 questions."""
    return [
        PartSpec(1, topics[0], True, (LGroupSpec("form", 6, "ONE WORD AND/OR A NUMBER"),
                                      LGroupSpec("note", 4, "ONE WORD AND/OR A NUMBER"))),
        PartSpec(2, topics[1], False, (LGroupSpec("mc", 4, options=3), LGroupSpec("map", 6, options=8))),
        PartSpec(3, topics[2], True, (LGroupSpec("mc", 5, options=3), LGroupSpec("matching", 5, options=6))),
        PartSpec(4, topics[3], False, (LGroupSpec("note", 10, "ONE WORD ONLY"),), words=(600, 1000)),
    ]


INLINE = {"form": CF.FORM, "note": CF.NOTE, "table": CF.TABLE}
LIMITS = {"ONE WORD ONLY": (1, False), "ONE WORD AND/OR A NUMBER": (1, True),
          "NO MORE THAN TWO WORDS": (2, False), "NO MORE THAN TWO WORDS AND/OR A NUMBER": (2, True),
          "NO MORE THAN THREE WORDS": (3, False)}


# ---------------------------------------------------------------------------
# LLM-facing draft
# ---------------------------------------------------------------------------
class GenTurn(BaseModel):
    speaker: str
    text: str


class GenItem(BaseModel):
    stem: str = Field(default="", description="question / statement / place name; empty for form & note blanks")
    options: list[str] = Field(default_factory=list, description="multiple choice only: the options, no letters")
    answers: list[str] = Field(description="exact words heard (completion) or the letter (choices, matching, plan)")
    evidence: str = Field(default="", description="for choice/matching/plan items: the exact transcript words "
                                                  "that give the answer")


class GenGroup(BaseModel):
    title: str = Field(default="", description="form / notes heading")
    lines: list[str] = Field(default_factory=list, description="form/note lines; blanks written as {1}, {2}… in order")
    shared_options: list[str] = Field(default_factory=list, description="matching list, no letters")
    items: list[GenItem]


class GenPlanItem(BaseModel):
    label: str = Field(description="a letter (A, B…) for answer locations, or a name for landmarks")
    x: int
    y: int
    w: int
    h: int


class GenPart(BaseModel):
    context: str = Field(description="one sentence describing the situation and speakers")
    speakers: list[str]
    transcript: list[GenTurn]
    groups: list[GenGroup]
    plan_title: str = ""
    plan: list[GenPlanItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def _norm(s: str) -> str:
    s = s.lower().replace("’", "'")
    return " ".join(re.sub(r"[^\w\s'@./-]", " ", s).split())


def _words(s: str) -> list[str]:
    return [w for w in s.split() if w]


def _find(haystack: str, needle: str, start: int) -> int:
    """Position of ``needle`` at a word boundary at or after ``start`` (−1 if absent)."""
    m = re.compile(rf"(?<![\w]){re.escape(needle)}(?![\w])").search(haystack, start)
    return m.start() if m else -1


def check_part(d: GenPart, spec: PartSpec) -> list[str]:
    p: list[str] = []
    if spec.dialogue and len(set(d.speakers)) < 2:
        p.append(f"part {spec.number} must be a conversation between at least two speakers")
    if not spec.dialogue and len(set(d.speakers)) != 1:
        p.append(f"part {spec.number} must be a monologue (one speaker)")
    if bad := sorted({t.speaker for t in d.transcript} - set(d.speakers)):
        p.append(f"transcript uses speakers not listed: {bad}")
    script = _norm(" ".join(t.text for t in d.transcript))
    n_words = len(_words(script))
    lo, hi = spec.words
    if not lo <= n_words <= hi:
        p.append(f"transcript has {n_words} words; it must be {lo}-{hi}")
    if len(d.groups) != len(spec.groups):
        return [*p, f"expected {len(spec.groups)} question groups, got {len(d.groups)}"]

    pos, number = 0, 0
    for gi, (g, s) in enumerate(zip(d.groups, spec.groups, strict=True), start=1):
        w = f"group {gi} ({s.kind})"
        if len(g.items) != s.count:
            p.append(f"{w}: expected {s.count} items, got {len(g.items)}")
            continue
        if s.kind in INLINE:
            found = [int(x) for x in re.findall(r"\{(\d+)\}", "\n".join(g.lines))]
            if found != list(range(1, s.count + 1)):
                p.append(f"{w}: lines must contain blanks {{1}}…{{{s.count}}} in order")
        if s.kind == "mc":
            for k, it in enumerate(g.items, start=1):
                if len(it.options) != s.options:
                    p.append(f"{w} item {k}: give exactly {s.options} options")
        if s.kind == "matching" and len(g.shared_options) != s.options:
            p.append(f"{w}: the list must have exactly {s.options} entries")
        if s.kind == "map":
            plan_letters = {pi.label for pi in d.plan if len(pi.label) == 1 and pi.label.isupper()}
            if plan_letters != set(letters(s.options)):
                p.append(f"{w}: the plan must show letters A-{letters(s.options)[-1]} (got {sorted(plan_letters)})")
            if any(pi.x + pi.w > 12 or pi.y + pi.h > 12 for pi in d.plan):
                p.append(f"{w}: plan boxes must fit inside the 12 × 12 grid")
        for k, it in enumerate(g.items, start=1):
            number += 1
            loc = f"question {number} ({w} item {k})"
            ans = [a.strip() for a in it.answers if a.strip()]
            if not ans:
                p.append(f"{loc}: no answer")
                continue
            if s.kind in ("mc", "matching", "map"):
                n_opts = s.options if s.kind != "mc" else len(it.options)
                if len(ans) != 1 or ans[0] not in letters(n_opts):
                    p.append(f"{loc}: answer must be one letter A-{letters(n_opts)[-1]}")
                anchor = _norm(it.evidence)
                if not anchor:
                    p.append(f"{loc}: quote the transcript words that give the answer (evidence)")
                    continue
            else:
                limit_words, allow_number = LIMITS.get(s.word_limit, (3, True))
                for a in ans:
                    counted = [x for x in _words(a) if not (allow_number and re.fullmatch(r"[\d.,:/-]+", x))]
                    if len(counted) > limit_words or (not allow_number and re.search(r"\d", a)):
                        p.append(f"{loc}: answer '{a}' breaks the limit {s.word_limit}")
                anchor = _norm(ans[0])
            at = _find(script, anchor, pos)
            if at >= 0:
                pos = at + 1
            elif _find(script, anchor, 0) >= 0:
                p.append(f"{loc}: '{anchor}' is heard before the previous answer — answers must come in the order "
                         "they are heard")
            else:
                p.append(f"{loc}: '{anchor}' is never heard in the transcript")
    return p


# ---------------------------------------------------------------------------
# Assembly + rendering
# ---------------------------------------------------------------------------
def assemble_part(d: GenPart, spec: PartSpec, first_q: int) -> ListeningPart:
    groups, n = [], first_q
    for g, s in zip(d.groups, spec.groups, strict=True):
        a, b = n, n + s.count - 1
        opts = s.options if s.kind != "mc" else len(g.items[0].options)
        common = {"range": (a, b), "instructions": listening_instructions(s.kind, first=a, last=b, options=opts,
                                                                         word_limit=s.word_limit)}

        def q(num: int, it: GenItem, qtype: QuestionType, **kw) -> Question:  # noqa: ANN003
            return Question(number=num, type=qtype, stem=it.stem,
                            answer=Answer(accepted=[x.strip() for x in it.answers], evidence=it.evidence),
                            provenance=Provenance.AI_GENERATED, **kw)

        if s.kind in INLINE:
            body = [re.sub(r"\{(\d+)\}", lambda m: "{" + str(a + int(m.group(1)) - 1) + "}", ln) for ln in g.lines]
            limit_words, allow_number = LIMITS.get(s.word_limit, (3, True))
            grp = QuestionGroup(type=QT.COMPLETION, completion_form=INLINE[s.kind], list_title=g.title, body=body,
                                word_limit=WordLimit(max_words=limit_words, allow_number=allow_number, raw=s.word_limit),
                                questions=[q(a + i, it.model_copy(update={"stem": ""}), QT.COMPLETION)
                                           for i, it in enumerate(g.items)], **common)
        elif s.kind == "sentence":
            grp = QuestionGroup(type=QT.COMPLETION, completion_form=CF.SENTENCE, questions=[
                q(a + i, it, QT.COMPLETION) for i, it in enumerate(g.items)], **common)
        elif s.kind == "mc":
            grp = QuestionGroup(type=QT.MULTIPLE_CHOICE, questions=[
                q(a + i, it, QT.MULTIPLE_CHOICE, options=[Option(label=letters(len(it.options))[k], text=t)
                                                          for k, t in enumerate(it.options)])
                for i, it in enumerate(g.items)], **common)
        elif s.kind == "map":
            grp = QuestionGroup(type=QT.LABELLING, questions=[q(a + i, it, QT.LABELLING)
                                                             for i, it in enumerate(g.items)], **common)
        else:  # matching
            grp = QuestionGroup(type=QT.MATCHING_FEATURES, list_title="List",
                                shared_options=[Option(label=letters(len(g.shared_options))[k], text=t)
                                                for k, t in enumerate(g.shared_options)],
                                questions=[q(a + i, it, QT.MATCHING_FEATURES) for i, it in enumerate(g.items)],
                                **common)
        groups.append(grp)
        n = b + 1
    return ListeningPart(number=spec.number, context=d.context.strip(), speakers=d.speakers,
                         transcript=[Turn(speaker=t.speaker, text=t.text) for t in d.transcript], groups=groups,
                         plan=[PlanItem(**x.model_dump()) for x in d.plan], plan_title=d.plan_title)


def render_paper(test: IELTSListeningTest, *, include_answer_key: bool = True) -> list[Line]:
    out: list[Line] = []
    for part in test.parts:
        out += [Line(f"PART {part.number}", bold=True), Line(part.context)]
        for g in part.groups:
            out += render_group(g)
    if include_answer_key:
        out.append(Line("ANSWER KEY", bold=True))
        qs = sorted((q for p in test.parts for g in p.groups for q in g.questions), key=lambda q: q.numbers()[0])
        out += [_answer_line(q) for q in qs]
    return out


def render_transcript(test: IELTSListeningTest) -> str:
    out = [f"# {test.title} — Audio script", ""]
    for part in test.parts:
        out += [f"## PART {part.number}", "", f"*{part.context}*", ""]
        out += [f"**{t.speaker}:** {t.text}" for t in part.transcript] + [""]
    return "\n".join(out).rstrip() + "\n"


def validate_paper(test: IELTSListeningTest) -> ValidationResult:
    return IELTSDocumentValidator(C.LISTENING).validate_lines(render_paper(test), target_id=test.id)


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
SYSTEM = """You write ORIGINAL IELTS Listening material (never reproduce published tests). Write a natural audio
script for the situation and questions that are answered in the order they are heard. Completion answers are
the exact words spoken (names may be spelled out, e.g. 'That's S-M-I-T-H'); include realistic distractors
(corrections, changed plans) but make the final answer unambiguous. For choices, matching and plan labelling,
quote the exact transcript words that give the answer as evidence. Do not number anything; the system does."""

KIND_TEXT = {
    "form": "Form completion: title + form lines with blanks {1}…{n} (e.g. 'Surname: {1}'); items have empty stems.",
    "note": "Note completion: title + note lines with blanks {1}…{n}; items have empty stems.",
    "table": "Table completion: lines are table rows ('cell | cell {1} | cell'); items have empty stems.",
    "sentence": "Sentence completion: each stem contains one ______ blank.",
    "mc": "Multiple choice: question stem + options per item; answer = letter.",
    "map": "Plan labelling: a plan of boxes on a 12×12 grid with letters for answer places and names for landmarks; "
           "each item stem names a place; answer = its letter on the plan.",
    "matching": "Matching: a list of options (shared_options) and statements as stems; answer = letter.",
}


def _describe(spec: PartSpec) -> str:
    who = "a conversation between two (or more) speakers" if spec.dialogue else "a monologue by one speaker"
    lines = [f"PART {spec.number}: {who} about: {spec.topic}.",
             f"Transcript length: {spec.words[0]}-{spec.words[1]} words.", "Question groups in order:"]
    for i, g in enumerate(spec.groups, start=1):
        extra = f" Word limit: {g.word_limit}." if g.word_limit else ""
        if g.kind == "mc":
            extra += f" {g.options} options each."
        elif g.kind in ("map", "matching"):
            extra += f" {g.options} letters/options."
        lines.append(f"{i}. {g.count} items — {KIND_TEXT[g.kind]}{extra}")
    return "\n".join(lines)


@dataclass
class ListeningReport:
    test: IELTSListeningTest
    validation: ValidationResult
    attempts: dict[int, int] = field(default_factory=dict)


class IELTSListeningGenerator:
    def __init__(self, registry: ProviderRegistry, *, max_attempts: int = 3) -> None:
        self.registry = registry
        self.max_attempts = max_attempts

    async def generate(self, plan: list[PartSpec], title: str = "Listening Practice Test") -> ListeningReport:
        parts, attempts, first = [], {}, 1
        for spec in plan:
            out = await generate_checked(
                self.registry, STAGE, system=SYSTEM, prompt=_describe(spec), schema=GenPart,
                check=lambda d, spec=spec: check_part(d, spec), prompt_version=PROMPT_VERSION,
                max_attempts=self.max_attempts, max_tokens=32_000)
            parts.append(assemble_part(out.value, spec, first))
            attempts[spec.number] = out.attempts
            first += spec.count
        test = IELTSListeningTest(title=title, parts=parts)
        return ListeningReport(test=test, validation=validate_paper(test), attempts=attempts)
