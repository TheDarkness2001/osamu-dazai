"""IELTS Speaking (spec §15): Parts 1–3, model answers and evaluation.

One checked LLM stage writes a full speaking test. Deterministic checks:

* Part 1: 2–3 familiar topics, 3–5 questions each, all real questions;
* Part 2: a cue card 'Describe …', 3–4 'You should say' prompts, an
  'and explain …' line, and 1–2 rounding-off questions;
* Part 3: 4–6 discussion questions;
* model answers answer questions that exist, at realistic lengths
  (Part 1 ≈ 20–70 words, Part 2 ≈ 180–320 ≈ 2 minutes, Part 3 ≈ 50–150);
* each model answer is evaluated on the four criteria, consistent with its
  target band. Pronunciation cannot be judged from text, so that comment must
  say what to listen for rather than claim a judgement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from osamu_dazai.domain.common import Model, id_field
from osamu_dazai.ielts.bands import SPEAKING, CriterionScore, check_scores
from osamu_dazai.pipeline.llm_stage import generate_checked
from osamu_dazai.providers import ProviderRegistry

STAGE = "ielts_speaking_generator"
PROMPT_VERSION = "ielts.speaking.v1"
LENGTHS = {1: (20, 70), 2: (180, 320), 3: (50, 150)}


class Part1Topic(Model):
    topic: str
    questions: list[str]


class CueCard(Model):
    task: str  # "Describe a …"
    prompts: list[str]  # "You should say:" items
    explain: str  # "and explain …"
    rounding_off: list[str]


class ModelAnswer(Model):
    part: Literal[1, 2, 3]
    question: str
    target_band: float
    answer: str
    scores: list[CriterionScore]


class SpeakingTest(Model):
    id: str = id_field("isp")
    part1: list[Part1Topic]
    part2: CueCard
    part3: list[str]
    model_answers: list[ModelAnswer]


class GenScore(BaseModel):
    criterion: str
    band: int = Field(ge=0, le=9)
    comment: str


class GenAnswer(BaseModel):
    part: Literal[1, 2, 3]
    question: str = Field(description="copy the question exactly (for Part 2: the cue card task line)")
    target_band: float
    answer: str
    scores: list[GenScore]


class GenSpeaking(BaseModel):
    part1: list[Part1Topic]
    part2: CueCard
    part3: list[str]
    model_answers: list[GenAnswer]


def check_speaking(d: GenSpeaking, *, target_band: float) -> list[str]:
    p: list[str] = []
    if not 2 <= len(d.part1) <= 3:
        p.append("Part 1 needs 2-3 topics")
    for t in d.part1:
        if not 3 <= len(t.questions) <= 5:
            p.append(f"Part 1 topic '{t.topic}': give 3-5 questions")
        if bad := [q for q in t.questions if not q.strip().endswith("?")]:
            p.append(f"Part 1 topic '{t.topic}': these are not questions: {bad}")
    c = d.part2
    if not c.task.strip().lower().startswith("describe"):
        p.append("Part 2 cue card task must start with 'Describe'")
    if not 3 <= len(c.prompts) <= 4:
        p.append("Part 2 cue card needs 3-4 'You should say' prompts")
    if not c.explain.strip().lower().startswith("and explain"):
        p.append("Part 2 cue card must end with an 'and explain …' line")
    if not 1 <= len(c.rounding_off) <= 2 or any(not q.strip().endswith("?") for q in c.rounding_off):
        p.append("Part 2 needs 1-2 rounding-off questions")
    if not 4 <= len(d.part3) <= 6 or any(not q.strip().endswith("?") for q in d.part3):
        p.append("Part 3 needs 4-6 discussion questions")

    known = {1: {q.strip() for t in d.part1 for q in t.questions}, 2: {c.task.strip()}, 3: {q.strip() for q in d.part3}}
    parts_answered = {a.part for a in d.model_answers}
    if parts_answered != {1, 2, 3}:
        p.append("give model answers for Parts 1, 2 and 3")
    for i, a in enumerate(d.model_answers, start=1):
        where = f"model answer {i} (Part {a.part})"
        if a.question.strip() not in known[a.part]:
            p.append(f"{where}: question '{a.question}' is not in Part {a.part} — copy it exactly")
        lo, hi = LENGTHS[a.part]
        n = len(a.answer.split())
        if not lo <= n <= hi:
            p.append(f"{where}: {n} words; Part {a.part} answers should be {lo}-{hi} words")
        if a.target_band != target_band:
            p.append(f"{where}: target band must be {target_band:g}")
        scores = [CriterionScore(criterion=s.criterion, band=s.band, comment=s.comment) for s in a.scores]
        p += check_scores(scores, SPEAKING, a.target_band, where)
        pron = next((s for s in a.scores if s.criterion == "Pronunciation"), None)
        if pron and not any(w in pron.comment.lower() for w in ("listen", "spoken", "audio", "when said", "aloud")):
            p.append(f"{where}: the Pronunciation comment must say what to listen for when the answer is spoken "
                     "(it cannot be judged from text)")
    return p


def assemble(d: GenSpeaking) -> SpeakingTest:
    return SpeakingTest(part1=d.part1, part2=d.part2, part3=d.part3, model_answers=[
        ModelAnswer(part=a.part, question=a.question.strip(), target_band=a.target_band, answer=a.answer,
                    scores=[CriterionScore(criterion=s.criterion, band=s.band, comment=s.comment) for s in a.scores])
        for a in d.model_answers])


def render_examiner_script(t: SpeakingTest) -> str:
    out = ["# SPEAKING — examiner script", "", "## Part 1 (4–5 minutes)", ""]
    for topic in t.part1:
        out += [f"**{topic.topic}**", "", *(f"- {q}" for q in topic.questions), ""]
    c = t.part2
    out += ["## Part 2 (3–4 minutes)", "", "*Give the candidate the task card, paper and a pencil. "
            "One minute to prepare; speak for 1–2 minutes.*", "", f"**{c.task}**", "", "You should say:",
            *(f"- {x}" for x in c.prompts), f"{c.explain}", "", "Rounding-off:", *(f"- {q}" for q in c.rounding_off),
            "", "## Part 3 (4–5 minutes)", "", *(f"- {q}" for q in t.part3), ""]
    return "\n".join(out).rstrip() + "\n"


def render_cue_card(t: SpeakingTest) -> str:
    c = t.part2
    return "\n".join([f"**{c.task}**", "", "You should say:", *(f"- {x}" for x in c.prompts), c.explain, ""])


def render_model_answers(t: SpeakingTest) -> str:
    out = ["# Speaking — model answers", "", "_Bands are teaching estimates on the four public criteria; "
           "Pronunciation can only be judged when the answer is spoken._", ""]
    for a in t.model_answers:
        out += [f"## Part {a.part}: {a.question}", "", a.answer, "", "| Criterion | Band | Comment |", "|---|---|---|",
                *(f"| {s.criterion} | {s.band} | {s.comment} |" for s in a.scores), ""]
    return "\n".join(out).rstrip() + "\n"


SYSTEM = """You write ORIGINAL IELTS Speaking practice material (never reproduce published tests or band
descriptors). Part 1 asks about familiar topics; Part 2 is a cue card; Part 3 asks more abstract questions
linked to the Part 2 theme. Model answers sound natural and spoken, at the stated band, at realistic length.
Score each on the four criteria with whole bands and short comments in your own words; for Pronunciation,
say what a teacher should listen for when the answer is spoken."""


@dataclass
class SpeakingSpec:
    theme: str
    target_band: float = 7.0
    part1_topics: tuple[str, ...] = field(default=("home town", "free time"))


class IELTSSpeakingGenerator:
    def __init__(self, registry: ProviderRegistry, *, max_attempts: int = 3) -> None:
        self.registry = registry
        self.max_attempts = max_attempts

    async def generate(self, spec: SpeakingSpec) -> tuple[SpeakingTest, int]:
        prompt = "\n".join([
            f"Part 1 topics: {', '.join(spec.part1_topics)}.",
            f"Part 2 cue card and Part 3 discussion theme: {spec.theme}.",
            f"Model answers at band {spec.target_band:g}: at least two Part 1 answers, the Part 2 long turn, "
            "and at least two Part 3 answers.",
            f"Criteria, in order: {SPEAKING}."])
        out = await generate_checked(self.registry, STAGE, system=SYSTEM, prompt=prompt, schema=GenSpeaking,
                                     check=lambda d: check_speaking(d, target_band=spec.target_band),
                                     prompt_version=PROMPT_VERSION, max_attempts=self.max_attempts, max_tokens=32_000)
        return assemble(out.value), out.attempts
