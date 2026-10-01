"""IELTS Reading generation through the provider layer (mock LLM, no network)."""

import asyncio
import re

import pytest

from osamu_dazai.domain.questions import CompletionForm as CF
from osamu_dazai.domain.questions import QuestionType as QT
from osamu_dazai.ielts import export_reading_test, parse, validate_docx
from osamu_dazai.ielts.docx_io import read_docx
from osamu_dazai.ielts.generator import (
    STAGE,
    GenerationFailed,
    GenGroup,
    GenItem,
    GenSection,
    IELTSReadingGenerator,
    check_section,
    default_plan,
)
from osamu_dazai.ielts.model import ReadingSection
from osamu_dazai.providers import ProviderRegistry
from osamu_dazai.providers.llm import MockProvider
from tests.fixtures.ielts_sample import sample_test

SHORT = ((150, 400), (150, 400), (150, 400))  # fixture passages are short
PLAN = default_plan(("tulips", "urban bees", "sleep"), words=SHORT)


def to_gen(section: ReadingSection) -> GenSection:
    """What a well-behaved LLM would return for an existing section (no numbers, no labels)."""
    groups = []
    for g in section.groups:
        start = g.range[0]
        if g.type is QT.MULTIPLE_CHOICE_MULTI:
            q = g.questions[0]
            groups.append(GenGroup(stem=q.stem, shared_options=[o.text for o in q.options],
                                   items=[GenItem(stem="", answers=q.answer.accepted, evidence="")]))
            continue
        shared = [] if g.type is QT.MATCHING_INFORMATION else [o.text for o in g.shared_options]
        summary = ""
        if g.completion_form is CF.SUMMARY:
            summary = re.sub(r"\{(\d+)\}", lambda m: "{" + str(int(m.group(1)) - start + 1) + "}", g.body[0])
        items = [GenItem(stem="" if g.type is QT.MATCHING_HEADINGS else q.stem,
                         options=[o.text for o in q.options], answers=q.answer.accepted, evidence="")
                 for q in g.questions]
        groups.append(GenGroup(shared_options=shared, summary_title=g.list_title if summary else "",
                               summary_text=summary, items=items))
    return GenSection(title=section.passage.title, paragraphs=[p.text for p in section.passage.paragraphs],
                      groups=groups)


def fixture_replies() -> list[str]:
    return [to_gen(s).model_dump_json() for s in sample_test().sections]


def registry(mock: MockProvider) -> ProviderRegistry:
    reg = ProviderRegistry()
    reg.register_llm(mock)
    return reg


def test_fixture_sections_pass_content_checks():
    for spec, section in zip(PLAN.passages, sample_test().sections, strict=True):
        assert check_section(to_gen(section), spec) == []


def test_generate_assemble_validate_export(tmp_path):
    mock = MockProvider().queue(STAGE, *fixture_replies())
    report = asyncio.run(IELTSReadingGenerator(registry(mock)).generate(PLAN))
    assert report.validation.passed, [i.render() for i in report.validation.issues]
    assert report.test.question_count() == 40
    assert report.attempts == {1: 1, 2: 1, 3: 1}
    # numbering, labels and instructions come from code, not the model
    p = parse(read_docx(_export(report.test, tmp_path)).lines)
    assert sorted(n for it in p.items() for n in it.numbers) == list(range(1, 41))
    assert [g.label for g in p.groups()][:3] == ["Questions 1-5", "Questions 6-7", "Questions 8-13"]
    # every prompt carried the prompt version and the stage
    assert all(r.prompt_version == "ielts.reading.v1" and r.stage == STAGE for r in mock.requests)


def _export(test, tmp_path):
    path = tmp_path / "generated.docx"
    assert export_reading_test(test, path).passed
    assert validate_docx(path).passed
    return path


def test_bad_content_is_sent_back_and_fixed():
    good = fixture_replies()
    bad = GenSection.model_validate_json(good[1])
    bad.groups[3].items[0].answers = ["parasite worm"]  # not in the passage
    bad.groups[0].items[0].options = bad.groups[0].items[0].options[:3]  # MC with only 3 options
    mock = MockProvider().queue(STAGE, good[0], bad.model_dump_json(), good[1], good[2])
    report = asyncio.run(IELTSReadingGenerator(registry(mock)).generate(PLAN))
    assert report.attempts[2] == 2 and report.validation.passed
    feedback = mock.requests[2].messages[-1].content
    assert "does not appear in the passage" in feedback and "needs exactly 4 options" in feedback


def test_gives_up_after_max_attempts():
    bad = GenSection.model_validate_json(fixture_replies()[0])
    bad.paragraphs = bad.paragraphs[:3]
    mock = MockProvider().queue(STAGE, *[bad.model_dump_json()] * 2)
    with pytest.raises(GenerationFailed) as e:
        asyncio.run(IELTSReadingGenerator(registry(mock), max_attempts=2).generate(PLAN))
    assert any("exactly 5 paragraphs" in p for p in e.value.problems)


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda g: setattr(g.groups[0].items[1], "answers", ["i"]), "different heading"),
        (lambda g: setattr(g.groups[0].items[0], "answers", ["xi"]), "not a heading numeral"),
        (lambda g: setattr(g.groups[1].items[0], "answers", ["A"]), "needs 2 different letters"),
        (lambda g: setattr(g.groups[2].items[0], "answers", ["MAYBE"]), "must be one of"),
        (lambda g: [setattr(it, "answers", ["TRUE"]) for it in g.groups[2].items], "use each of the three"),
        (lambda g: setattr(g.groups[0], "shared_options", g.groups[0].shared_options[:5]), "at least 7 headings"),
    ],
)
def test_content_checks_passage_1(mutate, expected):
    gen = to_gen(sample_test().sections[0])
    mutate(gen)
    assert any(expected in p for p in check_section(gen, PLAN.passages[0]))


def test_content_checks_passage_3():
    gen = to_gen(sample_test().sections[2])
    gen.groups[1].summary_text = gen.groups[1].summary_text.replace("{2}", "{9}")
    gen.groups[3].items[1].answers = ["a short daytime nap"]  # 4 words > THREE
    gen.groups[3].items[0].stem = "The animals used were rats."
    problems = check_section(gen, PLAN.passages[2])
    assert any("{1}…{4} in order" in p for p in problems)
    assert any("exceeds NO MORE THAN THREE WORDS" in p for p in problems)
    assert any("must end with '?'" in p for p in problems)
