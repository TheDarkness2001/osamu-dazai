"""Teacher guide generation (mock LLM)."""

import asyncio

import pytest

from osamu_dazai.documents.markdown import render_teacher_guide
from osamu_dazai.domain.common import Lang
from osamu_dazai.domain.knowledge import KnowledgeBase
from osamu_dazai.pipeline.book import STAGE as BOOK_STAGE
from osamu_dazai.pipeline.book import BookWriter, plan_chapters
from osamu_dazai.pipeline.curriculum import assemble_course, build_graph
from osamu_dazai.pipeline.llm_stage import StageFailed
from osamu_dazai.pipeline.teacher import (
    STAGE,
    TeacherContext,
    TeacherGuideWriter,
    check_teacher_chapter,
    longest_copied_run,
    shingles,
)
from osamu_dazai.providers import ProviderRegistry
from osamu_dazai.providers.llm import MockProvider
from tests.fixtures.book_sample import FILLER, chapter_draft
from tests.fixtures.course_sample import curriculum_draft, graph_draft
from tests.fixtures.teacher_sample import lesson_draft, teacher_draft
from tests.test_course_design import brief

run = asyncio.run


def registry(stage: str, *replies) -> tuple[ProviderRegistry, MockProvider]:
    mock = MockProvider().queue(stage, *[r.model_dump_json() for r in replies])
    reg = ProviderRegistry()
    reg.register_llm(mock)
    return reg, mock


@pytest.fixture(scope="module")
def setup():
    graph, ids = build_graph(graph_draft(12), "c")
    course = assemble_course(curriculum_draft(12, 3, 6), brief(), "prj_1", graph, ids)
    plans = plan_chapters(course, graph)
    reg, _ = registry(BOOK_STAGE, *[chapter_draft(p, graph) for p in plans])
    book = run(BookWriter(reg).write(course, graph, KnowledgeBase(project_id="p"), words_per_chapter=40)).book
    return course, graph, book, plans


def ctx(setup, n=0):
    course, graph, book, plans = setup
    return TeacherContext(plan=plans[n], chapter=book.chapters[n], kb=KnowledgeBase(project_id="p"), lang=Lang.UZ)


def test_full_guide_and_rendering(setup):
    course, graph, book, plans = setup
    reg, mock = registry(STAGE, *[teacher_draft(p) for p in plans])
    res = run(TeacherGuideWriter(reg).write(course, graph, book, KnowledgeBase(project_id="p"),
                                            teaching_style="project-based"))
    guide = res.guide
    assert len(guide.lessons) == 18 and res.attempts == {1: 1, 2: 1, 3: 1}
    first = guide.lessons[0]
    assert first.lesson_id == "les_1" and first.chapter_id == book.chapters[0].id
    assert first.planned_minutes == 45 and first.objectives == course.all_lessons()[0].objective_ids
    prompt = mock.requests[0].messages[0].content
    assert "Lesson 1 (teaching, 45 min)" in prompt and "Teaching style: project-based" in prompt
    assert "do not repeat them" in prompt

    md = render_teacher_guide(guide, course, book)
    assert "### Dars 1. Lesson 1 (45 daq)" in md and "| daq | Faoliyat | O‘qituvchi | O‘quvchilar |" in md
    assert "*Kutilgan javob:* NameError xatosi" in md
    # exercise answers come from the student book, not the model
    assert "### Javoblar — bob 1" in md and "**Ekranga matn chiqaradi.**" in md
    assert md.count("### Javoblar — bob") == 3


def test_timing_must_add_up(setup):
    d = teacher_draft(ctx(setup).plan)
    d.lessons[0].sequence[1].minutes += 10
    assert any("add up to 55 minutes, the lesson is 45" in p for p in check_teacher_chapter(d, ctx(setup)))


def test_teaching_lessons_need_substance(setup):
    d = teacher_draft(ctx(setup).plan)
    d.lessons[0] = lesson_draft(d.lessons[0].lesson_number, 45, questions=[], misconceptions=[], support=[],
                                homework_key="")
    problems = "\n".join(check_teacher_chapter(d, ctx(setup)))
    for expected in ("at least 2 questions", "misconception", "support and extension", "homework needs a key"):
        assert expected in problems


def test_review_lessons_are_lighter(setup):
    c = ctx(setup)
    assert any(les.is_review or les.is_assessment for les in c.plan.lessons)
    assert check_teacher_chapter(teacher_draft(c.plan), c) == []


def test_copying_the_student_book_is_rejected(setup):
    c = ctx(setup)
    d = teacher_draft(c.plan)
    d.lessons[0].explanation_points = [FILLER]  # one sentence lifted straight from the book
    problems = "\n".join(check_teacher_chapter(d, c))
    assert "just restates the student book" in problems
    # quoting a few words of the book inside real teaching advice is fine
    d.lessons[0].explanation_points = ["Kitobdagi 'muhim gʻoyalarini oddiy misollar' iborasini sinfga "
                                       "o‘qib bering, so‘ng o‘quvchilardan o‘z misolini so‘rang"]
    assert check_teacher_chapter(d, c) == []


def test_wrong_lesson_set(setup):
    c = ctx(setup)
    d = teacher_draft(c.plan)
    d.lessons = d.lessons[:-1]
    assert "give exactly one plan per lesson" in check_teacher_chapter(d, c)[0]


def test_failures_are_fed_back_then_fixed(setup):
    course, graph, book, plans = setup
    bad = teacher_draft(plans[0])
    bad.lessons[0].sequence[0].minutes = 1
    reg, mock = registry(STAGE, bad, *[teacher_draft(p) for p in plans])
    res = run(TeacherGuideWriter(reg).write(course, graph, book, KnowledgeBase(project_id="p")))
    assert res.attempts[1] == 2
    assert "timed steps add up to 41 minutes" in mock.requests[1].messages[-1].content


def test_gives_up(setup):
    course, graph, book, plans = setup
    bad = teacher_draft(plans[0], homework_key="")
    reg, _ = registry(STAGE, bad, bad, bad)
    with pytest.raises(StageFailed):
        run(TeacherGuideWriter(reg).write(course, graph, book, KnowledgeBase(project_id="p")))


def test_chapter_plan_mismatch_is_an_error(setup):
    course, graph, book, _ = setup
    reg, _ = registry(STAGE)
    with pytest.raises(ValueError, match="chapter plan"):
        run(TeacherGuideWriter(reg).write(course, graph, book, KnowledgeBase(project_id="p"), n_chapters=5))


def test_shingle_helpers():
    src = shingles("one two three four five six seven eight nine ten eleven twelve")
    assert longest_copied_run("zero one two three four five six seven eight nine ten end", src) == 10
    assert longest_copied_run("completely different words that share nothing at all here", src) == 0
