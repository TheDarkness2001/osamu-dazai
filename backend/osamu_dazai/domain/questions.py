"""General question / assessment model (spec §9 of the plan, §14 question checks).

Shared by quizzes, exams, worksheets, homework and — via ``osamu_dazai.ielts`` —
IELTS tests. A question either has one number (``number``) or covers a range of
answer boxes (``number_range``, e.g. IELTS "Choose TWO letters" → 7-8).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from osamu_dazai.domain.common import BloomLevel, Entity, Model, Provenance, ReviewStatus, id_field


class QuestionType(StrEnum):
    # general
    MULTIPLE_CHOICE = "multiple_choice"
    MULTIPLE_CHOICE_MULTI = "multiple_choice_multi"  # choose TWO/THREE letters (compound)
    TRUE_FALSE = "true_false"
    SHORT_ANSWER = "short_answer"
    COMPLETION = "completion"  # sentence / note / table / flow-chart / summary / form
    MATCHING = "matching"
    ESSAY = "essay"
    CODE = "code"
    # IELTS-specific judgements
    TRUE_FALSE_NOT_GIVEN = "true_false_not_given"
    YES_NO_NOT_GIVEN = "yes_no_not_given"
    MATCHING_HEADINGS = "matching_headings"
    MATCHING_INFORMATION = "matching_information"
    MATCHING_FEATURES = "matching_features"
    MATCHING_SENTENCE_ENDINGS = "matching_sentence_endings"
    LABELLING = "labelling"  # map / plan / diagram


class CompletionForm(StrEnum):
    SENTENCE = "sentence"
    SUMMARY = "summary"
    NOTE = "note"
    TABLE = "table"
    FLOW_CHART = "flow_chart"
    FORM = "form"
    DIAGRAM = "diagram"


class Option(Model):
    label: str  # "A", "B", "i", "ii" — literal text, never auto-numbered
    text: str


class Answer(Model):
    """Accepted answer(s). ``accepted`` holds alternatives (rendered ``river | stream``).

    For compound questions (7-8 → "C, D"), ``accepted`` holds the required set and
    ``unordered`` is True.
    """

    accepted: list[str] = Field(min_length=1)
    unordered: bool = False
    explanation: str = ""
    evidence: str = ""  # passage quote / line reference supporting the answer


class WordLimit(Model):
    max_words: int | None = Field(default=None, gt=0)
    allow_number: bool = False
    raw: str = ""  # original phrasing, e.g. "NO MORE THAN TWO WORDS AND/OR A NUMBER"


class Question(Model):
    id: str = id_field("q")
    number: int | None = Field(default=None, gt=0)
    number_range: tuple[int, int] | None = None  # inclusive, compound questions only
    type: QuestionType
    stem: str  # question text / statement / sentence with blank
    options: list[Option] = Field(default_factory=list)
    choose: int | None = Field(default=None, gt=1)  # letters to choose (compound MC)
    answer: Answer | None = None
    word_limit: WordLimit | None = None
    concept_ids: list[str] = Field(default_factory=list)
    objective_ids: list[str] = Field(default_factory=list)  # learning objectives this item assesses
    bloom_level: BloomLevel | None = None
    difficulty: int = Field(default=2, ge=1, le=5)
    points: float = 1.0
    provenance: Provenance = Provenance.AI_GENERATED

    @model_validator(mode="after")
    def _numbering(self) -> Question:
        if (self.number is None) == (self.number_range is None):
            raise ValueError("a question needs exactly one of number / number_range")
        if self.number_range is not None:
            a, b = self.number_range
            if not 0 < a < b:
                raise ValueError(f"invalid number_range {self.number_range}")
            if self.choose is not None and self.choose != b - a + 1:
                raise ValueError(f"choose={self.choose} but range {a}-{b} covers {b - a + 1} boxes")
        return self

    def numbers(self) -> list[int]:
        """All answer-box numbers this question occupies."""
        if self.number is not None:
            return [self.number]
        a, b = self.number_range  # type: ignore[misc]
        return list(range(a, b + 1))


class QuestionGroup(Entity):
    """A block of questions sharing one instruction (e.g. IELTS "Questions 1-6")."""

    ID_PREFIX = "qg"
    id: str = id_field(ID_PREFIX)
    type: QuestionType
    completion_form: CompletionForm | None = None
    range: tuple[int, int] | None = None  # declared range; None for unnumbered exercises
    title: str = ""
    instructions: list[str] = Field(default_factory=list)
    list_title: str = ""  # e.g. "List of Headings", "List of Researchers"
    shared_options: list[Option] = Field(default_factory=list)  # heading list, feature list...
    # Free text for inline-blank forms (summary / notes / table / flow-chart):
    # "{37}" marks where question 37's numbered blank goes.
    body: list[str] = Field(default_factory=list)
    word_limit: WordLimit | None = None
    questions: list[Question] = Field(default_factory=list)

    @model_validator(mode="after")
    def _within_range(self) -> QuestionGroup:
        if self.range is None:
            return self
        a, b = self.range
        if a > b:
            raise ValueError(f"group range {a}-{b} is reversed")
        for q in self.questions:
            outside = [n for n in q.numbers() if not a <= n <= b]
            if outside:
                raise ValueError(f"question numbers {outside} fall outside group range {a}-{b}")
        return self

    def numbers(self) -> list[int]:
        return [n for q in self.questions for n in q.numbers()]


class RubricLevel(Model):
    score: float
    descriptor: str


class RubricCriterion(Model):
    name: str
    weight: float = 1.0
    levels: list[RubricLevel] = Field(min_length=1)


class Rubric(Model):
    title: str
    criteria: list[RubricCriterion] = Field(min_length=1)


class AssessmentKind(StrEnum):
    QUIZ = "quiz"
    EXAM = "exam"
    WORKSHEET = "worksheet"
    HOMEWORK = "homework"
    PROJECT = "project"
    IELTS_TEST = "ielts_test"


class Assessment(Entity):
    ID_PREFIX = "asm"
    id: str = id_field(ID_PREFIX)
    project_id: str
    course_id: str | None = None
    chapter_id: str | None = None
    kind: AssessmentKind
    title: str
    instructions: str = ""
    version_label: str | None = None  # "A", "B", … for shuffled versions
    source_assessment_id: str | None = None  # the master a version was derived from
    duration_minutes: int | None = Field(default=None, gt=0)
    groups: list[QuestionGroup] = Field(default_factory=list)
    rubrics: list[Rubric] = Field(default_factory=list)
    status: ReviewStatus = ReviewStatus.DRAFT

    def numbers(self) -> list[int]:
        return [n for g in self.groups for n in g.numbers()]
