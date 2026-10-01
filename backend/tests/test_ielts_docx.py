import zipfile
from io import BytesIO

import pytest

from osamu_dazai.ielts import (
    ExportBlocked,
    export_reading_test,
    lines_from_text,
    render_test,
    repair_docx,
    validate_docx,
)
from osamu_dazai.ielts.docx_io import docx_bytes, read_docx
from tests.fixtures.ielts_sample import sample_test
from tests.ielts_helpers import build_docx, sample_lines


def document_xml(data: bytes) -> str:
    with zipfile.ZipFile(BytesIO(data)) as z:
        return z.read("word/document.xml").decode("utf-8")


def test_written_docx_is_parser_safe():
    lines = render_test(sample_test())
    data = docx_bytes(lines)
    xml = document_xml(data)
    assert "w:numPr" not in xml and "<w:br" not in xml and "<w:tbl" not in xml
    read = read_docx(data)
    assert [ln.text for ln in read.lines] == [ln.text for ln in lines]  # one paragraph per line
    assert all(ln.auto_label is None for ln in read.lines)


def test_auto_numbered_heading_list_detected_and_repaired(tmp_path):
    lines = sample_lines()
    heading_idx = {i for i, ln in enumerate(lines) if ln.split(" ")[0] in
                   {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii"} and i < lines.index("1. Paragraph A")}
    assert len(heading_idx) == 8
    stripped = [ln.split(" ", 1)[1] if i in heading_idx else ln for i, ln in enumerate(lines)]
    data = build_docx(stripped, roman_auto=heading_idx)

    read = read_docx(data)
    labels = [read.lines[i].auto_label for i in sorted(heading_idx)]
    assert labels == ["i.", "ii.", "iii.", "iv.", "v.", "vi.", "vii.", "viii."]

    r = validate_docx(data)
    codes = {i.code for i in r.errors}
    assert {"ielts.docx.auto_numbering", "ielts.headings.list_missing"} <= codes

    out = repair_docx(data, tmp_path / "fixed.docx")
    assert out.exported, out.report.render()
    fixed = read_docx(tmp_path / "fixed.docx")
    assert "iii. Government controls on trade" in [ln.text for ln in fixed.lines]
    assert "w:numPr" not in document_xml((tmp_path / "fixed.docx").read_bytes())


def test_soft_break_detected_and_repaired(tmp_path):
    lines = sample_lines()
    i12 = next(i for i, ln in enumerate(lines) if ln.startswith("12. "))
    data = build_docx(lines, soft_break_with_next={i12})
    r = validate_docx(data)
    assert "ielts.docx.soft_break" in {i.code for i in r.errors}
    out = repair_docx(data, tmp_path / "fixed.docx")
    assert out.exported, out.report.render()
    assert validate_docx(tmp_path / "fixed.docx").passed


def test_table_before_answer_key_rejected():
    lines = sample_lines()
    lines.insert(lines.index("Questions 14-17"), "Answer: TRUE because paragraph B says so")
    i = lines.index("Answer: TRUE because paragraph B says so")
    r = validate_docx(build_docx(lines, table_lines={i}))
    assert "ielts.docx.table_before_key" in {x.code for x in r.errors}


def test_export_gate_blocks_invalid_model(tmp_path):
    t = sample_test()
    t.sections[0].groups[2].questions[0].answer.accepted = ["MAYBE"]
    with pytest.raises(ExportBlocked) as exc:
        export_reading_test(t, tmp_path / "x.docx")
    assert not (tmp_path / "x.docx").exists()
    assert "ielts.answer_key.answer_invalid" in str(exc.value)
    assert "Location: Passage 1" in str(exc.value)


def test_text_input_lines_round_trip():
    lines = lines_from_text("a\r\nb\rc")
    assert [ln.text for ln in lines] == ["a", "b", "c"]
