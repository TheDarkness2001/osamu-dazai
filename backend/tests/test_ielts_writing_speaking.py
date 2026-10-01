import asyncio
import xml.etree.ElementTree as ET

import pytest

from osamu_dazai.ielts.bands import CriterionScore, estimated_band, round_half, writing_overall
from osamu_dazai.ielts.speaking import (
    STAGE as SPEAKING_STAGE,
)
from osamu_dazai.ielts.speaking import (
    IELTSSpeakingGenerator,
    SpeakingSpec,
    check_speaking,
    render_cue_card,
    render_examiner_script,
    render_model_answers,
)
from osamu_dazai.ielts.writing import (
    STAGE as WRITING_STAGE,
)
from osamu_dazai.ielts.writing import (
    IELTSWritingGenerator,
    WritingSpec,
    check_writing,
    render_samples,
    render_tasks,
    task1_figure,
)
from osamu_dazai.providers import ProviderRegistry
from osamu_dazai.providers.llm import MockProvider
from tests.fixtures.writing_speaking_sample import speaking_draft, writing_draft

run = asyncio.run


def reg(stage, *replies):
    mock = MockProvider().queue(stage, *[r.model_dump_json() for r in replies])
    r = ProviderRegistry()
    r.register_llm(mock)
    return r, mock


# ---- bands ------------------------------------------------------------------------
def test_band_arithmetic():
    assert [round_half(x) for x in (6.1, 6.25, 6.5, 6.74, 6.75)] == [6.0, 6.5, 6.5, 6.5, 7.0]
    s = [CriterionScore(criterion=c, band=b, comment="x") for c, b in zip("abcd", (7, 8, 7, 8), strict=True)]
    assert estimated_band(s) == 7.5
    assert writing_overall(6.0, 7.0) == 6.5  # Task 2 counts double: 20/3 = 6.67


# ---- writing ------------------------------------------------------------------------
def test_writing_fixture_passes():
    assert check_writing(writing_draft(), "academic") == []


def test_writing_generation_and_rendering():
    r, mock = reg(WRITING_STAGE, writing_draft())
    ws, attempts = run(IELTSWritingGenerator(r).generate(WritingSpec("academic", "commuting", "cycle lanes")))
    assert attempts == 1 and ws.task1.min_words == 150 and ws.task2.minutes == 40
    tasks = render_tasks(ws)
    assert "You should spend about 20 minutes on this task." in tasks and "Write at least 250 words." in tasks
    assert "Summarise the information by selecting" in tasks
    svg = task1_figure(ws)
    assert "Bus" in "".join(ET.fromstring(svg.svg).itertext())
    samples = render_samples(ws)
    assert "| **Estimated band** | **7.5** |" in samples and "not official IELTS scores" in samples
    assert "Task 1 criteria, in order: ['Task Achievement'" in mock.requests[0].messages[0].content


def test_invented_figures_are_caught():
    d = writing_draft()
    d.task1.samples[0].text = d.task1.samples[0].text.replace("reaching 30%", "reaching 27%")
    problems = check_writing(d, "academic")
    assert any("quotes figures not in the visual: ['27']" in p for p in problems)


def test_derived_figures_are_allowed():
    d = writing_draft()
    assert "fell by 5 percentage points" in d.task1.samples[0].text  # 40 − 35, a derived figure
    assert check_writing(d, "academic") == []


@pytest.mark.parametrize(("mutate", "expected"), [
    (lambda d: setattr(d.task1.samples[1], "target_band", 7.5), "two or more different band levels"),
    (lambda d: setattr(d.task2.samples[0].scores[0], "band", 4), "criterion scores give band"),
    (lambda d: setattr(d.task2.samples[0], "text", " ".join(d.task2.samples[0].text.split()[:200])),
     "must have at least 250"),
    (lambda d: setattr(d.task1, "visual", None), "needs a visual"),
    (lambda d: setattr(d.task1.samples[0], "improvements", []), "strengths and improvements"),
    (lambda d: d.task2.samples[1].scores.reverse(), "one score per criterion"),
])
def test_writing_checks(mutate, expected):
    d = writing_draft()
    mutate(d)
    assert any(expected in p for p in check_writing(d, "academic"))


def test_under_length_low_band_cannot_score_high_on_task():
    d = writing_draft()
    s = d.task2.samples[1]  # band 5.5
    s.text = " ".join(s.text.split()[:180])
    s.scores[0].band = 6
    assert any("under-length response cannot score above 5" in p for p in check_writing(d, "academic"))


def test_general_training_letter_rules():
    d = writing_draft()
    d.task1.visual = None
    d.task1.bullets = ["explain the problem", "say what you want"]
    problems = check_writing(d, "general_training")
    assert any("exactly 3 bullet points" in p for p in problems)


# ---- speaking -----------------------------------------------------------------------
def test_speaking_fixture_and_rendering():
    assert check_speaking(speaking_draft(), target_band=7) == []
    r, _ = reg(SPEAKING_STAGE, speaking_draft())
    test, attempts = run(IELTSSpeakingGenerator(r).generate(SpeakingSpec(theme="teachers and education")))
    assert attempts == 1
    script = render_examiner_script(test)
    assert "## Part 2 (3–4 minutes)" in script and "One minute to prepare" in script
    assert render_cue_card(test).startswith("**Describe a teacher who has influenced you.**")
    assert "can only be judged when the answer is spoken" in render_model_answers(test)


@pytest.mark.parametrize(("mutate", "expected"), [
    (lambda d: setattr(d.part2, "task", "Talk about a teacher."), "must start with 'Describe'"),
    (lambda d: setattr(d.part2, "explain", "Why was the teacher important?"), "'and explain"),
    (lambda d: setattr(d, "part3", d.part3[:2]), "4-6 discussion questions"),
    (lambda d: d.part1[0].questions.append("Tell me about your street."), "not questions"),
    (lambda d: setattr(d.model_answers[0], "question", "What is your name?"), "copy it exactly"),
    (lambda d: setattr(d.model_answers[2], "answer", "She was nice and I liked her lessons a lot."),
     "Part 2 answers should be 180-320 words"),
    (lambda d: setattr(d.model_answers[0].scores[3], "comment", "Good pronunciation."), "what to listen for"),
    (lambda d: setattr(d, "model_answers", [a for a in d.model_answers if a.part != 3]), "Parts 1, 2 and 3"),
])
def test_speaking_checks(mutate, expected):
    d = speaking_draft()
    mutate(d)
    assert any(expected in p for p in check_speaking(d, target_band=7))


def test_speaking_feedback_loop():
    bad = speaking_draft()
    bad.part2.rounding_off = []
    r, mock = reg(SPEAKING_STAGE, bad, speaking_draft())
    _, attempts = run(IELTSSpeakingGenerator(r).generate(SpeakingSpec(theme="teachers")))
    assert attempts == 2 and "rounding-off" in mock.requests[1].messages[-1].content
