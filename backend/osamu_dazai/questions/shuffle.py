# Portions of this file are a Python port of ClassBuild's quiz version logic
# (src/services/export/quizDocExporter.ts: seededRng / shuffle / generateVersions)
# and its longest-answer audit (src/services/quiz/answerBalancer.ts: auditQuestions),
# https://github.com/jtangen/classbuild
#
# Copyright (c) 2026 Jason Tangen
# Licensed under the MIT License — see licenses/classbuild-MIT.txt.
#
# Changes for Osamu Dazai: translated to Python with explicit 32-bit arithmetic;
# versions operate on Osamu Dazai's Assessment/QuestionGroup model; added
# deterministic answer-position balancing (correct letters spread evenly over
# A–D in every version), which ClassBuild leaves to chance; the audit returns
# the offending questions deterministically instead of a random subset.
"""Seeded shuffling, balanced quiz versions, and the longest-correct-answer audit."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import TypeVar

from osamu_dazai.domain.questions import Answer, Assessment, Option, Question, QuestionGroup, QuestionType

T = TypeVar("T")
M32 = 0xFFFFFFFF
VERSION_LABELS = "ABCDEFGH"


def mulberry32(seed: int) -> Callable[[], float]:
    """Seeded PRNG (mulberry32), bit-identical to the JavaScript original."""
    state = seed & M32

    def nxt() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & M32
        t = ((state ^ (state >> 15)) * (1 | state)) & M32
        t = ((t + (((t ^ (t >> 7)) * (61 | t)) & M32)) & M32) ^ t
        return ((t ^ (t >> 14)) & M32) / 4294967296

    return nxt


def shuffled(items: Sequence[T], rng: Callable[[], float]) -> list[T]:
    """Fisher–Yates with the given RNG (same order of draws as the original)."""
    out = list(items)
    for i in range(len(out) - 1, 0, -1):
        j = math.floor(rng() * (i + 1))
        out[i], out[j] = out[j], out[i]
    return out


def longest_answer_bias(questions: Sequence[Question], *, expected_share: float = 0.25) -> list[Question]:
    """MC questions whose correct option is strictly the longest — returned only when that happens
    more often than chance (``expected_share`` of the questions), so a test does not leak answers."""
    mc = [q for q in questions if q.type is QuestionType.MULTIPLE_CHOICE and q.answer and len(q.options) > 1]
    if len(mc) <= 4:
        return []
    flagged = []
    for q in mc:
        correct = next((o for o in q.options if o.label == q.answer.accepted[0]), None)
        if correct and len(correct.text) > max(len(o.text) for o in q.options if o is not correct):
            flagged.append(q)
    return flagged if len(flagged) - round(len(mc) * expected_share) > 0 else []


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------
def _balanced_positions(n: int, k: int, rng: Callable[[], float]) -> list[int]:
    """n target positions over k slots, counts differing by at most one, in shuffled order."""
    base = [i % k for i in range(n)]
    return shuffled(base, rng)


def make_version(master: Assessment, index: int, *, seed_base: int = 42, balance: bool = True,
                 shuffle_questions: bool = True) -> Assessment:
    """Version ``index`` (0 → A): questions shuffled within each group, MC options reordered so the
    correct letters are evenly spread, everything renumbered, answer key updated."""
    rng = mulberry32(index * 1000 + seed_base)
    groups: list[QuestionGroup] = []
    number = 0
    for g in master.groups:
        order = shuffled(g.questions, rng) if shuffle_questions else list(g.questions)
        mc = [q for q in order if q.type is QuestionType.MULTIPLE_CHOICE and len(q.options) > 1 and q.answer]
        k = min((len(q.options) for q in mc), default=0)
        targets = iter(_balanced_positions(len(mc), k, rng)) if (balance and k) else None
        new_qs = []
        for q in order:
            number += 1
            update: dict = {"number": number}
            if q in mc:
                correct = next(o for o in q.options if o.label == q.answer.accepted[0])
                others = shuffled([o for o in q.options if o is not correct], rng)
                if targets is not None:
                    pos = next(targets)
                    texts = [*others[:pos], correct, *others[pos:]]
                else:
                    texts = shuffled([correct, *others], rng)
                    pos = texts.index(correct)
                labels = [o.label for o in q.options]
                update["options"] = [Option(label=labels[i], text=o.text) for i, o in enumerate(texts)]
                update["answer"] = Answer(accepted=[labels[pos]], explanation=q.answer.explanation,
                                          evidence=q.answer.evidence)
            new_qs.append(q.model_copy(update=update))
        groups.append(g.model_copy(update={"questions": new_qs}))
    label = VERSION_LABELS[index]
    return master.model_copy(update={
        "id": f"{master.id}_v{label}", "groups": groups, "version_label": label, "source_assessment_id": master.id,
        "title": master.title})


def rebalanced(a: Assessment, *, seed_base: int = 7) -> Assessment:
    """Same assessment, same question order, MC options reordered so correct letters are evenly spread."""
    v = make_version(a, 0, seed_base=seed_base, shuffle_questions=False)
    return v.model_copy(update={"id": a.id, "version_label": a.version_label,
                                "source_assessment_id": a.source_assessment_id})


def make_versions(master: Assessment, n: int = 4, **kw) -> list[Assessment]:  # noqa: ANN003
    if not 1 <= n <= len(VERSION_LABELS):
        raise ValueError(f"1-{len(VERSION_LABELS)} versions supported")
    return [make_version(master, i, **kw) for i in range(n)]


def answer_positions(a: Assessment) -> dict[str, int]:
    """How often each letter is the correct MC answer (for balance reports)."""
    counts: dict[str, int] = {}
    for g in a.groups:
        for q in g.questions:
            if q.type is QuestionType.MULTIPLE_CHOICE and q.answer:
                counts[q.answer.accepted[0]] = counts.get(q.answer.accepted[0], 0) + 1
    return dict(sorted(counts.items()))
