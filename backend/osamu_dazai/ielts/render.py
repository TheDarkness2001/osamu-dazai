"""Deterministic renderer: IELTSReadingTest → line IR (spec §17–31).

Parser compatibility beats decoration: one logical line per paragraph, literal
numbers and numerals, no lists, no tables.
"""

from __future__ import annotations

import re

from osamu_dazai.domain.questions import Question, QuestionGroup
from osamu_dazai.domain.questions import QuestionType as QT
from osamu_dazai.ielts import contract as C
from osamu_dazai.ielts.lines import Line
from osamu_dazai.ielts.model import IELTSReadingTest

_PLACEHOLDER = re.compile(r"\{(\d{1,2})\}")


class RenderError(ValueError):
    pass


def _q(n: int, text: str) -> Line:
    return Line(f"{n}. {text}")


def render_group(g: QuestionGroup) -> list[Line]:
    if g.range is None:
        raise RenderError(f"group {g.id} has no range")
    a, b = g.range
    out = [Line(f"Questions {a}-{b}", bold=True)]
    out += [Line(t) for t in g.instructions]
    t = g.type

    def shared_list() -> list[Line]:
        lst = [Line(g.list_title, bold=True)] if g.list_title else []
        return lst + [Line(f"{o.label} {o.text}") for o in g.shared_options]

    if t is QT.MATCHING_HEADINGS:
        out += shared_list()
        out += [_q(q.number, q.stem) for q in g.questions]
    elif t is QT.MULTIPLE_CHOICE_MULTI:
        if len(g.questions) != 1 or g.questions[0].number_range != (a, b):
            raise RenderError(f"compound group {a}-{b} must hold exactly one question covering {a}-{b}")
        q = g.questions[0]
        out.append(Line(q.stem))
        out += [Line(f"{o.label} {o.text}") for o in q.options]
    elif t is QT.MULTIPLE_CHOICE:
        for q in g.questions:
            out.append(_q(q.number, q.stem))
            out += [Line(f"{o.label}. {o.text}") for o in q.options]
    elif t is QT.MATCHING_INFORMATION:
        out += shared_list()  # explicit list first: keeps auto-detection safe (spec §27)
        out += [_q(q.number, q.stem) for q in g.questions]
    elif t in (QT.MATCHING_FEATURES, QT.MATCHING_SENTENCE_ENDINGS, QT.MATCHING):
        out += [_q(q.number, q.stem) for q in g.questions]
        out += shared_list()
    elif g.completion_form in C.INLINE_FORMS:
        if g.list_title:
            out.append(Line(g.list_title, bold=True))
        wanted = {q.number for q in g.questions}
        placed: set[int] = set()

        def fill(m: re.Match[str]) -> str:
            n = int(m.group(1))
            placed.add(n)
            return f"{n}{C.BLANK_INLINE_DEFAULT}"

        out += [Line(_PLACEHOLDER.sub(fill, line)) for line in g.body]
        if placed != wanted:
            raise RenderError(f"group {a}-{b}: body places {sorted(placed)}, questions are {sorted(wanted)}")
    else:  # TFNG, YNNG, sentence completion, short answer, labelling lists
        out += [_q(q.number, q.stem) for q in g.questions]
    return out


def _answer_line(q: Question) -> Line:
    if q.answer is None:
        raise RenderError(f"question {q.numbers()} has no answer")
    if q.number_range:
        a, b = q.number_range
        return Line(f"{a}-{b}. {', '.join(q.answer.accepted)}")
    return Line(f"{q.number}. {' | '.join(q.answer.accepted)}")


def render_test(test: IELTSReadingTest, *, include_answer_key: bool = True) -> list[Line]:
    out: list[Line] = []
    for s in test.sections:
        p = s.passage
        out.append(Line(f"PASSAGE {p.number}", bold=True))
        out.append(Line(p.title, bold=True))
        for para in p.paragraphs:
            out.append(Line(f"{para.label} {para.text}" if para.label else para.text))
        for g in s.groups:
            out += render_group(g)
    if include_answer_key:
        out.append(Line("ANSWER KEY", bold=True))
        questions = sorted((q for g in test.groups() for q in g.questions), key=lambda q: q.numbers()[0])
        out += [_answer_line(q) for q in questions]
    return out
