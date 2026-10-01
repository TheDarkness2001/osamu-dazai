"""Visual system: structured specs → checks → deterministic SVG/Mermaid or image provider."""

import asyncio
import xml.etree.ElementTree as ET

import pytest

from osamu_dazai.documents.markdown import render_student_book
from osamu_dazai.domain.common import Lang
from osamu_dazai.domain.knowledge import KnowledgeBase
from osamu_dazai.domain.visuals import RenderStrategy, VisualKind
from osamu_dazai.pipeline.book import STAGE as BOOK_STAGE
from osamu_dazai.pipeline.book import BlockDraft, BookWriter, plan_chapters
from osamu_dazai.pipeline.curriculum import assemble_course, build_graph
from osamu_dazai.providers import ProviderRegistry
from osamu_dazai.providers.image import MockImageProvider
from osamu_dazai.providers.llm import MockProvider
from osamu_dazai.storage.assets import AssetStore
from osamu_dazai.visuals.builder import STAGE, VisualBuilder, check_draft, check_plan
from osamu_dazai.visuals.mermaid import to_mermaid
from osamu_dazai.visuals.specs import EdgeD, EventD, NodeD, SeriesD, VarD, VisualDraft, VisualPlanDraft, renderer_for
from osamu_dazai.visuals.svg import back_edges, layers, nice_step, render_svg, wrap
from tests.fixtures.book_sample import chapter_draft
from tests.fixtures.course_sample import curriculum_draft, graph_draft
from tests.test_course_design import brief

run = asyncio.run
KB = KnowledgeBase(project_id="p")


def V(**k) -> VisualDraft:
    k.setdefault("visual_id", "vis_ch1_1")
    k.setdefault("caption", "Dastur qanday ishlaydi")
    k.setdefault("alt_text", "Boshlashdan tugashgacha bo‘lgan qadamlar")
    return VisualDraft(**k)


def while_loop(**over) -> VisualDraft:
    data = dict(kind=VisualKind.FLOWCHART, title="While sikli", nodes=[
        NodeD(id="s", label="Boshlash", shape="start"), NodeD(id="i", label="i = 0"),
        NodeD(id="c", label="i < 3 ?", shape="decision"), NodeD(id="p", label="print(i)", shape="io"),
        NodeD(id="inc", label="i = i + 1"), NodeD(id="e", label="Tugash", shape="end")],
        edges=[EdgeD(source="s", target="i"), EdgeD(source="i", target="c"),
               EdgeD(source="c", target="p", label="ha"), EdgeD(source="p", target="inc"),
               EdgeD(source="inc", target="c"), EdgeD(source="c", target="e", label="yo‘q")])
    data.update(over)
    return V(**data)


ALL_KINDS = [
    while_loop(),
    V(kind=VisualKind.CONCEPT_MAP, title="Ma’lumot turlari",
      nodes=[NodeD(id="t", label="Ma’lumot turi"), NodeD(id="i", label="int — butun son"),
             NodeD(id="s", label="str — satr")],
      edges=[EdgeD(source="t", target="i", label="turi"), EdgeD(source="t", target="s", label="turi")]),
    V(kind=VisualKind.MIND_MAP, title="Python", root="r",
      nodes=[NodeD(id="r", label="Python asoslari"), NodeD(id="a", label="O‘zgaruvchilar"),
             NodeD(id="c", label="Sikllar"), NodeD(id="c1", label="for"), NodeD(id="c2", label="while")],
      edges=[EdgeD(source="r", target="a"), EdgeD(source="r", target="c"), EdgeD(source="c", target="c1"),
             EdgeD(source="c", target="c2")]),
    V(kind=VisualKind.TIMELINE, title="Python tarixi",
      events=[EventD(date="1991", label="Python 0.9 chiqdi"), EventD(date="2008", label="Python 3.0 chiqdi")]),
    V(kind=VisualKind.CHART, title="Natijalar", chart_type="bar", categories=["1-hafta", "2-hafta", "3-hafta"],
      series=[SeriesD(name="A sinf", values=[12, 18, 22]), SeriesD(name="B sinf", values=[10, -3, 25])],
      data_provenance="illustrative"),
    V(kind=VisualKind.GRAPH, title="O‘sish", chart_type="line", categories=["dushanba", "seshanba", "chorshanba"],
      series=[SeriesD(name="Ball", values=[1, 2.5, 4])], data_provenance="from_text"),
    V(kind=VisualKind.CHART, title="Ulush", chart_type="pie", categories=["Python", "Boshqa tillar"],
      series=[SeriesD(name="x", values=[60, 40])], data_provenance="illustrative"),
    V(kind=VisualKind.COMPARISON, title="for va while", columns=["for", "while"], criteria=["Qachon", "Takror soni"],
      cells=[["Ketma-ketlik bo‘ylab", "Shart rost ekan"], ["Ma’lum", "Noma’lum bo‘lishi mumkin"]]),
    V(kind=VisualKind.PROGRAMMING, title="Xotira", variables=[VarD(name="ism", value='"Ali"', type="str"),
                                                              VarD(name="yosh", value="14", type="int")]),
]


# ---- rendering ---------------------------------------------------------------
@pytest.mark.parametrize("d", ALL_KINDS, ids=lambda d: d.kind.value + ("-" + d.chart_type if d.chart_type else ""))
def test_every_kind_renders_valid_svg(d):
    assert check_draft(d, Lang.UZ, KB) == []
    out = render_svg(d, renderer_for(d), note="Shartli ma’lumotlar")
    root = ET.fromstring(out.svg)  # well-formed XML
    assert root.tag.endswith("svg") and out.width > 50 and out.height > 50
    assert root.find("{http://www.w3.org/2000/svg}title").text == d.title
    texts = "".join(root.itertext())
    for label in [n.label for n in d.nodes] + d.categories + d.columns + [v.name for v in d.variables]:
        assert label in texts


def test_flow_layout_handles_loops():
    d = while_loop()
    ids = [n.id for n in d.nodes]
    assert back_edges(ids, d.edges) == {("inc", "c")}
    forward = [(e.source, e.target) for e in d.edges if (e.source, e.target) != ("inc", "c")]
    rows = layers(ids, forward)
    assert rows[0] == ["s"] and rows[1] == ["i"] and rows[2] == ["c"] and "p" in rows[3]


def test_helpers():
    assert wrap("bir ikki uch to‘rt besh olti yetti sakkiz", 12) == ["bir ikki uch", "to‘rt besh", "olti yetti", "sakkiz"]
    assert wrap("x" * 30, 10) == ["x" * 10] * 3
    assert nice_step(27) == 10 and nice_step(4.2) == 1
    assert "&lt;" in render_svg(while_loop(nodes=[NodeD(id="s", label="a < b", shape="start"),
                                                  NodeD(id="e", label="end", shape="end")],
                                           edges=[EdgeD(source="s", target="e")]), "flow").svg


def test_mermaid_sources():
    m = to_mermaid(while_loop(), "flow")
    assert m.startswith("flowchart TD") and 'n_c{"i < 3 ?"}' in m and 'n_c -- "ha" --> n_p' in m
    assert to_mermaid(ALL_KINDS[2], "mindmap").splitlines()[1] == "  root((Python asoslari))"
    assert to_mermaid(ALL_KINDS[3], "timeline").endswith("2008 : Python 3.0 chiqdi")
    assert to_mermaid(ALL_KINDS[7], "comparison") is None


# ---- checks ------------------------------------------------------------------------
@pytest.mark.parametrize(("mutate", "expected"), [
    (lambda d: d.edges.append(EdgeD(source="c", target="ghost")), "unknown nodes"),
    (lambda d: setattr(d, "edges", [e for e in d.edges if e.target != "e"]), "two outgoing edges"),
    (lambda d: setattr(d.nodes[0], "shape", "process"), "exactly one start"),
    (lambda d: d.nodes.append(NodeD(id="x", label="yolg‘iz")), "not connected"),
    (lambda d: setattr(d, "caption", ""), "caption and alt_text"),
])
def test_flow_checks(mutate, expected):
    d = while_loop()
    mutate(d)
    assert any(expected in p for p in check_draft(d, Lang.UZ, KB))


def test_other_checks():
    mind = ALL_KINDS[2].model_copy(deep=True)
    mind.edges.append(EdgeD(source="a", target="c1"))
    assert any("must be a tree" in p for p in check_draft(mind, Lang.UZ, KB))
    pie = ALL_KINDS[6].model_copy(update={"series": [SeriesD(name="x", values=[60, -5])]})
    assert any("positive values" in p for p in check_draft(pie, Lang.UZ, KB))
    bar = ALL_KINDS[4].model_copy(update={"data_provenance": None})
    assert any("where the numbers come from" in p for p in check_draft(bar, Lang.UZ, KB))
    sourced = ALL_KINDS[4].model_copy(update={"data_provenance": "source"})
    assert any("citation" in p for p in check_draft(sourced, Lang.UZ, KB))
    concept = ALL_KINDS[1].model_copy(deep=True)
    concept.edges[0].label = ""
    assert any("relationship labels" in p for p in check_draft(concept, Lang.UZ, KB))
    english = while_loop(nodes=[NodeD(id="s", label="Начало работы программы", shape="start"),
                                NodeD(id="e", label="Конец работы программы", shape="end")],
                         edges=[EdgeD(source="s", target="e")], title="Блок-схема", caption="Как работает программа",
                         alt_text="x")
    assert any("write labels in Uzbek" in p for p in check_draft(english, Lang.UZ, KB))
    kb = KnowledgeBase(project_id="p")
    kb.approve_term("variables", Lang.UZ, "o‘zgaruvchi", forbidden=["variabl"])
    bad_term = while_loop(caption="Har bir variabl qiymat oladi")
    assert any("approved term" in p for p in check_draft(bad_term, Lang.UZ, kb))


def test_plan_must_cover_requests_and_keep_illustrations():
    from osamu_dazai.domain.visuals import RenderStrategy as RS
    from osamu_dazai.domain.visuals import VisualSpec

    reqs = {"vis_ch1_1": VisualSpec(kind=VisualKind.FLOWCHART, purpose="p", render_strategy=RS.MERMAID),
            "vis_ch1_2": VisualSpec(kind=VisualKind.ILLUSTRATION, purpose="p", render_strategy=RS.IMAGE_GEN)}
    assert "exactly one spec per visual request" in check_plan(VisualPlanDraft(visuals=[while_loop()]), reqs, Lang.UZ, KB)[0]
    switched = while_loop(visual_id="vis_ch1_2")
    problems = check_plan(VisualPlanDraft(visuals=[while_loop(), switched]), reqs, Lang.UZ, KB)
    assert any("keep it an illustration" in p for p in problems)


# ---- end to end -------------------------------------------------------------------
@pytest.fixture
def written_book():
    graph, ids = build_graph(graph_draft(12), "c")
    course = assemble_course(curriculum_draft(12, 3, 6), brief(), "prj_1", graph, ids)
    plans = plan_chapters(course, graph)
    drafts = [chapter_draft(p, graph) for p in plans]
    drafts[1].sections[3].blocks.append(BlockDraft(
        kind="visual", visual_kind="illustration", title="Kompyuter oldidagi o‘quvchi",
        visual_purpose="mavzuga qiziqish uyg‘otish",
        visual_description="Bir o‘quvchi maktab kompyuter xonasida dastur yozmoqda, ekranda rangli bloklar"))
    mock = MockProvider().queue(BOOK_STAGE, *[d.model_dump_json() for d in drafts])
    reg = ProviderRegistry()
    reg.register_llm(mock)
    book = run(BookWriter(reg).write(course, graph, KnowledgeBase(project_id="p"), words_per_chapter=40)).book
    return course, graph, book


def plan_for(book) -> list[str]:
    replies = []
    for ch in book.chapters:
        visuals = []
        for vid, spec in ch.visual_specs.items():
            if spec.kind is VisualKind.ILLUSTRATION:
                visuals.append(V(visual_id=vid, kind=VisualKind.ILLUSTRATION, title="O‘quvchi",
                                 image_prompt="A teenage student at a school computer lab writing a program, "
                                              "colourful blocks on the screen, friendly classroom atmosphere"))
            else:
                visuals.append(while_loop(visual_id=vid))
        replies.append(VisualPlanDraft(visuals=visuals).model_dump_json())
    return replies


def test_build_visuals_end_to_end(written_book, tmp_path):
    course, graph, book = written_book
    llm = MockProvider().queue(STAGE, *plan_for(book))
    images = MockImageProvider()
    reg = ProviderRegistry()
    reg.register_llm(llm)
    reg.register_image(images)
    res = run(VisualBuilder(reg, AssetStore(tmp_path)).build(book, course, graph, KnowledgeBase(project_id="p")))

    assert len(res.visuals) == 4 and len(res.images) == 4  # 3 flowcharts + 1 illustration
    svg_img = next(i for i in res.images if i.provider == "dazai-svg")
    ch1 = res.book.chapters[0]
    assert svg_img.chapter_id == ch1.id and svg_img.section_id == ch1.sections[3].id
    assert svg_img.concept_ids == ch1.introduces_concepts and svg_img.filename.endswith("vis_ch1_1.svg")
    ET.fromstring((tmp_path / svg_img.filename).read_text(encoding="utf-8"))
    illus = next(i for i in res.images if i.provider == "mock")
    assert (tmp_path / illus.filename).read_bytes().startswith(b"\x89PNG")
    assert "no text" not in illus.prompt and "Educational illustration for learners aged 13-16" in illus.prompt
    assert images.requests[0].negative_prompt.startswith("text, letters")
    # specs now carry the structured data and the render strategy
    spec = ch1.visual_specs["vis_ch1_1"]
    assert spec.render_strategy is RenderStrategy.MERMAID and spec.data["nodes"][0]["label"] == "Boshlash"
    flow_visual = next(v for v in res.visuals if v.chapter_id == ch1.id)
    assert flow_visual.source.startswith("flowchart TD") and flow_visual.image_id == svg_img.id
    # markdown embeds the figures
    md = render_student_book(res.book, figures=res.figures)
    assert "![Rasm 1.1: Dastur qadamlari](prj_1/vis_ch1_1.svg)" in md


def test_bad_plan_is_sent_back(written_book, tmp_path):
    course, graph, book = written_book
    replies = plan_for(book)
    bad = VisualPlanDraft.model_validate_json(replies[0])
    bad.visuals[0].edges.append(EdgeD(source="c", target="nowhere"))
    llm = MockProvider().queue(STAGE, bad.model_dump_json(), *replies)
    reg = ProviderRegistry()
    reg.register_llm(llm)
    reg.register_image(MockImageProvider())
    res = run(VisualBuilder(reg, AssetStore(tmp_path)).build(book, course, graph, KnowledgeBase(project_id="p")))
    assert res.attempts[1] == 2 and "unknown nodes" in llm.requests[1].messages[-1].content


def test_images_can_be_skipped(written_book, tmp_path):
    course, graph, book = written_book
    reg = ProviderRegistry()
    reg.register_llm(MockProvider().queue(STAGE, *plan_for(book)))
    res = run(VisualBuilder(reg, AssetStore(tmp_path), generate_images=False).build(
        book, course, graph, KnowledgeBase(project_id="p")))
    assert all(i.provider == "dazai-svg" for i in res.images) and len(res.visuals) == 4
    illus = next(v for v in res.visuals if v.spec.kind is VisualKind.ILLUSTRATION)
    assert illus.image_id is None and illus.spec.image_prompt
