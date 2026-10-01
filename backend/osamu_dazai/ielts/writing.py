"""IELTS Writing (spec §15): Task 1 (Academic chart/process or General Training letter) and Task 2.

One checked LLM stage writes the tasks, band-targeted sample responses with
per-criterion scores and commentary, and teacher feedback. Deterministic checks:

* Academic Task 1 data is a structured chart/table/process spec rendered by the
  visual system — and sample answers may only quote figures that exist in it
  (no invented numbers);
* General Training Task 1 letters have exactly three bullet points;
* samples span at least two bands; criterion scores are consistent with the
  target band; length rules (≥150 / ≥250 words) hold for band ≥6 samples, and
  under-length samples are not given a high Task Achievement/Response score;
* every sample has teacher feedback (strengths and improvements).

Standard rubric lines (time, minimum words) are added by code, not the model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from osamu_dazai.domain.common import Lang, Model, id_field
from osamu_dazai.domain.knowledge import KnowledgeBase
from osamu_dazai.ielts.bands import WRITING_T1, WRITING_T2, CriterionScore, check_scores, estimated_band
from osamu_dazai.pipeline.llm_stage import generate_checked
from osamu_dazai.providers import ProviderRegistry
from osamu_dazai.visuals.builder import check_draft as check_visual
from osamu_dazai.visuals.specs import VisualDraft, renderer_for
from osamu_dazai.visuals.svg import RenderedSvg, render_svg

STAGE = "ielts_writing_generator"
PROMPT_VERSION = "ielts.writing.v1"
Module_ = Literal["academic", "general_training"]
Task2Type = Literal["opinion", "discussion", "problem_solution", "advantages_disadvantages", "two_part"]
_NUM = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?(?![\w])")


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
class Feedback(Model):
    strengths: list[str]
    improvements: list[str]


class SampleResponse(Model):
    target_band: float
    text: str
    scores: list[CriterionScore]
    examiner_comment: str
    feedback: Feedback

    @property
    def words(self) -> int:
        return len(self.text.split())

    @property
    def estimated_band(self) -> float:
        return estimated_band(self.scores)


class WritingTask(Model):
    number: Literal[1, 2]
    module: Module_
    prompt: str  # the task wording (situation / question)
    bullets: list[str] = Field(default_factory=list)  # GT letter bullet points
    visual: VisualDraft | None = None  # Academic Task 1 data
    task2_type: Task2Type | None = None
    minutes: int
    min_words: int
    samples: list[SampleResponse]


class WritingSet(Model):
    id: str = id_field("iwr")
    module: Module_
    task1: WritingTask
    task2: WritingTask


# ---------------------------------------------------------------------------
# LLM-facing draft
# ---------------------------------------------------------------------------
class GenScore(BaseModel):
    criterion: str
    band: int = Field(ge=0, le=9)
    comment: str


class GenSample(BaseModel):
    target_band: float
    text: str
    scores: list[GenScore]
    examiner_comment: str
    strengths: list[str]
    improvements: list[str]


class GenTask1(BaseModel):
    prompt: str = Field(description="Academic: what the visual shows ('The chart below shows …'); "
                                    "GT: the situation for the letter")
    bullets: list[str] = Field(default_factory=list, description="General Training only: exactly 3 points")
    visual: VisualDraft | None = Field(default=None, description="Academic only: chart, table (comparison) or "
                                                                 "process diagram with complete data")
    samples: list[GenSample]


class GenTask2(BaseModel):
    task_type: Task2Type
    prompt: str = Field(description="the statement/question the candidate responds to")
    samples: list[GenSample]


class GenWriting(BaseModel):
    task1: GenTask1
    task2: GenTask2


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def _numbers(text: str) -> set[float]:
    return {float(m.group(0).replace(",", "")) for m in _NUM.finditer(text)}


def visual_numbers(v: VisualDraft) -> set[float]:
    """Every figure a sample may legitimately quote: data values, numeric labels, totals and differences."""
    vals = {float(x) for s in v.series for x in s.values}
    for label in [*v.categories, *v.columns, *v.criteria, v.title, *(c for r in v.cells for c in r),
                  *(n.label for n in v.nodes), *(ev.date for ev in v.events)]:
        vals |= _numbers(label)
    derived = {abs(a - b) for a in vals for b in vals} | {a + b for a in vals for b in vals}
    for s in v.series:
        derived.add(sum(s.values))
    return vals | {round(x, 2) for x in derived}


def _check_samples(samples: list[GenSample], criteria: list[str], min_words: int, task: str) -> list[str]:
    p = []
    targets = sorted({s.target_band for s in samples})
    if len(targets) < 2:
        p.append(f"{task}: give samples at two or more different band levels")
    for s in samples:
        where = f"{task} band-{s.target_band:g} sample"
        if s.target_band * 2 != int(s.target_band * 2) or not 3 <= s.target_band <= 9:
            p.append(f"{where}: target band must be 3-9 in half-band steps")
        scores = [CriterionScore(criterion=x.criterion, band=x.band, comment=x.comment) for x in s.scores]
        p += check_scores(scores, criteria, s.target_band, where)
        n = len(s.text.split())
        if n < min_words:
            if s.target_band >= 6:
                p.append(f"{where}: {n} words — a band-{s.target_band:g} response must have at least {min_words}")
            if s.scores and s.scores[0].criterion == criteria[0] and s.scores[0].band > 5:
                p.append(f"{where}: an under-length response cannot score above 5 for {criteria[0]}")
        if not s.strengths or not s.improvements:
            p.append(f"{where}: teacher feedback needs strengths and improvements")
        if not s.examiner_comment.strip():
            p.append(f"{where}: add an overall commentary")
    return p


def check_writing(d: GenWriting, module: Module_) -> list[str]:
    p: list[str] = []
    t1 = d.task1
    if module == "academic":
        if t1.visual is None:
            p.append("Academic Task 1 needs a visual (chart, table or process)")
        else:
            if renderer_for(t1.visual) not in ("chart", "comparison", "flow", "timeline"):
                p.append("Academic Task 1 visual must be a chart, table, process diagram or timeline")
            p += [f"Task 1 visual: {x}" for x in check_visual(t1.visual, Lang.EN, KnowledgeBase(project_id="ielts"))]
            allowed = visual_numbers(t1.visual) | _numbers(t1.prompt) | {float(n) for n in range(13)}  # counting
            for s in t1.samples:
                extra = sorted(_numbers(s.text) - allowed)
                if extra:
                    p.append(f"Task 1 band-{s.target_band:g} sample quotes figures not in the visual: "
                             f"{[f'{x:g}' for x in extra]}")
        if t1.bullets:
            p.append("Academic Task 1 has no bullet points")
    else:
        if len(t1.bullets) != 3:
            p.append("General Training Task 1 must give exactly 3 bullet points")
        if t1.visual is not None:
            p.append("General Training Task 1 is a letter, not a visual")
    p += _check_samples(t1.samples, WRITING_T1, 150, "Task 1")
    p += _check_samples(d.task2.samples, WRITING_T2, 250, "Task 2")
    if not d.task2.prompt.strip():
        p.append("Task 2 needs a prompt")
    return p


def _sample(s: GenSample) -> SampleResponse:
    return SampleResponse(target_band=s.target_band, text=s.text, examiner_comment=s.examiner_comment,
                          scores=[CriterionScore(criterion=x.criterion, band=x.band, comment=x.comment) for x in s.scores],
                          feedback=Feedback(strengths=s.strengths, improvements=s.improvements))


def assemble(d: GenWriting, module: Module_) -> WritingSet:
    return WritingSet(module=module, task1=WritingTask(
        number=1, module=module, prompt=d.task1.prompt, bullets=d.task1.bullets, visual=d.task1.visual,
        minutes=20, min_words=150, samples=[_sample(s) for s in d.task1.samples]),
        task2=WritingTask(number=2, module=module, prompt=d.task2.prompt, task2_type=d.task2.task_type, minutes=40,
                          min_words=250, samples=[_sample(s) for s in d.task2.samples]))


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def task1_figure(ws: WritingSet) -> RenderedSvg | None:
    v = ws.task1.visual
    return render_svg(v, renderer_for(v)) if v else None


def render_tasks(ws: WritingSet) -> str:
    t1, t2 = ws.task1, ws.task2
    out = ["# WRITING", "", "## WRITING TASK 1", "",
           f"You should spend about {t1.minutes} minutes on this task.", ""]
    if ws.module == "academic":
        out += [t1.prompt, "", "Summarise the information by selecting and reporting the main features, and make "
                "comparisons where relevant.", "", "*[Figure: Task 1 visual]*", ""]
    else:
        out += [t1.prompt, "", "In your letter", "", *(f"- {b}" for b in t1.bullets), "",
                "You do NOT need to write any addresses.", "", "Begin your letter as follows:", "", "Dear …………,", ""]
    out += [f"Write at least {t1.min_words} words.", "", "## WRITING TASK 2", "",
            f"You should spend about {t2.minutes} minutes on this task.", "",
            "Write about the following topic:", "", f"> {t2.prompt}", "",
            "Give reasons for your answer and include any relevant examples from your own knowledge or experience.",
            "", f"Write at least {t2.min_words} words.", ""]
    return "\n".join(out).rstrip() + "\n"


def render_samples(ws: WritingSet) -> str:
    """Teacher material: band-targeted samples with estimated scores and feedback (not official scores)."""
    out = ["# Writing — sample responses and feedback", "",
           "_Bands are estimates for teaching, based on the four public criteria; not official IELTS scores._", ""]
    for task in (ws.task1, ws.task2):
        for s in sorted(task.samples, key=lambda x: x.target_band):
            out += [f"## Task {task.number} — sample at band {s.target_band:g} ({s.words} words)", "", s.text, "",
                    "| Criterion | Band | Comment |", "|---|---|---|",
                    *(f"| {c.criterion} | {c.band} | {c.comment} |" for c in s.scores),
                    f"| **Estimated band** | **{s.estimated_band:g}** | |", "",
                    f"**Examiner-style comment:** {s.examiner_comment}", "",
                    "**Strengths**", *(f"- {x}" for x in s.feedback.strengths), "",
                    "**To improve**", *(f"- {x}" for x in s.feedback.improvements), ""]
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
SYSTEM = """You write ORIGINAL IELTS Writing practice material (never reproduce published tasks or band
descriptors). Academic Task 1 visuals contain complete, internally consistent data, marked as illustrative.
Sample responses are realistic for their target band — including the typical weaknesses of that band — and
Task 1 samples quote only figures that are in the visual. Score each sample on the four criteria with whole
bands and a short comment in your own words; give practical teacher feedback (strengths, improvements)."""


@dataclass
class WritingSpec:
    module: Module_
    task1_topic: str
    task2_topic: str
    task2_type: Task2Type = "opinion"
    sample_bands: tuple[float, ...] = (5.5, 7.5)


def _describe(spec: WritingSpec) -> str:
    t1 = ("Academic Task 1: a visual (bar/line/pie chart, table as 'comparison', or process as 'flowchart') about "
          f"{spec.task1_topic}; data_provenance 'illustrative'." if spec.module == "academic" else
          f"General Training Task 1: a letter situation about {spec.task1_topic} with exactly 3 bullet points.")
    bands = ", ".join(f"{b:g}" for b in spec.sample_bands)
    return "\n".join([
        t1,
        f"Task 2 ({spec.task2_type.replace('_', '/')} essay) on: {spec.task2_topic}.",
        f"For EACH task, one sample response at each of these bands: {bands}.",
        f"Task 1 criteria, in order: {WRITING_T1}.", f"Task 2 criteria, in order: {WRITING_T2}.",
    ])


class IELTSWritingGenerator:
    def __init__(self, registry: ProviderRegistry, *, max_attempts: int = 3) -> None:
        self.registry = registry
        self.max_attempts = max_attempts

    async def generate(self, spec: WritingSpec) -> tuple[WritingSet, int]:
        def check(d: GenWriting) -> list[str]:
            p = check_writing(d, spec.module)
            for task, name in ((d.task1, "Task 1"), (d.task2, "Task 2")):
                got = sorted(s.target_band for s in task.samples)
                if got != sorted(spec.sample_bands):
                    p.append(f"{name}: give samples at bands {list(spec.sample_bands)} (got {got})")
            if d.task2.task_type != spec.task2_type:
                p.append(f"Task 2 must be a {spec.task2_type} essay")
            return p

        out = await generate_checked(self.registry, STAGE, system=SYSTEM, prompt=_describe(spec), schema=GenWriting,
                                     check=check, prompt_version=PROMPT_VERSION, max_attempts=self.max_attempts,
                                     max_tokens=48_000)
        return assemble(out.value, spec.module), out.attempts
