"""Spec §46 — FIRST TEST.

IELTS Academic Reading: 3 passages, 40 questions, multiple question types,
answer key. Then introduce "...energy 13 The author..." style errors; the
IELTS Document Fixer must detect and repair them; the resulting DOCX must
validate against the deterministic import contract.
"""

import pytest

from osamu_dazai.ielts import export_reading_test, parse, repair_docx, validate_docx
from osamu_dazai.ielts.docx_io import read_docx
from osamu_dazai.ielts.fixer import squash
from tests.fixtures.ielts_sample import sample_test
from tests.ielts_helpers import build_docx as build_broken_docx
from tests.ielts_helpers import sample_lines


def glue(lines: list[str], prefix: str, joiner: str, *, after: int = 0) -> None:
    """Merge the first line starting with ``prefix`` (at or after ``after``) into the line above."""
    i = next(k for k, ln in enumerate(lines) if k >= after and ln.startswith(prefix))
    lines[i - 1] = lines[i - 1] + joiner + lines[i]
    del lines[i]


def broken_lines() -> list[str]:
    lines = sample_lines()
    # spec §20/§33 example shape: "...magnetic energy 13 The author..." (no full stop, no "13.")
    i12 = next(k for k, ln in enumerate(lines) if ln.startswith("12. "))
    lines[i12] = "12. Some bulbs released a small amount of magnetic energy"
    i13 = i12 + 1
    lines[i12] += " 13 " + lines[i13].split(" ", 1)[1]
    del lines[i13]
    glue(lines, "27. ", " ")  # first question of a group glued onto the YES/NO legend
    glue(lines, "16. ", " ")  # glued onto option D of question 15
    glue(lines, "10. ", " ", after=lines.index("ANSWER KEY"))  # answers "9. TRUE 10. NOT GIVEN"
    return lines


@pytest.fixture
def exported(tmp_path):
    path = tmp_path / "ielts_reading.docx"
    return path, export_reading_test(sample_test(), path)


def test_step1_generate_and_export(exported):
    path, result = exported
    assert result.passed and result.issues == []
    parsed = parse(read_docx(path).lines)
    assert len(parsed.passages) == 3
    assert sorted(n for it in parsed.items() for n in it.numbers) == list(range(1, 41))
    assert len({(g.type, g.form) for g in parsed.groups()}) == 11  # 11 distinct question formats
    assert sorted(n for a in parsed.answers for n in a.numbers) == list(range(1, 41))


def test_step2_inject_errors_detect_repair_validate(tmp_path):
    broken = build_broken_docx(broken_lines())

    before = validate_docx(broken)
    assert not before.passed
    glued = sorted(i.location.question for i in before.errors if i.code == "ielts.question.glued")
    assert glued == [13, 16, 27]
    assert "ielts.answer_key.glued" in {i.code for i in before.errors}

    out = repair_docx(broken, tmp_path / "fixed.docx")
    assert out.exported, out.report.render()
    assert out.report.preserved and out.report.flags == []
    assert sum(o.kind == "split" for o in out.report.ops) == 4

    after = validate_docx(tmp_path / "fixed.docx")
    assert after.passed and after.errors == []

    fixed = read_docx(tmp_path / "fixed.docx").lines
    texts = [ln.text for ln in fixed]
    assert "12. Some bulbs released a small amount of magnetic energy" in texts
    assert "13 The Haarlem auction was attended mainly by foreign buyers." in texts
    parsed = parse(fixed)
    assert sorted(n for it in parsed.items() for n in it.numbers) == list(range(1, 41))
    # only line breaks changed — wording identical
    assert squash(read_docx(broken).lines) == squash(fixed)


def test_step3_unrepairable_document_is_not_exported(tmp_path):
    lines = sample_lines()
    i = next(k for k, ln in enumerate(lines) if ln.startswith("13. "))
    lines[i - 1] += " and 13 more were sold."  # lowercase: not a confident question start
    del lines[i]
    out = repair_docx(build_broken_docx(lines), tmp_path / "fixed.docx")
    assert not out.exported
    assert not (tmp_path / "fixed.docx").exists()
    assert out.report.flags  # handed to a human, not guessed
