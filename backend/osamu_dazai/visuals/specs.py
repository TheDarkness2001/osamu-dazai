"""Structured visual specifications (spec §11: 'first create a structured visual specification').

One flat model (friendly to structured output); which fields matter depends on
``kind``. Rendering is deterministic (``svg.py`` / ``mermaid.py``) except
illustrations, which go to an image provider.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from osamu_dazai.domain.visuals import VisualKind

Shape = Literal["start", "end", "process", "decision", "io"]


class NodeD(BaseModel):
    id: str
    label: str
    shape: Shape = "process"


class EdgeD(BaseModel):
    source: str
    target: str
    label: str = ""


class EventD(BaseModel):
    date: str
    label: str


class SeriesD(BaseModel):
    name: str
    values: list[float]


class VarD(BaseModel):
    name: str
    value: str
    type: str = ""


class VisualDraft(BaseModel):
    visual_id: str = Field(description="the id of the visual request being specified")
    kind: VisualKind
    title: str
    caption: str = Field(description="one-sentence caption shown under the figure")
    alt_text: str = Field(description="accessible description of what the figure shows")
    # flowchart / process / technical / concept_map / mind_map / programming (control flow)
    nodes: list[NodeD] = Field(default_factory=list)
    edges: list[EdgeD] = Field(default_factory=list)
    root: str = Field(default="", description="mind_map only: id of the central node")
    # timeline
    events: list[EventD] = Field(default_factory=list)
    # chart / graph
    chart_type: Literal["bar", "line", "pie"] | None = None
    categories: list[str] = Field(default_factory=list)
    series: list[SeriesD] = Field(default_factory=list)
    x_label: str = ""
    y_label: str = ""
    data_provenance: Literal["from_text", "illustrative", "source"] | None = Field(
        default=None, description="from_text: numbers stated in the chapter; illustrative: invented example "
                                  "values (will be labelled as such); source: from a cited source")
    data_note: str = Field(default="", description="for 'source': the citation; otherwise optional")
    # comparison
    columns: list[str] = Field(default_factory=list, description="the things being compared")
    criteria: list[str] = Field(default_factory=list)
    cells: list[list[str]] = Field(default_factory=list, description="one row per criterion, one cell per column")
    # programming: memory / variables diagram
    variables: list[VarD] = Field(default_factory=list)
    # illustration
    image_prompt: str = Field(default="", description="illustration only: detailed scene description, no text")


class VisualPlanDraft(BaseModel):
    visuals: list[VisualDraft]


FLOW_KINDS = {VisualKind.FLOWCHART, VisualKind.PROCESS, VisualKind.TECHNICAL, VisualKind.CONCEPT_MAP}


def renderer_for(d: VisualDraft) -> str:
    k = d.kind
    if k is VisualKind.ILLUSTRATION:
        return "image"
    if k is VisualKind.MIND_MAP:
        return "mindmap"
    if k is VisualKind.TIMELINE:
        return "timeline"
    if k in (VisualKind.CHART, VisualKind.GRAPH):
        return "chart"
    if k is VisualKind.COMPARISON:
        return "comparison"
    if k is VisualKind.PROGRAMMING and d.variables:
        return "memory"
    return "flow"
