"""IELTS assessment criteria and band arithmetic for Writing and Speaking.

Only the public *names* of the criteria are used here. The official band
descriptor texts are owned by the IELTS partners and are not reproduced;
Osamu Dazai's commentaries are its own wording, and computed bands are clearly an
*estimate* for teaching purposes, not an official score.
"""

from __future__ import annotations

import math

from pydantic import Field

from osamu_dazai.domain.common import Model

WRITING_T1 = ["Task Achievement", "Coherence and Cohesion", "Lexical Resource", "Grammatical Range and Accuracy"]
WRITING_T2 = ["Task Response", "Coherence and Cohesion", "Lexical Resource", "Grammatical Range and Accuracy"]
SPEAKING = ["Fluency and Coherence", "Lexical Resource", "Grammatical Range and Accuracy", "Pronunciation"]


class CriterionScore(Model):
    criterion: str
    band: int = Field(ge=0, le=9)
    comment: str


def round_half(x: float) -> float:
    """Round to the nearest half band; quarters round up (6.25 → 6.5, 6.75 → 7.0)."""
    return math.floor(x * 2 + 0.5) / 2


def estimated_band(scores: list[CriterionScore]) -> float:
    return round_half(sum(s.band for s in scores) / len(scores))


def writing_overall(task1: float, task2: float) -> float:
    """Task 2 counts twice as much as Task 1."""
    return round_half((task1 + 2 * task2) / 3)


def check_scores(scores: list[CriterionScore], criteria: list[str], target: float, where: str) -> list[str]:
    p = []
    names = [s.criterion for s in scores]
    if names != criteria:
        p.append(f"{where}: give one score per criterion, in this order: {criteria} (got {names})")
        return p
    if any(not s.comment.strip() for s in scores):
        p.append(f"{where}: every criterion needs a comment")
    est = estimated_band(scores)
    if abs(est - target) > 0.5:
        p.append(f"{where}: criterion scores give band {est}, but the sample is meant to be band {target}")
    return p
