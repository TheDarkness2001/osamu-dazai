"""Planner → learning graph → curriculum, with a mock LLM."""

import asyncio

import pytest

from osamu_dazai.domain import Course, Lang, Project, ProjectKind
from osamu_dazai.domain.graph import ConceptGraph
from osamu_dazai.pipeline.curriculum import (
    CURRICULUM_STAGE,
    GRAPH_STAGE,
    BriefNotConfirmed,
    CurriculumArchitect,
    assemble_course,
    build_graph,
    validate_course,
)
from osamu_dazai.pipeline.llm_stage import StageFailed
from osamu_dazai.pipeline.planner import STAGE as PLANNER_STAGE
from osamu_dazai.pipeline.planner import EducationalPlanner, accept_all, confirm
from osamu_dazai.providers import ProviderRegistry
from osamu_dazai.providers.llm import MockProvider
from osamu_dazai.storage import EntityRepository, ProjectRepository, init_db, make_engine, session_factory
from tests.fixtures.course_sample import REQUEST, brief_draft, curriculum_draft, graph_draft

run = asyncio.run


def reg(mock: MockProvider) -> ProviderRegistry:
    r = ProviderRegistry()
    r.register_llm(mock)
    return r


def brief(weeks=6, per_week=3):
    mock = MockProvider().queue(PLANNER_STAGE, brief_draft(duration_weeks=weeks, lessons_per_week=per_week)
                                .model_dump_json())
    return accept_all(run(EducationalPlanner(reg(mock)).plan(REQUEST)).brief)


# ---- planner ---------------------------------------------------------------
def test_planner_infers_but_does_not_confirm():
    mock = MockProvider().queue(PLANNER_STAGE, brief_draft().model_dump_json())
    res = run(EducationalPlanner(reg(mock)).plan(REQUEST, known={"subject": "Python"}))
    b = res.brief
    assert b.subject.value == "Python" and b.subject.origin.value == "confirmed"
    assert "schedule" in b.unconfirmed_fields() and "subject" not in b.unconfirmed_fields()
    assert b.schedule.value.total_lessons == 78  # 6 months × 3 per week
    lv = b.languages.value
    assert (lv.explanation, lv.terminology, lv.assessment) == (Lang.UZ, Lang.EN, Lang.UZ)
    assert res.questions[0] == "Do students have their own computers?"
    assert "Already confirmed" in mock.requests[0].messages[0].content


def test_planner_retries_invalid_draft():
    bad = brief_draft(age_min=17, age_max=13, outputs=["student_book", "hologram"])
    mock = MockProvider().queue(PLANNER_STAGE, bad.model_dump_json(), brief_draft().model_dump_json())
    res = run(EducationalPlanner(reg(mock)).plan(REQUEST))
    assert res.attempts == 2
    feedback = mock.requests[1].messages[-1].content
    assert "age_min is greater than age_max" in feedback and "hologram" in feedback


def test_confirm_with_new_value():
    mock = MockProvider().queue(PLANNER_STAGE, brief_draft().model_dump_json())
    b = run(EducationalPlanner(reg(mock)).plan(REQUEST)).brief
    b = confirm(b, level="intermediate", goal=True)
    assert b.level.value == "intermediate" and b.level.origin.value == "confirmed"
    assert b.goal.value == "Teach programming from zero"
    with pytest.raises(ValueError):
        confirm(b, colour="red")


# ---- curriculum ---------------------------------------------------------------
def design(b, *replies_graph_then_curriculum, **kw):
    mock = MockProvider()
    graph_replies, curriculum_replies = replies_graph_then_curriculum
    mock.queue(GRAPH_STAGE, *[r.model_dump_json() for r in graph_replies])
    mock.queue(CURRICULUM_STAGE, *[r.model_dump_json() for r in curriculum_replies])
    return run(CurriculumArchitect(reg(mock)).design(b, "prj_1", **kw)), mock


def test_design_small_course():
    result, _ = design(brief(), [graph_draft(12)], [curriculum_draft(12, 3, 6)])
    course, graph = result.course, result.graph
    assert result.validation.passed, [i.problem for i in result.validation.issues]
    assert len(course.all_lessons()) == 18 and [m.number for m in course.modules] == [1, 2, 3]
    assert [les.number for les in course.all_lessons()] == list(range(1, 19))
    assert all(les.minutes == 45 for les in course.all_lessons())
    assert graph.course_id == course.id and course.concept_graph_id == graph.id
    assert graph.by_id()["con_variables"].learning_objectives  # back-linked
    assert course.lesson_objectives[0].lang is Lang.UZ
    assert result.attempts == {GRAPH_STAGE: 1, CURRICULUM_STAGE: 1}


def test_spec_example_six_months_three_per_week():
    """Spec §7: Python, beginner, 13–16, 6 months, 3 classes/week, Uzbek."""
    result, mock = design(brief(26, 3), [graph_draft()], [curriculum_draft(24, 6, 13)])
    assert result.validation.passed, [i.problem for i in result.validation.issues]
    assert len(result.course.all_lessons()) == 78 and len(result.graph.concepts) == 24
    prompt = mock.requests[1].messages[0].content
    assert "exactly 78 lessons" in prompt and "Uzbek (Latin script)" in prompt
    assert "variables: Variables (prerequisites: print_output)" in prompt


def test_unconfirmed_brief_is_refused():
    mock = MockProvider().queue(PLANNER_STAGE, brief_draft().model_dump_json())
    b = run(EducationalPlanner(reg(mock)).plan(REQUEST)).brief
    with pytest.raises(BriefNotConfirmed, match="schedule"):
        run(CurriculumArchitect(reg(MockProvider())).design(b, "prj_1"))


def test_cyclic_graph_is_sent_back():
    cyclic = graph_draft(12)
    cyclic.concepts[1].prerequisites = ["data_types"]  # variables ⇄ data types
    result, mock = design(brief(), [cyclic, graph_draft(12)], [curriculum_draft(12, 3, 6)])
    assert result.attempts[GRAPH_STAGE] == 2
    assert "Prerequisite cycle" in mock.requests[1].messages[-1].content


def test_prerequisite_violation_is_sent_back():
    bad = curriculum_draft(12, 3, 6)
    first, later = bad.modules[0].lessons[0], bad.modules[2].lessons[0]
    first.introduces, later.introduces = later.introduces, first.introduces  # loops before printing
    result, mock = design(brief(), [graph_draft(12)], [bad, curriculum_draft(12, 3, 6)])
    assert result.attempts[CURRICULUM_STAGE] == 2
    feedback = mock.requests[2].messages[-1].content
    assert "is taught before its prerequisite" in feedback


def test_gives_up_on_wrong_lesson_count():
    wrong = curriculum_draft(12, 3, 5)  # 15 lessons, schedule says 18
    with pytest.raises(StageFailed) as e:
        design(brief(), [graph_draft(12)], [wrong, wrong, wrong])
    assert any("15 lessons, but the schedule has 18" in p for p in e.value.problems)


def test_validate_course_catches_coverage_and_spacing():
    b = brief()
    graph, ids = build_graph(graph_draft(12), "c")
    draft = curriculum_draft(12, 3, 6)
    draft.assessments = [a for a in draft.assessments if "build_project" not in a.objectives]
    for m in draft.modules:
        for les in m.lessons:
            if les.kind == "review":
                les.kind = "teach"
            for o in les.objectives:
                o.supports = [s for s in o.supports if s != "debug_code"] or ["write_programs"]
                o.verb = "understand"
    course = assemble_course(draft, b, "p", graph, ids)
    codes = {i.code for i in validate_course(course, graph, max_review_gap=4).issues}
    assert {"curriculum.objective_unassessed", "curriculum.objective_untaught", "curriculum.vague_objective",
            "curriculum.review_gap"} <= codes


def test_course_and_graph_persist():
    result, _ = design(brief(), [graph_draft(12)], [curriculum_draft(12, 3, 6)])
    engine = make_engine()
    init_db(engine)
    with session_factory(engine)() as s:
        project = ProjectRepository(s).save(Project(name="Python (UZ)", kind=ProjectKind.COURSE))
        repo = EntityRepository(s)
        course = result.course.model_copy(update={"project_id": project.id})
        repo.save(course, project.id)
        repo.save(result.graph, project.id)
        assert repo.get(Course, course.id) == course
        assert [x.id for x in repo.list(ConceptGraph, project.id, parent_id=course.id)] == [result.graph.id]
