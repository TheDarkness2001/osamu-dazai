import asyncio
import xml.etree.ElementTree as ET

import pytest

from osamu_dazai.ielts import contract as C
from osamu_dazai.ielts import lines_to_text, parse
from osamu_dazai.ielts.docx_io import docx_bytes, read_docx
from osamu_dazai.ielts.fixer import IELTSFormatRepair
from osamu_dazai.ielts.listening import (
    STAGE,
    IELTSListeningGenerator,
    check_part,
    default_plan,
    render_paper,
    render_transcript,
)
from osamu_dazai.ielts.validators import IELTSDocumentValidator
from osamu_dazai.providers import ProviderRegistry
from osamu_dazai.providers.llm import MockProvider
from osamu_dazai.visuals.svg import render_plan
from tests.fixtures.listening_sample import PLAN, part1, part2, part3, part4, parts

run = asyncio.run
V = IELTSDocumentValidator(C.LISTENING)


@pytest.fixture(scope="module")
def report():
    mock = MockProvider().queue(STAGE, *[p.model_dump_json() for p in parts()])
    reg = ProviderRegistry()
    reg.register_llm(mock)
    return run(IELTSListeningGenerator(reg).generate(PLAN, title="Practice Listening 1"))


def test_default_plan_is_four_by_ten():
    plan = default_plan(("a", "b", "c", "d"))
    assert [p.count for p in plan] == [10, 10, 10, 10]
    assert [p.dialogue for p in plan] == [True, False, True, False]


def test_fixture_parts_pass_checks():
    for spec, part in zip(PLAN, parts(), strict=True):
        assert check_part(part, spec) == [], spec.number


def test_generate_and_validate_paper(report):
    assert report.validation.passed, [i.render() for i in report.validation.issues]
    assert report.test.question_count() == 20
    text = lines_to_text(render_paper(report.test))
    assert text.startswith("PART 1\nA telephone conversation")
    assert "Surname: 1………………" in text and "Label the plan below." in text
    p = parse(render_paper(report.test), C.LISTENING)
    assert [g.type.value for g in p.groups()] == ["completion", "completion", "multiple_choice", "labelling",
                                                  "multiple_choice", "matching_features", "completion"]
    assert sorted(n for it in p.items() for n in it.numbers) == list(range(1, 21))
    # DOCX round-trip through the shared export rules
    assert V.validate_lines(read_docx(docx_bytes(render_paper(report.test))).lines).passed


def test_transcript_and_plan(report):
    md = render_transcript(report.test)
    assert "## PART 1" in md and "**Daniel:** It's Harper." in md
    p2 = report.test.parts[1]
    svg = render_plan([(i.label, i.x, i.y, i.w, i.h) for i in p2.plan], p2.plan_title, "plan")
    root = ET.fromstring(svg.svg)
    assert {"A", "B", "C", "D", "E", "Lake"} <= set(root.itertext())


def test_answer_must_be_heard():
    d = part1()
    d.groups[0].items[1].answers = ["Fernhill Road"]  # the distractor phrase, not what was finally said
    problems = check_part(d, PLAN[0])
    assert any("never heard" in p for p in problems)


def test_answers_must_follow_audio_order():
    d = part1()
    d.groups[0].items[0], d.groups[0].items[3] = d.groups[0].items[3], d.groups[0].items[0]
    assert any("order they are heard" in p for p in check_part(d, PLAN[0]))


def test_word_limits_and_letters():
    d = part1()
    d.groups[1].items[0].answers = ["passport photo"]
    assert any("breaks the limit ONE WORD AND/OR A NUMBER" in p for p in check_part(d, PLAN[0]))
    d4 = part4()
    d4.groups[0].items[0].answers = ["diet 2"]
    assert any("breaks the limit ONE WORD ONLY" in p for p in check_part(d4, PLAN[3]))
    d2 = part2()
    d2.groups[1].items[0].answers = ["H"]
    d2.groups[0].items[0].evidence = ""
    problems = check_part(d2, PLAN[1])
    assert any("answer must be one letter A-E" in p for p in problems)
    assert any("quote the transcript words" in p for p in problems)


def test_part_shape():
    d = part2()
    d.speakers.append("Visitor")
    assert any("monologue" in p for p in check_part(d, PLAN[1]))
    d3 = part3()
    d3.speakers = ["Amira"]
    problems = check_part(d3, PLAN[2])
    assert any("conversation" in p for p in problems) and any("not listed" in p for p in problems)
    d1 = part1()
    d1.groups[0].lines = ["Surname: {1}", "Address: {3}", "Mobile: {2}", "Main activity: {4}"]
    assert any("{1}…{4} in order" in p for p in check_part(d1, PLAN[0]))


def test_plan_letters_must_match():
    d = part2()
    d.plan = [x for x in d.plan if x.label != "E"]
    assert any("letters A-E" in p for p in check_part(d, PLAN[1]))


def test_fixer_and_validator_handle_part_headers(report):
    text = lines_to_text(render_paper(report.test))
    glued = text.replace("Parking is free after 6………………\nPART 2", "Parking is free after 6……………… PART 2")
    assert glued != text
    assert "ielts.passage.header_glued" in {i.code for i in V.validate_text(glued).errors}
    rep = IELTSFormatRepair(style=C.LISTENING).repair_text(glued)
    assert rep.ok, rep.render()
    # the Reading profile would not accept a Listening paper
    assert not IELTSDocumentValidator().validate_text(text).passed


def test_feedback_loop():
    bad = part4()
    bad.groups[0].items[2].answers = ["mites"]
    mock = MockProvider().queue(STAGE, part1().model_dump_json(), part2().model_dump_json(),
                                part3().model_dump_json(), bad.model_dump_json(), part4().model_dump_json())
    reg = ProviderRegistry()
    reg.register_llm(mock)
    rep = run(IELTSListeningGenerator(reg).generate(PLAN))
    assert rep.attempts == {1: 1, 2: 1, 3: 1, 4: 2}
    assert "'mites' is never heard" in mock.requests[4].messages[-1].content
