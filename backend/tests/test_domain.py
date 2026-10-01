import pytest
from pydantic import TypeAdapter, ValidationError

from osamu_dazai.domain import (
    Answer,
    Assessment,
    AssessmentKind,
    Chapter,
    Concept,
    ConceptGraph,
    Course,
    CourseBrief,
    KnowledgeBase,
    Lang,
    LanguageSettings,
    Option,
    Question,
    QuestionGroup,
    QuestionType,
    Section,
    SectionKind,
    Source,
    SourceKind,
    StudentBook,
    ValidationIssue,
    ValidationResult,
    VerificationMethod,
)
from osamu_dazai.domain.common import Severity
from osamu_dazai.domain.content import Block, CodeBlock, ParagraphBlock
from osamu_dazai.domain.project import BriefField, FieldOrigin, Schedule
from osamu_dazai.domain.validation import Location


def test_ids_are_prefixed_and_unique():
    a, b = Concept(name="Variables"), Concept(name="Loops")
    assert a.id.startswith("con_") and a.id != b.id


def test_unknown_fields_rejected():
    with pytest.raises(ValidationError):
        Concept(name="x", colour="red")


# ---- learning graph ------------------------------------------------------
def test_concept_cannot_require_itself():
    with pytest.raises(ValidationError):
        Concept(id="con_a", name="A", prerequisites=["con_a"])


def test_graph_rejects_dangling_prerequisite():
    with pytest.raises(ValidationError, match="unknown concepts"):
        ConceptGraph(course_id="crs_1", concepts=[Concept(id="con_b", name="B", prerequisites=["con_x"])])


def test_graph_rejects_duplicate_ids():
    with pytest.raises(ValidationError, match="duplicate"):
        ConceptGraph(course_id="crs_1", concepts=[Concept(id="con_a", name="A"), Concept(id="con_a", name="A2")])


def test_graph_edges():
    g = ConceptGraph(
        course_id="crs_1",
        concepts=[
            Concept(id="con_var", name="Variables"),
            Concept(id="con_type", name="Data types", prerequisites=["con_var"]),
        ],
    )
    assert g.edges() == [("con_var", "con_type")]


# ---- questions -----------------------------------------------------------
def test_question_needs_exactly_one_numbering():
    with pytest.raises(ValidationError):
        Question(type=QuestionType.MULTIPLE_CHOICE, stem="?")
    with pytest.raises(ValidationError):
        Question(number=1, number_range=(1, 2), type=QuestionType.MULTIPLE_CHOICE, stem="?")


def test_compound_question_covers_range():
    q = Question(
        number_range=(7, 8),
        choose=2,
        type=QuestionType.MULTIPLE_CHOICE_MULTI,
        stem="Which TWO of the following are true?",
        options=[Option(label=c, text=c.lower()) for c in "ABCDE"],
        answer=Answer(accepted=["C", "D"], unordered=True),
    )
    assert q.numbers() == [7, 8]


def test_compound_choose_must_match_range():
    with pytest.raises(ValidationError, match="covers 2 boxes"):
        Question(number_range=(7, 8), choose=3, type=QuestionType.MULTIPLE_CHOICE_MULTI, stem="?")


def test_group_rejects_question_outside_range():
    with pytest.raises(ValidationError, match="outside group range"):
        QuestionGroup(
            type=QuestionType.TRUE_FALSE_NOT_GIVEN,
            range=(19, 20),
            questions=[Question(number=21, type=QuestionType.TRUE_FALSE_NOT_GIVEN, stem="s")],
        )


def test_assessment_numbers_flatten_compound():
    g1 = QuestionGroup(
        type=QuestionType.MULTIPLE_CHOICE,
        range=(1, 6),
        questions=[Question(number=n, type=QuestionType.MULTIPLE_CHOICE, stem="?") for n in range(1, 7)],
    )
    g2 = QuestionGroup(
        type=QuestionType.MULTIPLE_CHOICE_MULTI,
        range=(7, 8),
        questions=[Question(number_range=(7, 8), choose=2, type=QuestionType.MULTIPLE_CHOICE_MULTI, stem="?")],
    )
    a = Assessment(project_id="prj_1", kind=AssessmentKind.IELTS_TEST, title="T", groups=[g1, g2])
    assert a.numbers() == list(range(1, 9))


# ---- content -------------------------------------------------------------
def test_blocks_are_discriminated_by_kind():
    adapter = TypeAdapter(Block)
    blk = adapter.validate_python({"kind": "code", "language": "python", "code": "print(1)", "expected_output": "1"})
    assert isinstance(blk, CodeBlock)


def test_chapter_json_round_trip():
    ch = Chapter(
        number=1,
        title="O'zgaruvchilar",
        sections=[
            Section(
                kind=SectionKind.EXPLANATION,
                title="Tushuntirish",
                blocks=[ParagraphBlock(text="O'zgaruvchi — qiymat saqlovchi nom.", lang=Lang.UZ)],
            )
        ],
    )
    book = StudentBook(course_id="crs_1", title="Python", lang=Lang.UZ, chapters=[ch])
    again = StudentBook.model_validate_json(book.model_dump_json())
    assert again == book
    assert again.chapters[0].sections[0].blocks[0].lang is Lang.UZ


# ---- brief / course ------------------------------------------------------
def test_brief_reports_unconfirmed_fields():
    brief = CourseBrief(
        request="Create a beginner Python textbook for Uzbek teenagers.",
        subject=BriefField[str](value="Python", origin=FieldOrigin.CONFIRMED),
        level=BriefField[str](value="beginner", origin=FieldOrigin.CONFIRMED),
        age_range=BriefField[tuple[int, int]](value=(13, 16)),
        schedule=BriefField[Schedule](value=Schedule(duration_weeks=26, lessons_per_week=3)),
        languages=BriefField[LanguageSettings](
            value=LanguageSettings(explanation=Lang.UZ, terminology=Lang.EN, assessment=Lang.UZ)
        ),
        goal=BriefField[str](value="Teach programming from zero", origin=FieldOrigin.CONFIRMED),
    )
    assert set(brief.unconfirmed_fields()) == {"age_range", "schedule", "languages"}
    assert brief.schedule.value.total_lessons == 78


def test_course_languages_independent():
    c = Course(
        project_id="prj_1",
        title="Python",
        subject="Python",
        level="beginner",
        languages=LanguageSettings(explanation=Lang.UZ, terminology=Lang.EN, assessment=Lang.RU),
    )
    assert (c.languages.explanation, c.languages.terminology, c.languages.assessment) == (Lang.UZ, Lang.EN, Lang.RU)


# ---- knowledge / sources / validation -------------------------------------
def test_knowledge_base_term_approval():
    kb = KnowledgeBase(project_id="prj_1")
    kb.approve_term("variable", Lang.UZ, "o'zgaruvchi", forbidden=["variabl"])
    kb.approve_term("variable", Lang.RU, "переменная")
    assert kb.term("variable").preferred(Lang.UZ) == "o'zgaruvchi"
    assert kb.term("variable").preferred(Lang.RU) == "переменная"
    kb.approve_term("variable", Lang.UZ, "o‘zgaruvchi")  # re-approval replaces, not duplicates
    assert len([t for t in kb.term("variable").translations if t.lang is Lang.UZ]) == 1


def test_source_cannot_claim_verification_without_method():
    with pytest.raises(ValidationError):
        Source(project_id="p", kind=SourceKind.DOI, citation="x", verified=True)
    s = Source(project_id="p", kind=SourceKind.DOI, citation="x", verified=True, verified_via=VerificationMethod.CROSSREF)
    assert s.verified


def test_validation_result_gate_ignores_llm_errors():
    issue = ValidationIssue(
        code="ielts.question.glued",
        severity=Severity.ERROR,
        location=Location(passage=1, question=13, line=42, excerpt="energy 13 The author"),
        problem="Question 13 is glued to question 12",
        expected="13. on its own line",
        suggestion="Insert a line break before '13'",
    )
    soft = ValidationIssue(code="content.contradiction", severity=Severity.ERROR, problem="?", method="llm")
    assert not ValidationResult(target_id="d", profile="ielts_reading", issues=[issue]).passed
    assert ValidationResult(target_id="d", profile="x", issues=[soft]).passed
    text = issue.render()
    assert "Location: Passage 1, Question 13, Line 42" in text
    assert "Suggested correction:" in text
