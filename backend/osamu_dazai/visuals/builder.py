"""Visual Planner + rendering pipeline (spec §11–12).

Per chapter, one checked LLM stage turns the writer's visual requests into
structured specs (``VisualDraft``). Code then renders them deterministically
(SVG + Mermaid) — or, for illustrations only, calls the image provider — and
records every output as an ``Image`` linked to chapter, section and concepts.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from osamu_dazai.domain.common import Lang, Provenance
from osamu_dazai.domain.content import Chapter, StudentBook
from osamu_dazai.domain.curriculum import Course
from osamu_dazai.domain.graph import ConceptGraph
from osamu_dazai.domain.knowledge import KnowledgeBase
from osamu_dazai.domain.visuals import Image, RenderStrategy, Visual, VisualKind, VisualSpec
from osamu_dazai.knowledge import find_forbidden, terminology_prompt
from osamu_dazai.pipeline.book import script_ok
from osamu_dazai.pipeline.curriculum import LANG_NAMES
from osamu_dazai.pipeline.llm_stage import generate_checked
from osamu_dazai.providers import ProviderRegistry
from osamu_dazai.providers.image import ImageRequest
from osamu_dazai.storage.assets import AssetStore
from osamu_dazai.visuals.mermaid import to_mermaid
from osamu_dazai.visuals.specs import FLOW_KINDS, VisualDraft, VisualPlanDraft, renderer_for
from osamu_dazai.visuals.svg import render_svg

STAGE = "visual_planner"
PROMPT_VERSION = "visuals.v1"
MAX_NODES = 20

DATA_NOTES = {
    "illustrative": {Lang.EN: "Illustrative data", Lang.UZ: "Shartli (namunaviy) ma’lumotlar",
                     Lang.UZ_CYRL: "Шартли (намунавий) маълумотлар", Lang.RU: "Условные данные"},
    "source": {Lang.EN: "Source", Lang.UZ: "Manba", Lang.UZ_CYRL: "Манба", Lang.RU: "Источник"},
}


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def _labels(d: VisualDraft) -> list[str]:
    out = [d.title, d.caption, *(n.label for n in d.nodes), *(e.label for e in d.edges),
           *(ev.label for ev in d.events), *d.categories, *d.columns, *d.criteria,
           *(c for row in d.cells for c in row), d.x_label, d.y_label]
    return [s for s in out if s]


def check_draft(d: VisualDraft, lang: Lang, kb: KnowledgeBase) -> list[str]:
    p: list[str] = []
    w = f"visual {d.visual_id}"
    kind = renderer_for(d)
    if not d.caption.strip() or not d.alt_text.strip():
        p.append(f"{w}: needs a caption and alt_text")
    if kind in ("flow", "mindmap"):
        ids = [n.id for n in d.nodes]
        if len(ids) < 2:
            p.append(f"{w}: needs at least 2 nodes")
        if len(ids) > MAX_NODES:
            p.append(f"{w}: too many nodes ({len(ids)}); keep at most {MAX_NODES} so it stays legible")
        if len(set(ids)) != len(ids):
            p.append(f"{w}: node ids must be unique")
        known = set(ids)
        if bad := [f"{e.source}->{e.target}" for e in d.edges if e.source not in known or e.target not in known]:
            p.append(f"{w}: edges reference unknown nodes {bad}")
            return p
        if any(len(n.label) > 80 for n in d.nodes):
            p.append(f"{w}: node labels must be short (≤ 80 characters)")
        connected = {e.source for e in d.edges} | {e.target for e in d.edges}
        if len(ids) > 1 and (lonely := [i for i in ids if i not in connected]):
            p.append(f"{w}: nodes {lonely} are not connected")
        if kind == "flow":
            out_deg = defaultdict(int)
            for e in d.edges:
                out_deg[e.source] += 1
            for n in d.nodes:
                if n.shape == "decision" and out_deg[n.id] < 2:
                    p.append(f"{w}: decision '{n.label}' needs at least two outgoing edges (e.g. yes/no)")
            if d.kind is VisualKind.FLOWCHART:
                if sum(n.shape == "start" for n in d.nodes) != 1:
                    p.append(f"{w}: a flowchart needs exactly one start node")
                if not any(n.shape == "end" for n in d.nodes):
                    p.append(f"{w}: a flowchart needs an end node")
            if d.kind is VisualKind.CONCEPT_MAP and any(not e.label.strip() for e in d.edges):
                p.append(f"{w}: concept-map links need relationship labels (e.g. 'is a', 'uses')")
        else:  # mind map: a tree rooted at root
            if d.root not in known:
                p.append(f"{w}: root must be one of the node ids")
            parents = defaultdict(int)
            for e in d.edges:
                parents[e.target] += 1
            if parents.get(d.root) or any(parents[i] != 1 for i in ids if i != d.root):
                p.append(f"{w}: a mind map must be a tree (every node except the root has exactly one parent)")
    elif kind == "timeline":
        if not 2 <= len(d.events) <= 15:
            p.append(f"{w}: a timeline needs 2-15 events")
    elif kind == "chart":
        if d.chart_type is None:
            p.append(f"{w}: set chart_type (bar, line or pie)")
        if len(d.categories) < 2 or not d.series:
            p.append(f"{w}: needs at least 2 categories and one series")
        if any(len(s.values) != len(d.categories) for s in d.series):
            p.append(f"{w}: every series needs one value per category")
        if d.chart_type == "pie" and (len(d.series) != 1 or any(v <= 0 for v in d.series[0].values)):
            p.append(f"{w}: a pie chart needs exactly one series of positive values")
        if d.data_provenance is None:
            p.append(f"{w}: say where the numbers come from (data_provenance)")
        elif d.data_provenance == "source" and not d.data_note.strip():
            p.append(f"{w}: sourced data needs the citation in data_note")
    elif kind == "comparison":
        if len(d.columns) < 2 or len(d.criteria) < 2:
            p.append(f"{w}: compare at least 2 items on at least 2 criteria")
        if len(d.cells) != len(d.criteria) or any(len(r) != len(d.columns) for r in d.cells):
            p.append(f"{w}: cells must have one row per criterion and one cell per compared item")
    elif kind == "memory":
        if not d.variables:
            p.append(f"{w}: list the variables to show")
    elif kind == "image":
        if len(d.image_prompt.split()) < 12:
            p.append(f"{w}: describe the illustration in at least 12 words")
    text = " ".join(_labels(d))
    for hit in find_forbidden(text, kb, lang):
        p.append(f"{w}: use the approved term '{hit.preferred}' instead of '{hit.found}'")
    if not script_ok(text * 3, lang):  # labels are short; repeat to reach the script check's minimum
        p.append(f"{w}: write labels in {LANG_NAMES[lang]}")
    return p


def check_plan(plan: VisualPlanDraft, requests: dict[str, VisualSpec], lang: Lang, kb: KnowledgeBase) -> list[str]:
    got = [v.visual_id for v in plan.visuals]
    if sorted(got) != sorted(requests):
        return [f"give exactly one spec per visual request {sorted(requests)} (got {got})"]
    p: list[str] = []
    for v in plan.visuals:
        req = requests[v.visual_id]
        if (req.kind is VisualKind.ILLUSTRATION) != (v.kind is VisualKind.ILLUSTRATION):
            p.append(f"visual {v.visual_id}: keep it {'an illustration' if req.kind is VisualKind.ILLUSTRATION else 'a diagram'}")
        p += check_draft(v, lang, kb)
    return p


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------
SYSTEM = """You design educational figures. For each visual request, produce a precise structured
specification that a renderer will draw exactly as given. Keep figures simple and legible (few nodes,
short labels), consistent with the chapter's terminology and written in the chapter's language.
Never invent statistics: chart numbers must come from the chapter text, from a cited source, or be
explicitly marked as illustrative. Illustrations must contain no text, letters, logos or real people."""


def _context_text(ch: Chapter, vid: str) -> str:
    """The text around a visual reference, so the planner knows what it illustrates."""
    for s in ch.sections:
        for i, b in enumerate(s.blocks):
            if b.kind == "visual_ref" and b.visual_id == vid:
                near = [getattr(x, "text", "") or getattr(x, "code", "") for x in s.blocks[max(0, i - 2):i + 2]]
                return f"Section '{s.title}': " + " ".join(t for t in near if t)[:1200]
    return ""


def visuals_prompt(ch: Chapter, graph: ConceptGraph, kb: KnowledgeBase, lang: Lang) -> str:
    by = graph.by_id()
    reqs = []
    for vid, spec in ch.visual_specs.items():
        reqs.append(f"- {vid}: kind={spec.kind.value}; purpose: {spec.purpose}; requested content: "
                    f"{spec.data.get('description', '')}\n  Context: {_context_text(ch, vid)}")
    concepts = ", ".join(by[c].name for c in ch.introduces_concepts if c in by)
    return "\n\n".join(x for x in [
        f"Chapter {ch.number}: {ch.title}. New concepts: {concepts or '—'}.",
        f"Write all labels in {LANG_NAMES[lang]}.",
        "Visual requests (one spec each; keep the visual_id; you may switch between diagram kinds if another "
        "diagram type communicates better, but keep illustrations as illustrations):\n" + "\n".join(reqs),
        terminology_prompt(kb, lang),
    ] if x)


def illustration_prompt(d: VisualDraft, age: tuple[int, int] | None) -> ImageRequest:
    audience = f"learners aged {age[0]}-{age[1]}" if age else "school learners"
    return ImageRequest(
        prompt=f"{d.image_prompt.strip()}. Educational illustration for {audience}.",
        style="clean flat illustration, soft colours, white background, inclusive and culturally neutral",
        negative_prompt="text, letters, numbers, captions, watermark, logo, real people, brand names",
        width=1024, height=768)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
@dataclass
class VisualBuildResult:
    book: StudentBook
    visuals: list[Visual] = field(default_factory=list)
    images: list[Image] = field(default_factory=list)
    figures: dict[str, str] = field(default_factory=dict)  # visual_id -> asset path (relative)
    attempts: dict[int, int] = field(default_factory=dict)


def _section_of(ch: Chapter, vid: str) -> str | None:
    return next((s.id for s in ch.sections for b in s.blocks if b.kind == "visual_ref" and b.visual_id == vid), None)


class VisualBuilder:
    def __init__(self, registry: ProviderRegistry, assets: AssetStore, *, max_attempts: int = 3,
                 generate_images: bool = True) -> None:
        self.registry = registry
        self.assets = assets
        self.max_attempts = max_attempts
        self.generate_images = generate_images

    async def build(self, book: StudentBook, course: Course, graph: ConceptGraph, kb: KnowledgeBase) -> VisualBuildResult:
        lang = course.languages.explanation
        result = VisualBuildResult(book=book)
        chapters = []
        for ch in book.chapters:
            if not ch.visual_specs:
                chapters.append(ch)
                continue
            out = await generate_checked(
                self.registry, STAGE, system=SYSTEM, prompt=visuals_prompt(ch, graph, kb, lang),
                schema=VisualPlanDraft, check=lambda d, ch=ch: check_plan(d, ch.visual_specs, lang, kb),
                prompt_version=PROMPT_VERSION, max_attempts=self.max_attempts)
            result.attempts[ch.number] = out.attempts
            specs = dict(ch.visual_specs)
            for d in out.value.visuals:
                specs[d.visual_id] = await self._render(d, ch, course, lang, result)
            chapters.append(ch.model_copy(update={"visual_specs": specs}))
        result.book = book.model_copy(update={"chapters": chapters})
        return result

    async def _render(self, d: VisualDraft, ch: Chapter, course: Course, lang: Lang,
                      result: VisualBuildResult) -> VisualSpec:
        kind = renderer_for(d)
        pid = course.project_id
        section_id = _section_of(ch, d.visual_id)
        common = {"project_id": pid, "chapter_id": ch.id, "section_id": section_id,
                  "concept_ids": list(ch.introduces_concepts), "purpose": d.caption, "alt_text": d.alt_text}
        source, image = None, None
        strategy = RenderStrategy.IMAGE_GEN if kind == "image" else (
            RenderStrategy.CHART if kind == "chart" else
            RenderStrategy.MERMAID if kind in ("flow", "mindmap", "timeline") else RenderStrategy.SVG_TEMPLATE)
        if kind == "image":
            if self.generate_images:
                req = illustration_prompt(d, course.age_range)
                img = await self.registry.image().generate(req)
                ext = "png" if img.mime_type == "image/png" else "jpg"
                path = self.assets.save(pid, f"{d.visual_id}.{ext}", img.data)
                image = Image(**common, prompt=req.prompt, provider=img.provider, model=img.model, filename=path,
                              width=img.width, height=img.height, provenance=Provenance.AI_GENERATED)
        else:
            note = ""
            if kind == "chart" and d.data_provenance == "illustrative":
                note = DATA_NOTES["illustrative"][lang]
            elif kind == "chart" and d.data_provenance == "source":
                note = f"{DATA_NOTES['source'][lang]}: {d.data_note}"
            rendered = render_svg(d, kind, note)
            source = to_mermaid(d, kind)
            path = self.assets.save(pid, f"{d.visual_id}.svg", rendered.svg)
            image = Image(**common, prompt=None, provider="dazai-svg", model=f"svg:{kind}", filename=path,
                          width=rendered.width, height=rendered.height,
                          provenance=Provenance.SOURCE_BACKED if d.data_provenance == "source"
                          else Provenance.AI_GENERATED)
        if image is not None:
            result.images.append(image)
            result.figures[d.visual_id] = image.filename
        spec = VisualSpec(kind=d.kind, purpose=d.caption, render_strategy=strategy, concept_ids=list(ch.introduces_concepts),
                          title=d.title, alt_text=d.alt_text,
                          data=d.model_dump(exclude={"visual_id", "kind", "title", "caption", "alt_text"},
                                            exclude_defaults=True),
                          image_prompt=d.image_prompt or None)
        result.visuals.append(Visual(project_id=pid, chapter_id=ch.id, section_id=section_id, spec=spec,
                                     source=source, image_id=image.id if image else None))
        return spec


__all__ = ["FLOW_KINDS", "VisualBuildResult", "VisualBuilder", "check_draft", "check_plan"]
