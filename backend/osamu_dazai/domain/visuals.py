"""Visual specifications, rendered visuals and generated images (spec §11–12)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from osamu_dazai.domain.common import Entity, Model, Provenance, id_field, utcnow


class VisualKind(StrEnum):
    FLOWCHART = "flowchart"
    CONCEPT_MAP = "concept_map"
    MIND_MAP = "mind_map"
    TIMELINE = "timeline"
    PROCESS = "process"
    COMPARISON = "comparison"
    CHART = "chart"
    GRAPH = "graph"
    TECHNICAL = "technical"
    PROGRAMMING = "programming"  # e.g. memory/variable diagrams, call stacks
    ILLUSTRATION = "illustration"


class RenderStrategy(StrEnum):
    MERMAID = "mermaid"  # deterministic, preferred for diagrams
    SVG_TEMPLATE = "svg_template"
    CHART = "chart"
    IMAGE_GEN = "image_gen"  # only when a real illustration is better


class VisualSpec(Model):
    """What the Visual Planner decides *before* anything is rendered."""

    kind: VisualKind
    purpose: str = Field(min_length=1)  # why this visual helps learning
    render_strategy: RenderStrategy
    concept_ids: list[str] = Field(default_factory=list)
    title: str = ""
    alt_text: str = ""
    data: dict[str, Any] = Field(default_factory=dict)  # nodes/edges, series, events...
    image_prompt: str | None = None  # only for IMAGE_GEN


class Visual(Entity):
    ID_PREFIX = "vis"
    id: str = id_field(ID_PREFIX)
    project_id: str
    chapter_id: str | None = None
    section_id: str | None = None
    spec: VisualSpec
    source: str | None = None  # Mermaid/SVG source when deterministic
    image_id: str | None = None  # set when rendered to / generated as an image
    provenance: Provenance = Provenance.AI_GENERATED


class Image(Entity):
    """Stored image record (spec §12 fields)."""

    ID_PREFIX = "img"
    id: str = id_field(ID_PREFIX)
    project_id: str
    chapter_id: str | None = None
    section_id: str | None = None
    concept_ids: list[str] = Field(default_factory=list)
    purpose: str
    prompt: str | None = None
    provider: str  # "mock", "mermaid", "openai", "local-sd", ...
    model: str | None = None
    filename: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    alt_text: str = ""
    provenance: Provenance = Provenance.AI_GENERATED
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def image_id(self) -> str:
        return self.id

    @property
    def dimensions(self) -> tuple[int, int]:
        return (self.width, self.height)
