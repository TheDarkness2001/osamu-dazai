"""IELTS Reading test model. Question groups reuse the general question model."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from osamu_dazai.domain.common import Model, Provenance, id_field
from osamu_dazai.domain.questions import QuestionGroup


class IELTSModule(StrEnum):
    ACADEMIC = "academic"
    GENERAL = "general_training"


class PassageParagraph(Model):
    label: str | None = None  # "A", "B" … when questions refer to paragraphs
    text: str = Field(min_length=1)


class Passage(Model):
    number: int = Field(ge=1)
    title: str = Field(min_length=1)
    paragraphs: list[PassageParagraph] = Field(min_length=1)
    provenance: Provenance = Provenance.AI_GENERATED
    source_note: str = ""  # e.g. "original text written for this test"


class ReadingSection(Model):
    passage: Passage
    groups: list[QuestionGroup] = Field(min_length=1)


class IELTSReadingTest(Model):
    id: str = id_field("iel")
    title: str
    module: IELTSModule = IELTSModule.ACADEMIC
    sections: list[ReadingSection] = Field(min_length=1)

    @model_validator(mode="after")
    def _sequential(self) -> IELTSReadingTest:
        for k, s in enumerate(self.sections, start=1):
            if s.passage.number != k:
                raise ValueError(f"passage {s.passage.number} is in position {k}")
        return self

    def groups(self) -> list[QuestionGroup]:
        return [g for s in self.sections for g in s.groups]

    def question_count(self) -> int:
        return sum(len(g.numbers()) for g in self.groups())
