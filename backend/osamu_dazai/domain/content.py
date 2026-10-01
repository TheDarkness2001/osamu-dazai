"""Student-book content: book → chapter → section → blocks (spec §9).

Chapters are *not* forced into one template: each chapter picks and orders
sections from the ``SectionKind`` palette to suit its subject.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from osamu_dazai.domain.common import Entity, Lang, Model, Provenance, ReviewStatus, id_field
from osamu_dazai.domain.graph import ConceptRef
from osamu_dazai.domain.questions import QuestionGroup
from osamu_dazai.domain.visuals import VisualSpec


class _BlockBase(Model):
    id: str = id_field("blk")
    lang: Lang = Lang.EN
    provenance: Provenance = Provenance.AI_GENERATED
    source_ids: list[str] = Field(default_factory=list)
    concepts: list[ConceptRef] = Field(default_factory=list)


class HeadingBlock(_BlockBase):
    kind: Literal["heading"] = "heading"
    level: int = Field(ge=1, le=6)
    text: str


class ParagraphBlock(_BlockBase):
    kind: Literal["paragraph"] = "paragraph"
    text: str  # inline markdown subset: **bold**, *italic*, `code`


class ListBlock(_BlockBase):
    kind: Literal["list"] = "list"
    ordered: bool = False
    items: list[str]


class CodeBlock(_BlockBase):
    kind: Literal["code"] = "code"
    language: str  # programming language, e.g. "python"
    code: str
    expected_output: str | None = None  # checked by the programming validator
    runnable: bool = False


class CalloutBlock(_BlockBase):
    kind: Literal["callout"] = "callout"
    style: Literal["note", "tip", "warning", "common_mistake", "definition", "example"] = "note"
    title: str = ""
    text: str


class TableBlock(_BlockBase):
    kind: Literal["table"] = "table"
    caption: str = ""
    header: list[str]
    rows: list[list[str]]


class EquationBlock(_BlockBase):
    kind: Literal["equation"] = "equation"
    latex: str


class VisualRefBlock(_BlockBase):
    kind: Literal["visual_ref"] = "visual_ref"
    visual_id: str
    caption: str = ""


class QuestionRefBlock(_BlockBase):
    """Embeds exercises/quiz items owned by the question engine."""

    kind: Literal["question_ref"] = "question_ref"
    question_group_id: str


Block = Annotated[
    HeadingBlock
    | ParagraphBlock
    | ListBlock
    | CodeBlock
    | CalloutBlock
    | TableBlock
    | EquationBlock
    | VisualRefBlock
    | QuestionRefBlock,
    Field(discriminator="kind"),
]


class SectionKind(StrEnum):
    """Palette of section types a chapter may draw from."""

    OBJECTIVES = "objectives"
    PREREQUISITES = "prerequisites"
    INTRODUCTION = "introduction"
    EXPLANATION = "explanation"
    WORKED_EXAMPLE = "worked_example"
    VISUAL_EXPLANATION = "visual_explanation"
    GUIDED_PRACTICE = "guided_practice"
    INDEPENDENT_PRACTICE = "independent_practice"
    COMMON_MISTAKES = "common_mistakes"
    CHALLENGE = "challenge"
    MINI_PROJECT = "mini_project"
    REVIEW = "review"
    QUIZ = "quiz"
    HOMEWORK = "homework"
    CUSTOM = "custom"


class Section(Model):
    id: str = id_field("sec")
    kind: SectionKind
    title: str
    blocks: list[Block] = Field(default_factory=list)


class Chapter(Entity):
    ID_PREFIX = "chp"
    id: str = id_field(ID_PREFIX)
    number: int = Field(gt=0)
    title: str
    objective_ids: list[str] = Field(default_factory=list)
    introduces_concepts: list[str] = Field(default_factory=list)
    uses_concepts: list[str] = Field(default_factory=list)
    lesson_ids: list[str] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    # Practice/quiz/homework items, referenced from sections by QuestionRefBlock.
    # Answers live here and are rendered only in teacher material / answer keys.
    exercises: list[QuestionGroup] = Field(default_factory=list)
    # Visuals requested by the writer, keyed by the VisualRefBlock.visual_id that
    # marks their position; rendered by the visual system.
    visual_specs: dict[str, VisualSpec] = Field(default_factory=dict)
    summary: str = ""  # fed into the knowledge base for later chapters
    status: ReviewStatus = ReviewStatus.DRAFT


class GlossaryEntry(Model):
    term_key: str  # KnowledgeBase Term.key
    term: str
    definition: str
    lang: Lang = Lang.EN
    first_chapter: int | None = None


class StudentBook(Entity):
    ID_PREFIX = "sbk"
    id: str = id_field(ID_PREFIX)
    course_id: str
    title: str
    lang: Lang = Lang.EN
    chapters: list[Chapter] = Field(default_factory=list)
    glossary: list[GlossaryEntry] = Field(default_factory=list)
    status: ReviewStatus = ReviewStatus.DRAFT
