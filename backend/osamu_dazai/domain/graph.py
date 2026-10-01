"""Learning graph: concepts and prerequisite relations (spec §8).

Only the data model lives here; graph algorithms (cycle detection, ordering
checks) belong to ``osamu_dazai.graph`` (Phase 5).
"""

from __future__ import annotations

from pydantic import Field, model_validator

from osamu_dazai.domain.common import BloomLevel, Entity, Model, id_field


class Concept(Entity):
    ID_PREFIX = "con"
    id: str = id_field(ID_PREFIX)
    name: str = Field(min_length=1)
    description: str = ""
    difficulty: int = Field(default=1, ge=1, le=5)
    prerequisites: list[str] = Field(default_factory=list)  # Concept ids
    learning_objectives: list[str] = Field(default_factory=list)  # LearningObjective ids
    related_concepts: list[str] = Field(default_factory=list)  # non-prerequisite links
    chapters: list[str] = Field(default_factory=list)  # Chapter ids that teach it
    assessment_items: list[str] = Field(default_factory=list)  # Question ids assessing it
    taxonomy_group: str | None = None  # e.g. "foundation", "control-flow"
    bloom_levels: list[BloomLevel] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_self_reference(self) -> Concept:
        if self.id in self.prerequisites:
            raise ValueError(f"concept {self.id} lists itself as a prerequisite")
        return self


class ConceptGraph(Entity):
    ID_PREFIX = "cgr"
    id: str = id_field(ID_PREFIX)
    course_id: str
    concepts: list[Concept] = Field(default_factory=list)

    @model_validator(mode="after")
    def _references_resolve(self) -> ConceptGraph:
        ids = [c.id for c in self.concepts]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate concept ids in graph")
        known = set(ids)
        for c in self.concepts:
            missing = [p for p in (*c.prerequisites, *c.related_concepts) if p not in known]
            if missing:
                raise ValueError(f"concept {c.id} references unknown concepts: {missing}")
        return self

    def by_id(self) -> dict[str, Concept]:
        return {c.id: c for c in self.concepts}

    def edges(self) -> list[tuple[str, str]]:
        """(prerequisite, dependent) pairs."""
        return [(p, c.id) for c in self.concepts for p in c.prerequisites]


class ConceptRef(Model):
    """Lightweight reference used inside content blocks."""

    concept_id: str
    role: str = "uses"  # "introduces" | "uses" | "reviews"
