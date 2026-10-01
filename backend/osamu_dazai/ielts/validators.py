"""IELTS Reading validators (spec §20, §32).

``IELTSQuestionNumberValidator`` — numbering only: glued, missing, duplicate,
out-of-order, embedded numbers, and ranges that don't match their contents.

``IELTSDocumentValidator`` — the full pre-export checklist, including the
number validator and DOCX-level hazards (auto-numbering, soft breaks, tables).
Any deterministic ERROR blocks export.
"""

from __future__ import annotations

import re

from osamu_dazai.domain.common import Severity
from osamu_dazai.domain.questions import QuestionType as QT
from osamu_dazai.domain.validation import Location, ValidationIssue, ValidationResult
from osamu_dazai.ielts import contract as C
from osamu_dazai.ielts.lines import Line
from osamu_dazai.ielts.parser import ParsedTest, PGroup, parse

E, W = Severity.ERROR, Severity.WARNING


def _excerpt(text: str, at: int | None = None, width: int = 70) -> str:
    if at is None or len(text) <= width:
        return text[:width] + ("…" if len(text) > width else "")
    lo = max(0, at - width // 2)
    return ("…" if lo else "") + text[lo : lo + width] + "…"


class _Ctx:
    def __init__(self, parsed: ParsedTest) -> None:
        self.p = parsed
        self.issues: list[ValidationIssue] = []
        self.passage_of: dict[int, int] = {}
        for ps in parsed.passages:
            for i in [ps.header_line, *( [ps.title_line] if ps.title_line is not None else []), *ps.body]:
                self.passage_of[i] = ps.number
            for g in ps.groups:
                for i in [g.header_line, *g.lines]:
                    self.passage_of[i] = ps.number

    def loc(self, line: int | None, *, group: PGroup | None = None, question: int | None = None,
            at: int | None = None) -> Location:
        ln = self.p.lines[line] if line is not None else None
        passage = self.passage_of.get(line) if line is not None else None
        if passage is None and group is not None:
            passage = group.passage
        return Location(
            passage=passage,
            question_group=group.label if group else None,
            question=question,
            line=line + 1 if line is not None else None,
            paragraph_index=ln.para_index if ln else None,
            excerpt=_excerpt(ln.clean, at) if ln else "",
        )

    def add(self, code: str, sev: Severity, problem: str, loc: Location, expected: str = "",
            suggestion: str = "") -> None:
        self.issues.append(ValidationIssue(code=code, severity=sev, location=loc, problem=problem,
                                           expected=expected, suggestion=suggestion))


# ===========================================================================
class IELTSQuestionNumberValidator:
    """Every individual question number must begin on its own line (spec §20)."""

    def validate(self, parsed: ParsedTest) -> list[ValidationIssue]:
        ctx = _Ctx(parsed)
        groups = parsed.groups()
        prev_end = 0
        seen: dict[int, int] = {}  # number -> line
        for gi, g in enumerate(groups):
            if g.start > g.end:
                ctx.add("ielts.group.range_reversed", E, f"{g.label}: range is reversed",
                        ctx.loc(g.header_line, group=g), "Questions a-b with a ≤ b")
                continue
            if g.start != prev_end + 1:
                kind = "gap" if g.start > prev_end + 1 else "overlap"
                ctx.add(f"ielts.group.{kind}", E,
                        f"{g.label} follows a group ending at {prev_end} ({kind} in numbering)",
                        ctx.loc(g.header_line, group=g), f"Questions {prev_end + 1}-…")
            prev_end = max(prev_end, g.end)

            declared = set(range(g.start, g.end + 1))
            got: list[int] = []
            last = 0
            for it in g.items:
                for n in it.numbers:
                    if n in seen:
                        ctx.add("ielts.question.duplicate", E, f"Question {n} appears more than once",
                                ctx.loc(it.line, group=g, question=n),
                                f"each number once (first at line {seen[n] + 1})",
                                "Remove or renumber the duplicate")
                    else:
                        seen[n] = it.line
                    if n not in declared:
                        ctx.add("ielts.question.out_of_range", E,
                                f"Question {n} is outside its header {g.label}",
                                ctx.loc(it.line, group=g, question=n),
                                f"numbers {g.start}-{g.end} only",
                                "Fix the question number or the Questions header range")
                    if n < last:
                        ctx.add("ielts.question.order", E, f"Question {n} comes after question {last}",
                                ctx.loc(it.line, group=g, question=n), "ascending order")
                    last = max(last, n)
                    got.append(n)

            missing = sorted(declared - set(got))
            prev_group = groups[gi - 1] if gi else None
            for n in missing:
                self._missing(ctx, g, prev_group, n)
            if missing and not g.items:
                ctx.add("ielts.group.empty", E, f"{g.label} contains no recognisable questions",
                        ctx.loc(g.header_line, group=g),
                        "each question number at the start of its own line")
            if g.is_compound:
                self._compound(ctx, g)
            self._embedded(ctx, g, declared)

        self._answer_key(ctx)
        return ctx.issues

    # -----------------------------------------------------------------------
    def _search_region(self, ctx: _Ctx, g: PGroup, prev: PGroup | None, n: int) -> list[int]:
        region = list(g.lines)
        if n == g.start and prev is not None:
            region = prev.lines[-3:] + region
        return region

    def _missing(self, ctx: _Ctx, g: PGroup, prev: PGroup | None, n: int) -> None:
        if g.is_compound:
            return  # compound blocks own their whole range
        lines = ctx.p.lines
        hits = [
            (i, s)
            for i in self._search_region(ctx, g, prev, n)
            for s in C.glued_number_splits(lines[i].clean, n)
        ]
        if g.is_inline:
            ctx.add("ielts.question.missing", E, f"Question {n} has no numbered blank",
                    ctx.loc(g.header_line, group=g, question=n),
                    f'"{n}{C.BLANK_INLINE_DEFAULT}" inside the text',
                    f"Insert the number {n} directly before its blank")
            return
        strong = [h for h in hits if h[1].confidence >= 0.8]
        if strong:
            i, s = max(strong, key=lambda h: h[1].confidence)
            ctx.add("ielts.question.glued", E,
                    f"Question {n} does not start its own line — it is glued to the previous text",
                    ctx.loc(i, group=g, question=n, at=s.offset),
                    f"{n}. … on a new line",
                    f"Insert a line break before '{n}' (character {s.offset + 1} of line {i + 1})")
        elif hits:
            i, s = hits[0]
            ctx.add("ielts.question.missing", E,
                    f"Question {n} is missing from {g.label}; '{n}' appears mid-line but does not look "
                    "like a question start — needs review",
                    ctx.loc(i, group=g, question=n, at=s.offset),
                    f"a line starting with '{n}.'",
                    f"If question {n} starts at character {s.offset + 1} of line {i + 1}, "
                    "insert a line break there; otherwise add the missing question")
        else:
            ctx.add("ielts.question.missing", E, f"Question {n} is missing from {g.label}",
                    ctx.loc(g.header_line, group=g, question=n),
                    f"a line starting with '{n}.'",
                    "Add the question, or correct the Questions header range")

    def _embedded(self, ctx: _Ctx, g: PGroup, declared: set[int]) -> None:
        """Numbers of *other* questions sitting inside a question's text."""
        if g.is_inline:
            return
        present = set(g.numbers())
        for it in g.items:
            if it.inline:
                continue
            for n in sorted(declared & present - set(it.numbers)):
                for s in C.glued_number_splits(it.text, n):
                    if s.confidence >= 0.9:
                        ctx.add("ielts.question.embedded", W,
                                f"Text of question {it.numbers[0]} contains '{n}' followed by a new sentence",
                                ctx.loc(it.line, group=g, question=it.numbers[0]),
                                "one question per line",
                                "Check whether two questions were merged")

    def _compound(self, ctx: _Ctx, g: PGroup) -> None:
        split = [it for it in g.items if it.numbers != list(range(g.start, g.end + 1))]
        for it in split:
            ctx.add("ielts.compound.split", E,
                    f"'Choose {g.end - g.start + 1}' block {g.label} was split into numbered question {it.numbers}",
                    ctx.loc(it.line, group=g, question=it.numbers[0]),
                    "one compound block: instruction, stem, lettered options (no numbered lines)",
                    "Remove the per-box numbers; keep a single stem")
        if g.detected and g.detected.choose and g.detected.choose != g.end - g.start + 1:
            ctx.add("ielts.compound.choose_mismatch", E,
                    f"'Choose {g.detected.choose}' but {g.label} covers {g.end - g.start + 1} boxes",
                    ctx.loc(g.header_line, group=g), "range size = number of letters to choose")

    def _answer_key(self, ctx: _Ctx) -> None:
        p = ctx.p
        last = 0
        answered: set[int] = set()
        for a in p.answers:
            if a.numbers[0] < last:
                ctx.add("ielts.answer_key.order", E, f"Answer {a.numbers[0]} comes after answer {last}",
                        ctx.loc(a.line, question=a.numbers[0]), "ascending answer numbers")
            last = max(last, a.numbers[-1])
            answered.update(a.numbers)
        # glued answers ("1. ii 2. iv")
        for idx, a in enumerate(p.answers):
            nxt = a.numbers[-1] + 1
            if nxt not in answered:
                for s in C.glued_number_splits(p.lines[a.line].clean, nxt, answer_key=True):
                    ctx.add("ielts.answer_key.glued", E,
                            f"Answer {nxt} is on the same line as answer {a.numbers[-1]}",
                            ctx.loc(a.line, question=nxt, at=s.offset),
                            "one answer per line", f"Insert a line break before '{nxt}'")
                    break


# ===========================================================================
class IELTSDocumentValidator:
    """Full IELTS Reading pre-export checklist (spec §32)."""

    def __init__(self, style: C.SectionStyle = C.READING) -> None:
        self.style = style
        self.profile = style.profile

    def validate_lines(self, lines: list[Line], *, tables: int = 0, target_id: str = "") -> ValidationResult:
        parsed = parse(lines, self.style)
        ctx = _Ctx(parsed)
        self._docx(ctx)
        self._passages(ctx)
        self._headers(ctx)
        ctx.issues.extend(IELTSQuestionNumberValidator().validate(parsed))
        for g in parsed.groups():
            self._group(ctx, g)
        self._answers(ctx)
        return ValidationResult(target_id=target_id or "ielts", profile=self.profile, issues=ctx.issues)

    def validate_text(self, text: str, **kw) -> ValidationResult:  # noqa: ANN003
        from osamu_dazai.ielts.lines import lines_from_text

        return self.validate_lines(lines_from_text(text), **kw)

    # ---- DOCX hazards -----------------------------------------------------
    def _docx(self, ctx: _Ctx) -> None:
        key = ctx.p.answer_key_line
        for i, ln in enumerate(ctx.p.lines):
            if ln.auto_label:
                ctx.add("ielts.docx.auto_numbering", E,
                        f"Word automatic numbering ('{ln.auto_label}') — the label is not real text",
                        ctx.loc(i), "literal numbers / roman numerals typed as text",
                        f"Type '{ln.auto_label}' as text and remove list numbering")
            if ln.soft_breaks and ln.clean:
                ctx.add("ielts.docx.soft_break", E,
                        "Line break inside one paragraph (Shift+Enter) — parser sees one line",
                        ctx.loc(i), "one paragraph per line", "Replace the soft break with a paragraph break")
            if ln.in_table and ln.clean and (key is None or i < key):
                ctx.add("ielts.docx.table_before_key", E,
                        "Table content before ANSWER KEY (explanatory/answer tables are not parseable)",
                        ctx.loc(i), "plain paragraphs; answers only after ANSWER KEY",
                        "Move the table out, or convert it to plain lines")
            elif ln.in_table and ln.clean:
                ctx.add("ielts.docx.table_in_key", W, "Answer key is inside a table",
                        ctx.loc(i), "one answer per paragraph: '1. ii'")

    # ---- passages ---------------------------------------------------------
    def _passages(self, ctx: _Ctx) -> None:
        p, word = ctx.p, self.style.word
        if not p.passages:
            ctx.add("ielts.passage.none", E, f"No '{word} N' header found", Location(),
                    f"{word} 1 on its own line", f"Add a {word} header line")
        for k, ps in enumerate(p.passages, start=1):
            if ps.number != k:
                ctx.add("ielts.passage.sequence", E, f"{word} numbered {ps.number}, expected {k}",
                        ctx.loc(ps.header_line), f"{word} {k}")
            if not ps.title:
                ctx.add("ielts.passage.title_missing", E, f"{word} {ps.number} has no title line",
                        ctx.loc(ps.header_line), "a title / context line on the next non-empty line")
            elif self.style.require_body and (len(ps.title.split()) > 16 or ps.title.endswith(".")):
                ctx.add("ielts.passage.title_suspicious", W,
                        f"Title of {word} {ps.number} looks like body text", ctx.loc(ps.title_line),
                        "a short title line directly after the header")
            if self.style.require_body and not ps.body:
                ctx.add("ielts.passage.body_missing", E, f"{word} {ps.number} has no text",
                        ctx.loc(ps.header_line), "passage paragraphs before the first Questions header")
            if not ps.groups:
                ctx.add("ielts.passage.no_questions", E, f"{word} {ps.number} has no question groups",
                        ctx.loc(ps.header_line), f"Questions a-b headers after the {word.lower()} header")
        for g in p.orphan_groups:
            ctx.add("ielts.group.orphan", E, f"{g.label} appears before any {word} header",
                    ctx.loc(g.header_line, group=g), f"{word} N, title, then Questions")

    # ---- header lines that are present but malformed ------------------------
    def _headers(self, ctx: _Ctx) -> None:
        p = ctx.p
        key = p.answer_key_line
        for i, ln in enumerate(p.lines):
            t = ln.clean
            if not t or (key is not None and i > key):
                continue
            for s in C.header_splits(t, self.style):
                code = (
                    "ielts.passage.header_glued" if self.style.word in s.reason
                    else "ielts.answer_key.heading_glued" if "ANSWER" in s.reason
                    else "ielts.group.header_glued"
                )
                ctx.add(code, E, f"Header shares its line with other text ({s.reason})",
                        ctx.loc(i, at=s.offset), "the header alone on its own line",
                        f"Insert a line break at character {s.offset + 1}")
            if re.match(r"^READING\s+PASSAGE\s+\d+$", t):
                ctx.add("ielts.passage.header_wording", E, "Header reads 'READING PASSAGE N'",
                        ctx.loc(i), "PASSAGE N", "Change the line to exactly 'PASSAGE N' (wording change — confirm)")
            if C.SINGLE_QUESTION_HEADER.match(t):
                ctx.add("ielts.group.header_invalid", E, "Single 'Question N' header is not in the contract",
                        ctx.loc(i), "Questions a-b",
                        "Merge the question into a neighbouring group, or write 'Questions N-N'")
        if len(p.answer_key_lines) > 1:
            ctx.add("ielts.answer_key.duplicate_heading", E, "More than one ANSWER KEY heading",
                    ctx.loc(p.answer_key_lines[1]), "exactly one answer-key heading")

    # ---- per-group structure ----------------------------------------------
    def _group(self, ctx: _Ctx, g: PGroup) -> None:
        lines = ctx.p.lines
        hl = ctx.loc(g.header_line, group=g)
        if not g.instruction_lines:
            ctx.add("ielts.group.instructions_missing", E, f"{g.label} has no instruction line",
                    hl, "instruction text on the line(s) after the header")
        if g.detected is None:
            ctx.add("ielts.group.type_unknown", E, f"Cannot determine the question type of {g.label}",
                    hl, "a standard IELTS instruction (e.g. 'Choose the correct letter, A, B, C or D.')",
                    "Rewrite the instruction using standard wording (confirm with an editor)")
            return
        t = g.type

        if t is QT.MATCHING_HEADINGS:
            if len(g.romans) < 2:
                auto = [i for i in g.lines if lines[i].auto_label]
                ctx.add("ielts.headings.list_missing", E,
                        f"{g.label}: no literal roman-numeral heading list (i, ii, iii …)"
                        + (" — the list uses Word auto-numbering" if auto else ""),
                        hl, "lines like 'i Heading text' typed as plain text")
            valid = {r.label for r in g.romans}
            self._items_have_text(ctx, g)
            self._answers_in(ctx, g, valid, "heading numeral")

        elif t is QT.MULTIPLE_CHOICE_MULTI:
            if len(g.options) < (g.detected.choose or 2) + 1:
                ctx.add("ielts.compound.options_missing", E, f"{g.label}: too few lettered options",
                        hl, "lines 'A …', 'B …', … after the stem")
            self._answers_in(ctx, g, {o.label for o in g.options}, "option letter")

        elif t is QT.MULTIPLE_CHOICE:
            for it in g.items:
                if len(it.options) < 3:
                    ctx.add("ielts.mc.options_missing", E,
                            f"Question {it.numbers[0]} has {len(it.options)} options",
                            ctx.loc(it.line, group=g, question=it.numbers[0]),
                            "options A–D, each on its own line, after the question")
            for it in g.items:
                self._answers_in(ctx, g, {o.label for o in it.options}, "option letter", only=it.numbers)

        elif t in (QT.TRUE_FALSE_NOT_GIVEN, QT.YES_NO_NOT_GIVEN):
            self._items_have_text(ctx, g)
            valid = C.TFNG_VALUES if t is QT.TRUE_FALSE_NOT_GIVEN else C.YNNG_VALUES
            self._answers_in(ctx, g, valid, " / ".join(sorted(valid)))

        elif t is QT.MATCHING_INFORMATION:
            if len(g.options) < 2:
                ctx.add("ielts.matching_information.auto_detect_unsafe", W,
                        f"AUTO-DETECTION NOT SAFE: {g.label} ('Which paragraph contains…') has no explicit "
                        "lettered list — requires manual handling",
                        hl, "an explicit list such as 'A Paragraph A', 'B Paragraph B' …",
                        "Add an explicit paragraph list, or mark the group for manual import")
            else:
                self._answers_in(ctx, g, {o.label for o in g.options}, "letter")
            self._items_have_text(ctx, g)

        elif t in (QT.MATCHING_FEATURES, QT.MATCHING_SENTENCE_ENDINGS, QT.MATCHING):
            if len(g.options) < 2:
                ctx.add("ielts.matching.options_missing", E, f"{g.label}: no lettered choice list found",
                        hl, "lines 'A …', 'B …' before or after the numbered statements")
            self._items_have_text(ctx, g)
            self._answers_in(ctx, g, {o.label for o in g.options}, "letter")

        elif t is QT.LABELLING and g.form is None:  # map / plan labelling with letters
            self._items_have_text(ctx, g)
            self._answers_in(ctx, g, set("ABCDEFGHIJKLMNOPQRSTUVWXYZ"), "letter on the plan")

        elif t in (QT.COMPLETION, QT.LABELLING):
            if not g.word_limit:
                ctx.add("ielts.completion.word_limit_missing", E, f"{g.label}: no word-limit instruction",
                        hl, "e.g. 'Choose NO MORE THAN TWO WORDS from the passage'")
            if not g.is_inline:
                for it in g.items:
                    n = len(C.find_blanks(it.text))
                    if n == 0:
                        ctx.add("ielts.completion.blank_missing", E,
                                f"Question {it.numbers[0]} has no blank (______ or ……)",
                                ctx.loc(it.line, group=g, question=it.numbers[0]), "a blank marker in the sentence")
                    elif n > 1:
                        ctx.add("ielts.completion.multiple_blanks", W,
                                f"Question {it.numbers[0]} has {n} blanks",
                                ctx.loc(it.line, group=g, question=it.numbers[0]), "one blank per question")

        elif t is QT.SHORT_ANSWER:
            if not g.word_limit:
                ctx.add("ielts.short_answer.word_limit_missing", E, f"{g.label}: no word-limit instruction",
                        hl, "e.g. 'Choose NO MORE THAN THREE WORDS from the passage'")
            for it in g.items:
                if C.find_blanks(it.text):
                    ctx.add("ielts.short_answer.has_blank", E,
                            f"Question {it.numbers[0]} contains a blank but the group is short-answer",
                            ctx.loc(it.line, group=g, question=it.numbers[0]),
                            "a question ending with '?' (or use a completion instruction)")
                elif not it.text.rstrip().endswith("?"):
                    ctx.add("ielts.short_answer.not_question", W,
                            f"Question {it.numbers[0]} does not end with '?'",
                            ctx.loc(it.line, group=g, question=it.numbers[0]), "a direct question")

        for i in g.text_lines:
            if t not in (QT.COMPLETION, QT.LABELLING, QT.MULTIPLE_CHOICE_MULTI) and not g.is_inline:
                txt = lines[i].clean
                if re.match(r"^(answers?|explanations?|key)\b", txt, re.IGNORECASE):
                    ctx.add("ielts.answers_before_key", E, "Answer/explanation text before ANSWER KEY",
                            ctx.loc(i, group=g), "answers only after the ANSWER KEY heading")

    def _items_have_text(self, ctx: _Ctx, g: PGroup) -> None:
        for it in g.items:
            if not it.text.strip():
                ctx.add("ielts.question.empty", E, f"Question {it.numbers[0]} has no text",
                        ctx.loc(it.line, group=g, question=it.numbers[0]), "question text after the number")

    def _answers_in(self, ctx: _Ctx, g: PGroup, valid: set[str], what: str,
                    only: list[int] | None = None) -> None:
        if not valid:
            return
        nums = set(only or range(g.start, g.end + 1))
        for a in ctx.p.answers:
            if not nums & set(a.numbers):
                continue
            values = a.letters if g.is_compound else a.alternatives
            bad = [v for v in values if v not in valid and v.upper() not in valid]
            if bad:
                ctx.add("ielts.answer_key.answer_invalid", E,
                        f"Answer for {a.numbers[0] if len(a.numbers) == 1 else f'{a.numbers[0]}-{a.numbers[-1]}'}"
                        f" is {bad}, not a valid {what}",
                        ctx.loc(a.line, group=g, question=a.numbers[0]),
                        f"one of: {', '.join(sorted(valid))}")
            if g.is_compound and g.detected and g.detected.choose and len(a.letters) != g.detected.choose:
                ctx.add("ielts.answer_key.compound_count", E,
                        f"{g.label} needs {g.detected.choose} letters, answer gives {len(a.letters)}",
                        ctx.loc(a.line, group=g), f"{g.start}-{g.end}. C, D")

    # ---- answer key -------------------------------------------------------
    def _answers(self, ctx: _Ctx) -> None:
        p = ctx.p
        if p.answer_key_line is None:
            ctx.add("ielts.answer_key.missing", E, "No ANSWER KEY heading", Location(),
                    "'ANSWER KEY' on its own line after the last question group",
                    "Add the answer key (answers are never invented automatically)")
            return
        last_q = max((g.header_line for g in p.groups()), default=-1)
        if p.answer_key_line < last_q:
            ctx.add("ielts.answer_key.misplaced", E, "ANSWER KEY appears before the last question group",
                    ctx.loc(p.answer_key_line), "the answer key after all passages and questions")
        groups = p.groups()
        compound = {tuple(range(g.start, g.end + 1)) for g in groups if g.is_compound}
        expected = {n for g in groups for n in range(g.start, g.end + 1)}
        answered: dict[int, int] = {}
        for a in p.answers:
            if len(a.numbers) > 1 and tuple(a.numbers) not in compound:
                ctx.add("ielts.answer_key.range_mismatch", E,
                        f"Answer range {a.numbers[0]}-{a.numbers[-1]} does not match a compound group",
                        ctx.loc(a.line), "ranges only for 'Choose TWO/THREE' blocks")
            for n in a.numbers:
                if n in answered:
                    ctx.add("ielts.answer_key.answer_duplicate", E, f"Answer {n} given twice",
                            ctx.loc(a.line, question=n), "one answer line per question")
                answered[n] = a.line
                if n not in expected:
                    ctx.add("ielts.answer_key.answer_extra", E, f"Answer {n} has no matching question",
                            ctx.loc(a.line, question=n), "answers only for existing questions")
        for g in groups:
            for n in range(g.start, g.end + 1):
                if n not in answered:
                    if g.is_compound and tuple(range(g.start, g.end + 1)) in compound:
                        hint = f"{g.start}-{g.end}. C, D"
                    else:
                        hint = f"{n}. <answer>"
                    ctx.add("ielts.answer_key.answer_missing", E, f"No answer for question {n}",
                            ctx.loc(p.answer_key_line, group=g, question=n), hint)
            if g.is_compound:
                for n in range(g.start, g.end + 1):
                    a_line = answered.get(n)
                    if a_line is not None:
                        a = next(x for x in p.answers if x.line == a_line)
                        if a.numbers != list(range(g.start, g.end + 1)):
                            ctx.add("ielts.answer_key.compound_split", E,
                                    f"Compound {g.label} answered per box instead of as one range",
                                    ctx.loc(a_line, group=g, question=n), f"{g.start}-{g.end}. C, D")
                            break
        for i in p.unparsed_answer_lines:
            ctx.add("ielts.answer_key.unparsed_line", E, "Line after ANSWER KEY is not an answer",
                    ctx.loc(i), "'N. answer' or 'a-b. X, Y'",
                    "Move explanations out of the answer key or format as 'N. answer'")
