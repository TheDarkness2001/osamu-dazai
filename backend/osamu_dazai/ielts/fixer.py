"""IELTS Format Repair (spec §33–34).

Repairs badly formatted IELTS Reading documents *structurally*:

* Word auto-numbering → literal text (the label the reader saw)
* soft line breaks → separate lines
* headers glued to text → own lines
* glued question numbers ("…energy 13 The author…") → own lines
* glued options / heading entries / answers → own lines

It never rewrites wording. Every change is a ``RepairOp`` with a confidence;
only ops at or above the threshold are applied, the rest become
``ReviewFlag``s for a human. A hard invariant checks that the visible text,
ignoring whitespace, is identical before and after — otherwise the repair is
rejected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from osamu_dazai.domain.questions import QuestionType as QT
from osamu_dazai.domain.validation import ValidationResult
from osamu_dazai.ielts import contract as C
from osamu_dazai.ielts.lines import Line
from osamu_dazai.ielts.parser import ParsedTest, parse
from osamu_dazai.ielts.validators import IELTSDocumentValidator


_OPTION_A = re.compile(r"(?<=\s)A[.)]\s+(?=\S)")


@dataclass
class RepairOp:
    kind: str  # materialize_numbering | split_soft_break | trim | split
    line: int  # 1-based line number at the time of the op
    confidence: float
    reason: str
    before: str
    after: list[str]
    applied: bool = True


@dataclass
class ReviewFlag:
    line: int  # 1-based
    problem: str
    proposal: str
    confidence: float
    excerpt: str


@dataclass
class RepairReport:
    original: list[Line]
    repaired: list[Line]
    ops: list[RepairOp] = field(default_factory=list)
    flags: list[ReviewFlag] = field(default_factory=list)
    preserved: bool = True
    validation: ValidationResult | None = None
    parsed: ParsedTest | None = None

    @property
    def ok(self) -> bool:
        return self.preserved and self.validation is not None and self.validation.passed

    def group_summary(self) -> list[str]:
        if self.parsed is None:
            return []
        out = []
        for g in self.parsed.groups():
            t = g.type.value if g.type else "UNKNOWN"
            if g.form:
                t += f"/{g.form.value}"
            out.append(f"P{g.passage} {g.label}: {t}")
        return out

    def render(self) -> str:
        lines = [f"Repairs applied: {sum(o.applied for o in self.ops)}",
                 f"Flags for review: {len(self.flags)}",
                 f"Text preserved: {'yes' if self.preserved else 'NO — repair rejected'}"]
        for o in self.ops:
            lines.append(f"  [{o.kind} {o.confidence:.2f}] line {o.line}: {o.reason}")
        for f in self.flags:
            lines.append(f"  REVIEW line {f.line}: {f.problem} — {f.proposal}  «{f.excerpt}»")
        if self.validation is not None:
            lines.append(f"Validation: {'PASSED' if self.validation.passed else 'FAILED'}")
            lines += ["  " + i.render().replace("\n", "\n  ") for i in self.validation.issues]
        return "\n".join(lines)


def squash(lines: list[Line]) -> str:
    """Visible text with all whitespace removed — the preservation invariant."""
    return re.sub(r"\s+", "", "".join(ln.visible for ln in lines))


class IELTSFormatRepair:
    def __init__(self, threshold: float = 0.8, max_ops: int = 500, style: C.SectionStyle = C.READING) -> None:
        self.threshold = threshold
        self.max_ops = max_ops
        self.style = style

    # ------------------------------------------------------------------
    def repair(self, lines: list[Line]) -> RepairReport:
        original = [replace(ln) for ln in lines]
        report = RepairReport(original=original, repaired=[])
        work = self._materialize(original, report)
        work = self._split_soft_breaks(work, report)
        work = self._trim(work, report)

        flagged: set[tuple[str, int]] = set()
        for _ in range(self.max_ops):
            step = self._next_split(work, report, flagged)
            if step is None:
                break
            i, split = step
            work = self._apply_split(work, i, split, report)

        report.repaired = work
        report.preserved = squash(original) == squash(work)
        report.parsed = parse(work, self.style)
        if report.preserved:
            report.validation = IELTSDocumentValidator(self.style).validate_lines(work)
        return report

    def repair_text(self, text: str) -> RepairReport:
        from osamu_dazai.ielts.lines import lines_from_text

        return self.repair(lines_from_text(text))

    # ---- whole-line normalisations -----------------------------------
    def _materialize(self, lines: list[Line], rep: RepairReport) -> list[Line]:
        out = []
        for k, ln in enumerate(lines):
            if ln.auto_label:
                new = replace(ln, text=f"{ln.auto_label} {ln.text}", auto_label=None)
                rep.ops.append(RepairOp("materialize_numbering", k + 1, 0.95,
                                        f"Word auto-numbering '{ln.auto_label}' typed as literal text",
                                        ln.text, [new.text]))
                ln = new
            out.append(ln)
        return out

    def _split_soft_breaks(self, lines: list[Line], rep: RepairReport) -> list[Line]:
        out = []
        for ln in lines:
            if "\n" in ln.text:
                parts = ln.text.split("\n")
                rep.ops.append(RepairOp("split_soft_break", len(out) + 1, 0.95,
                                        "soft line break → paragraph break", ln.text, parts))
                out += [replace(ln, text=p, soft_breaks=0) for p in parts]
            else:
                out.append(ln)
        return out

    def _trim(self, lines: list[Line], rep: RepairReport) -> list[Line]:
        out = []
        trimmed = 0
        for ln in lines:
            t = ln.text.strip()
            if t != ln.text:
                trimmed += 1
            out.append(replace(ln, text=t))
        if trimmed:
            rep.ops.append(RepairOp("trim", 0, 0.99, f"leading/trailing whitespace removed on {trimmed} lines",
                                    "", []))
        return out

    # ---- splits ------------------------------------------------------
    def _decide(self, i: int, s: C.Split, work: list[Line], rep: RepairReport,
                flagged: set[tuple[str, int]]) -> tuple[int, C.Split] | None:
        if s.confidence >= self.threshold:
            return i, s
        key = (work[i].text, s.offset)
        if key not in flagged:
            flagged.add(key)
            t = work[i].text
            rep.flags.append(ReviewFlag(i + 1, s.reason, f"line break at character {s.offset + 1}?",
                                        s.confidence, t[max(0, s.offset - 30): s.offset + 30]))
        return None

    def _next_split(self, work: list[Line], rep: RepairReport,
                    flagged: set[tuple[str, int]]) -> tuple[int, C.Split] | None:
        parsed = parse(work, self.style)
        key = parsed.answer_key_line

        # 1. headers glued to text
        for i, ln in enumerate(work):
            if key is not None and i > key:
                break
            for s in C.header_splits(ln.text, self.style):
                if (d := self._decide(i, s, work, rep, flagged)) is not None:
                    return d

        # 2. glued question numbers
        groups = parsed.groups()
        for gi, g in enumerate(groups):
            if g.is_compound or g.is_inline or g.start > g.end:
                continue
            present = set(g.numbers())
            for n in range(g.start, g.end + 1):
                if n in present:
                    continue
                region = list(g.lines)
                if n == g.start and gi > 0:
                    region = groups[gi - 1].lines[-3:] + region
                hits = [(i, s) for i in region for s in C.glued_number_splits(work[i].text, n)]
                if not hits:
                    continue
                strong = [h for h in hits if h[1].confidence >= self.threshold]
                if len(strong) > 1:  # ambiguous: two plausible starts — let a human decide
                    for i, s in strong:
                        self._decide(i, C.Split(s.offset, 0.6, f"question {n}: ambiguous position"),
                                     work, rep, flagged)
                    continue
                i, s = strong[0] if strong else max(hits, key=lambda h: h[1].confidence)
                if (d := self._decide(i, s, work, rep, flagged)) is not None:
                    return d

        # 3. glued options / heading entries
        for g in groups:
            if g.type is QT.MULTIPLE_CHOICE:
                for it in g.items:
                    if it.options:
                        continue
                    # "14. Why…? A. first option" with B., C., D. on the following lines
                    m = _OPTION_A.search(work[it.line].text)
                    if m is None or m.start() == 0:
                        continue
                    nxt = next((work[k].text for k in range(it.line + 1, len(work)) if work[k].text), "")
                    conf = 0.85 if C.OPTION_LINE.match(nxt) and nxt.startswith("B") else 0.6
                    s = C.Split(m.start(), conf, "option A glued to its question")
                    if (d := self._decide(it.line, s, work, rep, flagged)) is not None:
                        return d
            if g.type in (QT.MULTIPLE_CHOICE, QT.MULTIPLE_CHOICE_MULTI, *C.LIST_TYPES):
                for i in g.lines:
                    roman = g.type is QT.MATCHING_HEADINGS and C.ROMAN_LINE.match(work[i].text) is not None
                    for s in C.list_marker_splits(work[i].text, roman=roman):
                        if (d := self._decide(i, s, work, rep, flagged)) is not None:
                            return d

        # 4. glued answers
        answered = {n for a in parsed.answers for n in a.numbers}
        for a in parsed.answers:
            nxt = a.numbers[-1] + 1
            if nxt in answered:
                continue
            for s in C.glued_number_splits(work[a.line].text, nxt, answer_key=True):
                if (d := self._decide(a.line, s, work, rep, flagged)) is not None:
                    return d
        return None

    def _apply_split(self, work: list[Line], i: int, s: C.Split, rep: RepairReport) -> list[Line]:
        ln = work[i]
        left, right = ln.text[: s.offset].rstrip(), ln.text[s.offset :].lstrip()
        rep.ops.append(RepairOp("split", i + 1, s.confidence, s.reason, ln.text, [left, right]))
        return [*work[:i], replace(ln, text=left), replace(ln, text=right), *work[i + 1 :]]
