"""Export gate for IELTS Reading DOCX (spec §32: if validation fails, do NOT export).

The exporter validates the *file it is about to ship*: render → DOCX bytes →
read the DOCX back → parse → validate. Only a clean result is written.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from osamu_dazai.domain.validation import ValidationResult
from osamu_dazai.ielts import contract as C
from osamu_dazai.ielts.docx_io import Source, docx_bytes, read_docx
from osamu_dazai.ielts.fixer import IELTSFormatRepair, RepairReport
from osamu_dazai.ielts.lines import Line, lines_from_text
from osamu_dazai.ielts.model import IELTSReadingTest
from osamu_dazai.ielts.render import render_test
from osamu_dazai.ielts.validators import IELTSDocumentValidator


class ExportBlocked(Exception):
    def __init__(self, result: ValidationResult) -> None:
        self.result = result
        errs = result.errors
        head = "\n\n".join(i.render() for i in errs[:10])
        more = f"\n\n… and {len(errs) - 10} more" if len(errs) > 10 else ""
        super().__init__(f"Export blocked: {len(errs)} validation error(s)\n\n{head}{more}")


def validate_docx(src: Source, *, target_id: str = "", style: C.SectionStyle = C.READING) -> ValidationResult:
    read = read_docx(src)
    return IELTSDocumentValidator(style).validate_lines(read.lines, tables=read.tables, target_id=target_id)


def build_docx(lines: list[Line], style: C.SectionStyle = C.READING) -> tuple[bytes, ValidationResult]:
    """DOCX bytes plus the validation of those exact bytes (round-trip)."""
    data = docx_bytes(lines)
    return data, validate_docx(data, style=style)


def export_reading_test(test: IELTSReadingTest, dest: str | Path) -> ValidationResult:
    data, result = build_docx(render_test(test))
    if not result.passed:
        raise ExportBlocked(result)
    Path(dest).write_bytes(data)
    return result


def with_header_bold(lines: list[Line], style: C.SectionStyle = C.READING) -> list[Line]:
    out = []
    for ln in lines:
        t = ln.clean
        bold = bool(style.header.match(t) or C.QUESTIONS_HEADER.match(t) or C.ANSWER_KEY_HEADER.match(t))
        out.append(Line(text=ln.text, bold=bold))
    return out


@dataclass
class RepairOutcome:
    report: RepairReport
    exported: bool
    dest: Path | None


def repair_lines_to_docx(lines: list[Line], dest: str | Path, *, threshold: float = 0.8,
                         style: C.SectionStyle = C.READING) -> RepairOutcome:
    report = IELTSFormatRepair(threshold=threshold, style=style).repair(lines)
    if not report.preserved:
        return RepairOutcome(report, False, None)
    data, result = build_docx(with_header_bold(report.repaired, style), style)
    report.validation = result  # validate the shipped bytes, not just the lines
    if not result.passed:
        return RepairOutcome(report, False, None)
    Path(dest).write_bytes(data)
    return RepairOutcome(report, True, Path(dest))


def repair_docx(src: Source, dest: str | Path, *, threshold: float = 0.8,
                style: C.SectionStyle = C.READING) -> RepairOutcome:
    """IELTS Document Fixer: read a DOCX, repair structure, validate, export if clean."""
    return repair_lines_to_docx(read_docx(src).lines, dest, threshold=threshold, style=style)


def repair_text(text: str, dest: str | Path, *, threshold: float = 0.8,
                style: C.SectionStyle = C.READING) -> RepairOutcome:
    return repair_lines_to_docx(lines_from_text(text), dest, threshold=threshold, style=style)
