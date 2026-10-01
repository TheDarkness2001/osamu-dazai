"""Deterministic IELTS Reading parser (no AI).

Line state machine mirroring the external fixed-rule parser:
PREAMBLE → PASSAGE header → title → body → Questions header → instructions →
items … → ANSWER KEY (everything after it is answers, never questions).

The parser is deliberately literal: it records what it finds, with line
indexes, and leaves judgement to the validators.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from osamu_dazai.domain.questions import CompletionForm, QuestionType
from osamu_dazai.ielts import contract as C
from osamu_dazai.ielts.lines import Line


@dataclass
class PEntry:
    """A labelled list line: option "A text" or heading "ii text"."""

    label: str
    text: str
    line: int


@dataclass
class PItem:
    numbers: list[int]
    text: str
    line: int
    inline: bool = False
    options: list[PEntry] = field(default_factory=list)


@dataclass
class PGroup:
    start: int
    end: int
    header_line: int
    passage: int | None
    lines: list[int] = field(default_factory=list)  # all non-empty lines after the header
    instruction_lines: list[int] = field(default_factory=list)
    text_lines: list[int] = field(default_factory=list)  # stems, titles, summary text…
    detected: C.DetectedType | None = None
    word_limit: str | None = None
    items: list[PItem] = field(default_factory=list)
    options: list[PEntry] = field(default_factory=list)  # shared lettered list
    romans: list[PEntry] = field(default_factory=list)  # heading list

    @property
    def label(self) -> str:
        return f"Questions {self.start}-{self.end}"

    @property
    def type(self) -> QuestionType | None:
        return self.detected.type if self.detected else None

    @property
    def form(self) -> CompletionForm | None:
        return self.detected.form if self.detected else None

    @property
    def is_compound(self) -> bool:
        return self.type is QuestionType.MULTIPLE_CHOICE_MULTI

    @property
    def is_inline(self) -> bool:
        return self.form in C.INLINE_FORMS

    def numbers(self) -> list[int]:
        return [n for it in self.items for n in it.numbers]


@dataclass
class PPassage:
    number: int
    header_line: int
    title: str | None = None
    title_line: int | None = None
    body: list[int] = field(default_factory=list)
    groups: list[PGroup] = field(default_factory=list)


@dataclass
class PAnswer:
    numbers: list[int]
    raw: str
    line: int

    @property
    def alternatives(self) -> list[str]:
        return [a.strip() for a in self.raw.split("|") if a.strip()]

    @property
    def letters(self) -> list[str]:
        return [a.strip() for a in self.raw.replace(" and ", ",").split(",") if a.strip()]


@dataclass
class ParsedTest:
    lines: list[Line]
    preamble: list[int] = field(default_factory=list)
    passages: list[PPassage] = field(default_factory=list)
    orphan_groups: list[PGroup] = field(default_factory=list)  # Questions before any PASSAGE
    answer_key_lines: list[int] = field(default_factory=list)  # every heading found
    answers: list[PAnswer] = field(default_factory=list)
    unparsed_answer_lines: list[int] = field(default_factory=list)

    @property
    def answer_key_line(self) -> int | None:
        return self.answer_key_lines[0] if self.answer_key_lines else None

    def groups(self) -> list[PGroup]:
        return [*self.orphan_groups, *(g for p in self.passages for g in p.groups)]

    def items(self) -> list[PItem]:
        return [it for g in self.groups() for it in g.items]


def parse(lines: list[Line], style: C.SectionStyle = C.READING) -> ParsedTest:
    res = ParsedTest(lines=lines)
    passage: PPassage | None = None
    group: PGroup | None = None
    expect_title = False

    for i, ln in enumerate(lines):
        t = ln.clean
        if not t:
            continue
        if res.answer_key_lines:  # everything after the key is answers
            if C.ANSWER_KEY_HEADER.match(t):
                res.answer_key_lines.append(i)
            elif m := C.ANSWER_LINE.match(t):
                a, b = int(m.group(1)), m.group(2)
                nums = list(range(a, int(b) + 1)) if b else [a]
                res.answers.append(PAnswer(nums, m.group(3).strip(), i))
            else:
                res.unparsed_answer_lines.append(i)
            continue
        if C.ANSWER_KEY_HEADER.match(t):
            res.answer_key_lines.append(i)
            group = None
            continue
        if m := style.header.match(t):
            passage = PPassage(number=int(m.group(1)), header_line=i)
            res.passages.append(passage)
            group, expect_title = None, True
            continue
        if m := C.QUESTIONS_HEADER.match(t):
            group = PGroup(int(m.group(1)), int(m.group(2)), i, passage.number if passage else None)
            (passage.groups if passage else res.orphan_groups).append(group)
            expect_title = False
            continue
        if group is not None:
            group.lines.append(i)
        elif passage is None:
            res.preamble.append(i)
        elif expect_title:
            passage.title, passage.title_line, expect_title = t, i, False
        else:
            passage.body.append(i)

    for g in res.groups():
        _classify(g, lines)
    return res


# ---------------------------------------------------------------------------
def _runs(entries: dict[int, tuple[str, str]], order: list[str], idx: list[int]) -> set[int]:
    """Line indexes that belong to a sequential label run (A,B,C… / i,ii,iii…) of length ≥ 2."""
    member: set[int] = set()
    pos = 0
    while pos < len(idx):
        i = idx[pos]
        if i in entries and entries[i][0] == order[0]:
            run, want, j = [i], 1, pos + 1
            while j < len(idx) and want < len(order):
                k = idx[j]
                if k in entries and entries[k][0] == order[want]:
                    run.append(k)
                    want += 1
                    j += 1
                else:
                    break
            if len(run) >= 2:
                member.update(run)
                pos = j
                continue
        pos += 1
    return member


def _classify(g: PGroup, lines: list[Line]) -> None:
    idx = g.lines
    text = {i: lines[i].clean for i in idx}

    letters = {i: (m.group(1), m.group(2)) for i in idx if (m := C.OPTION_LINE.match(text[i]))}
    romans = {i: (m.group(1), m.group(2)) for i in idx if (m := C.ROMAN_LINE.match(text[i]))}
    letter_lines = _runs(letters, [chr(c) for c in range(ord("A"), ord("Z") + 1)], idx)
    roman_lines = _runs(romans, C.ROMANS, idx)
    numbered = {i: m for i in idx if (m := C.QUESTION_LINE.match(text[i]))}
    inline = {i for i in idx if C.find_inline_items(text[i])}

    # Instructions: leading lines before the first structural line.
    first_struct = next(
        (i for i in idx if i in numbered or i in letter_lines or i in roman_lines or i in inline), None
    )
    g.instruction_lines = [i for i in idx if first_struct is None or i < first_struct]
    instr = " ".join(text[i] for i in g.instruction_lines)
    g.detected = C.detect_type(instr)
    wl = C.WORD_LIMIT.search(instr)
    g.word_limit = wl.group(0) if wl else None

    if g.is_inline:
        for i in idx:
            if i in g.instruction_lines:
                continue
            found = C.find_inline_items(text[i])
            for n, _off in found:
                g.items.append(PItem([n], text[i], i, inline=True))
            if not found:
                g.text_lines.append(i)
        return

    current: PItem | None = None
    for i in idx:
        if i in g.instruction_lines:
            continue
        if i in roman_lines:
            g.romans.append(PEntry(*romans[i], i))
        elif i in letter_lines:
            entry = PEntry(*letters[i], i)
            if current is not None and g.type is QuestionType.MULTIPLE_CHOICE:
                current.options.append(entry)
            else:
                g.options.append(entry)
        elif i in numbered:
            m = numbered[i]
            current = PItem([int(m.group(1))], m.group(2), i)
            g.items.append(current)
        else:
            g.text_lines.append(i)

    if g.is_compound and not g.items:
        stem_line = g.instruction_lines[-1] if g.instruction_lines else g.header_line
        g.items.append(
            PItem(list(range(g.start, g.end + 1)), text.get(stem_line, ""), stem_line, options=g.options)
        )
