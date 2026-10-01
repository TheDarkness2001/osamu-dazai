"""Student-book generation on top of the course design (mock LLM)."""

import asyncio

import pytest

from osamu_dazai.documents.markdown import render_student_book
from osamu_dazai.domain.common import Lang
from osamu_dazai.domain.knowledge import KnowledgeBase
from osamu_dazai.knowledge import contains_term, find_forbidden, normalize_for_match
from osamu_dazai.pipeline.book import STAGE, BookWriter, ChapterContext, check_chapter, plan_chapters
from osamu_dazai.pipeline.curriculum import assemble_course, build_graph
from osamu_dazai.pipeline.llm_stage import StageFailed
from osamu_dazai.providers import ProviderRegistry
from osamu_dazai.providers.llm import MockProvider
from osamu_dazai.quality.code import check_syntax, run_and_compare
from tests.fixtures.book_sample import chapter_draft
from tests.fixtures.course_sample import curriculum_draft, graph_draft
from tests.test_course_design import brief

run = asyncio.run


@pytest.fixture(scope="module")
def course_and_graph():
    graph, ids = build_graph(graph_draft(12), "c")
    course = assemble_course(curriculum_draft(12, 3, 6), brief(), "prj_1", graph, ids)
    return course, graph.model_copy(update={"course_id": course.id})


def writer(*replies, **kw):
    mock = MockProvider().queue(STAGE, *[r.model_dump_json() for r in replies])
    reg = ProviderRegistry()
    reg.register_llm(mock)
    return BookWriter(reg, **kw), mock


def ctx_for(plan, graph, kb=None, lang=Lang.UZ, words=40, execute=False):
    return ChapterContext(plan=plan, graph=graph, kb=kb or KnowledgeBase(project_id="p"), lang=lang,
                          target_words=words, execute_code=execute)


# ---- planning -----------------------------------------------------------------
def test_chapter_plan_per_module(course_and_graph):
    course, graph = course_and_graph
    plans = plan_chapters(course, graph)
    assert [p.number for p in plans] == [1, 2, 3]
    assert sum(len(p.lessons) for p in plans) == 18
    assert plans[0].known == [] and plans[1].known == plans[0].introduces
    assert set(plans[0].later) == set(plans[1].introduces + plans[2].introduces)
    assert len(plan_chapters(course, graph, 5)) == 5
    with pytest.raises(ValueError):
        plan_chapters(course, graph, 99)


# ---- full book ----------------------------------------------------------------
def test_write_book_end_to_end(course_and_graph):
    course, graph = course_and_graph
    plans = plan_chapters(course, graph)
    kb = KnowledgeBase(project_id="prj_1")
    kb.approve_term("variables", Lang.UZ, "o‘zgaruvchi", forbidden=["variabl"])
    w, mock = writer(*[chapter_draft(p, graph) for p in plans])
    res = run(w.write(course, graph, kb, words_per_chapter=40))
    book = res.book
    assert [c.number for c in book.chapters] == [1, 2, 3] and res.attempts == {1: 1, 2: 1, 3: 1}
    ch1 = book.chapters[0]
    assert ch1.introduces_concepts == plans[0].introduces
    assert {g.id for g in ch1.exercises} == {"qg_ch1_guided_practice", "qg_ch1_quiz"}
    refs = [b for s in ch1.sections for b in s.blocks if b.kind == "question_ref"]
    assert len(refs) == 2
    assert ch1.visual_specs["vis_ch1_1"].render_strategy.value == "mermaid"
    assert [q.number for g in ch1.exercises for q in g.questions] == [1, 2, 3]
    # knowledge base carried forward
    ch2_prompt = mock.requests[1].messages[0].content
    assert "Earlier chapters" in ch2_prompt and "ch1-ism-chiqarish" in ch2_prompt
    assert "variables → o‘zgaruvchi (never: variabl)" in ch2_prompt
    assert "Technical terms in English, with the Uzbek (Latin script) term first" in ch2_prompt
    assert {s.chapter_number for s in res.kb.chapter_summaries} == {1, 2, 3}
    assert kb.chapter_summaries == []  # caller's KB untouched; result.kb is the updated copy
    assert any(e.term == "chiqarish" for e in book.glossary)


def test_markdown_rendering(course_and_graph):
    course, graph = course_and_graph
    plans = plan_chapters(course, graph)
    w, _ = writer(*[chapter_draft(p, graph) for p in plans])
    book = run(w.write(course, graph, KnowledgeBase(project_id="p"), words_per_chapter=40)).book
    md = render_student_book(book)
    assert md.startswith(f"# {course.title}") and "## Bob 1." in md and "```python" in md
    assert "*[Rasm 1.1: Dastur qadamlari]*" in md and "## Lug‘at" in md and "## Javoblar" in md
    body, key = md.split("## Javoblar")
    assert "Ekranga matn chiqaradi." not in body and "Ekranga matn chiqaradi." in key
    assert "Javoblar" not in render_student_book(book, answer_key=False)


# ---- checks fed back to the model --------------------------------------------------
def test_forbidden_term_sent_back(course_and_graph):
    course, graph = course_and_graph
    plans = plan_chapters(course, graph)
    kb = KnowledgeBase(project_id="p")
    kb.approve_term("variables", Lang.UZ, "o‘zgaruvchi", forbidden=["variabl"])
    bad = chapter_draft(plans[0], graph, extra_text="Har bir variabl nomga ega.")
    w, mock = writer(bad, *[chapter_draft(p, graph) for p in plans])
    res = run(w.write(course, graph, kb, words_per_chapter=40))
    assert res.attempts[1] == 2
    assert "use the approved term 'o‘zgaruvchi' instead of 'variabl'" in mock.requests[1].messages[-1].content


def test_structural_problems(course_and_graph):
    course, graph = course_and_graph
    plan = plan_chapters(course, graph)[0]
    d = chapter_draft(plan, graph, code="print('Ali'", include_review=False)
    d.sections[2].blocks = [d.sections[2].blocks[0]]
    d.sections[2].blocks[0].text = "Bu yerda hech narsa tushuntirilmaydi. " * 5
    d.exercises = d.exercises[:2]
    problems = check_chapter(d, ctx_for(plan, graph))
    joined = "\n".join(problems)
    assert "add a 'review' section" in joined
    assert "Python syntax error" in joined
    assert "give at least 3 exercises" in joined
    assert "is never explained" in joined


def test_glossary_must_stay_consistent(course_and_graph):
    course, graph = course_and_graph
    plans = plan_chapters(course, graph)
    first = chapter_draft(plans[0], graph)
    # chapter 2 redefines chapter 1's term with a different translation, three times
    clash = chapter_draft(plans[1], graph)
    clash.glossary.append(first.glossary[0].model_copy(update={"term": "boshqa nom"}))
    w, _ = writer(first, clash, clash, clash)
    with pytest.raises(StageFailed) as e:
        run(w.write(course, graph, KnowledgeBase(project_id="p"), words_per_chapter=40, only=[1, 2]))
    assert any("already used term" in p for p in e.value.problems)


def test_language_script_check(course_and_graph):
    course, graph = course_and_graph
    plan = plan_chapters(course, graph)[0]
    d = chapter_draft(plan, graph)
    problems = check_chapter(d, ctx_for(plan, graph, lang=Lang.RU))
    assert "write the chapter in Russian" in problems


def test_too_short(course_and_graph):
    course, graph = course_and_graph
    plan = plan_chapters(course, graph)[0]
    problems = check_chapter(chapter_draft(plan, graph), ctx_for(plan, graph, words=5000))
    assert any("too short" in p for p in problems)


def test_execute_code_opt_in(course_and_graph):
    course, graph = course_and_graph
    plan = plan_chapters(course, graph)[0]
    wrong = chapter_draft(plan, graph, code="print(2 + 2)", expected="5")
    assert not any("expected output" in p for p in check_chapter(wrong, ctx_for(plan, graph)))
    problems = check_chapter(wrong, ctx_for(plan, graph, execute=True))
    assert any("expected output '5' but the program prints '4'" in p for p in problems)
    right = chapter_draft(plan, graph, code="print(2 + 2)", expected="4")
    assert check_chapter(right, ctx_for(plan, graph, execute=True)) == []


def test_later_concepts_are_warnings_not_blockers(course_and_graph):
    course, graph = course_and_graph
    plans = plan_chapters(course, graph)
    d = chapter_draft(plans[0], graph, extra_text="Keyinroq For loops ham o‘rganamiz.")
    w, _ = writer(d, *[chapter_draft(p, graph) for p in plans[1:]])
    res = run(w.write(course, graph, KnowledgeBase(project_id="p"), words_per_chapter=40))
    assert res.attempts[1] == 1
    assert any(i.code == "book.concept_before_introduction" and "For loops" in i.problem for i in res.warnings)


# ---- helpers -------------------------------------------------------------------------
def test_uzbek_apostrophes_match_but_are_not_rewritten():
    assert normalize_for_match("Oʻzgaruvchi") == normalize_for_match("o'zgaruvchi") == normalize_for_match("o‘zgaruvchi")
    assert contains_term("Har bir oʻzgaruvchi nomga ega.", "o'zgaruvchi")
    assert not contains_term("o'zgaruvchilar", "o'zgaruvchi")  # whole words only
    kb = KnowledgeBase(project_id="p")
    kb.approve_term("variables", Lang.UZ, "o‘zgaruvchi", forbidden=["variabl"])
    assert find_forbidden("Bu variabl emas.", kb, Lang.UZ)[0].preferred == "o‘zgaruvchi"
    assert find_forbidden("Bu variabl emas.", kb, Lang.RU) == []


def test_code_syntax_checkers():
    assert check_syntax("python", "x = 1\nprint(x)").ok
    assert not check_syntax("python", "print(").ok
    js_ok, js_bad = check_syntax("javascript", "let x = 1;\nconsole.log(x);"), check_syntax("js", "let = ;")
    assert js_ok.ok
    assert js_bad.skipped or not js_bad.ok
    assert check_syntax("kotlin", "fun main() {}").skipped
    assert run_and_compare("python", "name = input()", "x").skipped
