"""Question/assessment engine: ported shuffling, balanced versions, validator, generator, rendering."""

import asyncio
from collections import Counter

import pytest

from osamu_dazai.documents.markdown import render_answer_key, render_assessment
from osamu_dazai.domain.common import Lang
from osamu_dazai.domain.knowledge import KnowledgeBase
from osamu_dazai.domain.questions import Answer, Assessment, AssessmentKind, Option, Question, QuestionGroup, QuestionType
from osamu_dazai.pipeline.curriculum import assemble_course, build_graph
from osamu_dazai.providers import ProviderRegistry
from osamu_dazai.providers.llm import MockProvider
from osamu_dazai.questions.generator import STAGE, AssessmentGenerator, assemble, blueprint, check_draft
from osamu_dazai.questions.shuffle import answer_positions, longest_answer_bias, make_versions, mulberry32, shuffled
from osamu_dazai.questions.validate import validate_assessment
from tests.fixtures.assessment_sample import assessment_draft
from tests.fixtures.course_sample import curriculum_draft, graph_draft
from tests.test_course_design import brief

run = asyncio.run
QT = QuestionType
KB = KnowledgeBase(project_id="p")


@pytest.fixture(scope="module")
def course_graph():
    graph, ids = build_graph(graph_draft(12), "c")
    return assemble_course(curriculum_draft(12, 3, 6), brief(), "prj_1", graph, ids), graph


# ---- ported RNG (values produced by the original JavaScript under node) -------------
def test_mulberry32_matches_javascript_original():
    g = mulberry32(42)
    assert [g(), g()] == [0.6011037519201636, 0.44829055899754167]
    assert shuffled(list(range(10)), mulberry32(42)) == [0, 7, 3, 5, 2, 1, 8, 9, 4, 6]
    assert shuffled(list(range(10)), mulberry32(1042)) == [6, 1, 9, 8, 7, 5, 0, 4, 3, 2]


# ---- versions ---------------------------------------------------------------------
def mc(n: int, correct: str = "A", texts=("alpha", "beta", "gamma", "delta")) -> Question:
    return Question(number=n, type=QT.MULTIPLE_CHOICE, stem=f"Question {n} about topic {n}?",
                    options=[Option(label=lab, text=f"{t} {n}") for lab, t in zip("ABCD", texts, strict=True)],
                    answer=Answer(accepted=[correct]))


def master(n_mc: int = 9) -> Assessment:
    tf = Question(number=n_mc + 1, type=QT.TRUE_FALSE, stem="The sky is green.", answer=Answer(accepted=["FALSE"]))
    return Assessment(project_id="p", kind=AssessmentKind.QUIZ, title="Quiz 1", groups=[
        QuestionGroup(type=QT.MULTIPLE_CHOICE, questions=[mc(i) for i in range(1, n_mc + 1)]),
        QuestionGroup(type=QT.TRUE_FALSE, questions=[tf])])


def correct_text(q: Question) -> str:
    return next(o.text for o in q.options if o.label == q.answer.accepted[0])


def test_versions_are_balanced_correct_and_deterministic():
    m = master(9)  # every correct answer is "A" in the master — the worst case
    versions = make_versions(m, 4)
    assert [v.version_label for v in versions] == ["A", "B", "C", "D"]
    master_correct = {q.stem: correct_text(q) for q in m.groups[0].questions}
    for v in versions:
        counts = answer_positions(v)
        assert max(counts.values()) - min(counts.values()) <= 1 and sum(counts.values()) == 9
        for q in v.groups[0].questions:
            assert correct_text(q) == master_correct[q.stem]  # the key follows the option
        assert [q.number for g in v.groups for q in g.questions] == list(range(1, 11))
        assert validate_assessment(v).passed
        assert v.source_assessment_id == m.id and v.groups[1].questions[0].answer.accepted == ["FALSE"]
    orders = {tuple(q.stem for q in v.groups[0].questions) for v in versions}
    assert len(orders) == 4
    again = make_versions(m, 4)
    assert [v.model_dump(exclude={"created_at", "updated_at"}) for v in again] == \
           [v.model_dump(exclude={"created_at", "updated_at"}) for v in versions]


def test_longest_answer_audit():
    leaky = [mc(i, texts=("the clearly correct and much longer answer", "no", "nope", "nah")) for i in range(1, 9)]
    assert len(longest_answer_bias(leaky)) == 8
    fair = [mc(i, texts=("right", "wrong one", "wrong two", "wrong 3")) for i in range(1, 9)]
    assert longest_answer_bias(fair) == []
    assert longest_answer_bias(leaky[:4]) == []  # too few items to judge


# ---- validator ----------------------------------------------------------------------
def test_validator_catches_structural_problems():
    qs = [
        mc(1, correct="E"),
        Question(number=1, type=QT.MULTIPLE_CHOICE, stem="Dup number?", answer=Answer(accepted=["A"]),
                 options=[Option(label="A", text="x"), Option(label="B", text="x")]),
        Question(number=3, type=QT.TRUE_FALSE, stem="Statement.", answer=Answer(accepted=["MAYBE"])),
        Question(number=4, type=QT.COMPLETION, stem="No blank here.", answer=Answer(accepted=["x"])),
        Question(number=5, type=QT.CODE, stem="Write code.", answer=Answer(accepted=["print("])),
        Question(number=6, type=QT.ESSAY, stem="Discuss.", answer=Answer(accepted=["…"])),
        Question(number=7, type=QT.SHORT_ANSWER, stem="Question 1 about topic 1?", answer=Answer(accepted=[" "])),
    ]
    a = Assessment(project_id="p", kind=AssessmentKind.QUIZ, title="Q", groups=[QuestionGroup(type=QT.MULTIPLE_CHOICE,
                                                                                             questions=qs)])
    codes = {i.code for i in validate_assessment(a, code_language="python").issues}
    for expected in ("question.answer_wrong_type", "question.duplicate_number", "question.mc_too_few_options",
                     "question.mc_duplicate_options", "question.missing_number", "question.completion_no_blank",
                     "question.code_answer_invalid", "question.essay_without_rubric", "question.answer_missing"):
        assert expected in codes, expected


# ---- generator ------------------------------------------------------------------------
def test_blueprint_respects_teaching_order(course_graph):
    course, graph = course_graph
    bp = blueprint(course, graph, course.assessment_plan[0])
    taught_by_6 = {c for les in course.all_lessons() if les.number <= 6 for c in les.concept_ids}
    assert set(bp.taught) == taught_by_6 and bp.mix == {"multiple_choice": 7, "short_answer": 3}
    assert {o.id for o in bp.objectives} == set(course.assessment_plan[0].objective_ids)
    assert blueprint(course, graph, course.assessment_plan[-1]).kind == "project"
    assert blueprint(course, graph, course.assessment_plan[0], include_code=True).mix["code"] == 2


def generator(*replies):
    mock = MockProvider().queue(STAGE, *[r.model_dump_json() for r in replies])
    reg = ProviderRegistry()
    reg.register_llm(mock)
    return AssessmentGenerator(reg), mock


def test_generate_whole_assessment_plan(course_graph):
    course, graph = course_graph
    drafts = [assessment_draft(blueprint(course, graph, item, include_code=True)) for item in course.assessment_plan]
    gen, mock = generator(*drafts)
    res = run(gen.generate_all(course, graph, KB, code_language="python"))
    assert len(res.assessments) == 4 and set(res.attempts.values()) == {1}
    quiz, project = res.assessments[0], res.assessments[-1]
    assert [g.type for g in quiz.groups] == [QT.MULTIPLE_CHOICE, QT.SHORT_ANSWER, QT.CODE]
    assert [q.number for g in quiz.groups for q in g.questions] == list(range(1, 11))
    assert quiz.kind is AssessmentKind.QUIZ and quiz.duration_minutes == 20
    assert project.kind is AssessmentKind.PROJECT and len(project.rubrics[0].criteria) == 3
    assert all(validate_assessment(a, code_language="python").passed for a in res.assessments)
    # the fixture model put every correct answer at "A"; the master is rebalanced anyway
    counts = answer_positions(quiz)
    assert sum(counts.values()) == 7 and max(counts.values()) - min(counts.values()) <= 1
    prompt = mock.requests[0].messages[0].content
    assert "Exactly these question types: 7 × multiple_choice, 1 × short_answer, 2 × code" in prompt
    assert "in Uzbek (Latin script)" in prompt and "Code answers are written in python" in prompt


@pytest.mark.parametrize(("mutate", "expected"), [
    (lambda d: setattr(d.questions[0], "concepts", ["con_for_loop"]), "not yet taught by lesson 6"),
    (lambda d: [setattr(q, "objectives", [d.questions[0].objectives[0]]) for q in d.questions], "is not assessed"),
    (lambda d: d.questions.pop(), "question types must be exactly"),
    (lambda d: [setattr(q, "bloom_level", "remember") for q in d.questions], "apply-level or higher"),
    (lambda d: setattr(d.questions[0], "options", d.questions[0].options[:3]), "exactly 4 options"),
    (lambda d: setattr(d.questions[1], "stem", d.questions[0].stem), "Same question as number 1"),
])
def test_generator_checks(course_graph, mutate, expected):
    course, graph = course_graph
    bp = blueprint(course, graph, course.assessment_plan[0])
    d = assessment_draft(bp)
    assert check_draft(d, bp, course, KB, Lang.UZ) == []
    mutate(d)
    assert any(expected in p for p in check_draft(d, bp, course, KB, Lang.UZ))


def test_answer_leak_is_sent_back(course_graph):
    course, graph = course_graph
    bp = blueprint(course, graph, course.assessment_plan[0])
    leaky = assessment_draft(bp)
    for q in leaky.questions:
        if q.type == "multiple_choice":
            q.options[0] = q.options[0] + " — bu eng to‘liq, batafsil va uzun tushuntirilgan variant"
    gen, mock = generator(leaky, assessment_draft(bp))
    _, attempts = run(gen.generate(course, graph, course.assessment_plan[0], KB))
    assert attempts == 2 and "correct option is the longest" in mock.requests[1].messages[-1].content


# ---- rendering ----------------------------------------------------------------------------
def test_student_copy_and_answer_key(course_graph):
    course, graph = course_graph
    bp = blueprint(course, graph, course.assessment_plan[0], mix={"multiple_choice": 2, "true_false": 1,
                                                                  "short_answer": 1})
    a = assemble(assessment_draft(bp), bp, course)
    v = make_versions(a, 2)[1]
    student = render_assessment(v, Lang.UZ)
    assert student.startswith(f"# {a.title} — Variant B") and "## Test savollari" in student
    assert "☐ To‘g‘ri    ☐ Noto‘g‘ri" in student and "Ism: ____" in student
    assert "Birinchi variant to‘g‘ri" not in student  # explanations stay out of the student copy
    key = render_answer_key(v, Lang.UZ)
    assert "Javoblar kaliti" in key and "**Noto‘g‘ri**" in key and "shuningdek qabul qilinadi" in key
    letters = Counter(q.answer.accepted[0] for g in v.groups for q in g.questions if q.type is QT.MULTIPLE_CHOICE)
    assert all(f"**{x}**" in key for x in letters)
