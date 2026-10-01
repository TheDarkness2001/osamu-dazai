"""Course design from the command line.

    python -m osamu_dazai.pipeline plan "Create a beginner Python textbook for Uzbek teenagers." \
        --config config/providers.toml --out brief.json
    python -m osamu_dazai.pipeline confirm brief.json --all            # or: --fields schedule languages
    python -m osamu_dazai.pipeline design brief.json --config config/providers.toml --out-dir course/
    python -m osamu_dazai.pipeline term kb.json variables uz "o‘zgaruvchi" --forbid variabl
    python -m osamu_dazai.pipeline write course/ --config config/providers.toml --kb kb.json
    python -m osamu_dazai.pipeline teach course/ --config config/providers.toml --style "project-based"
    python -m osamu_dazai.pipeline visuals course/ --config config/providers.toml [--no-images]
    python -m osamu_dazai.pipeline assess course/ --config config/providers.toml --versions 4 --code-language python
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from osamu_dazai.documents.markdown import render_student_book, render_teacher_guide
from osamu_dazai.domain.common import Lang
from osamu_dazai.domain.content import StudentBook
from osamu_dazai.domain.curriculum import Course
from osamu_dazai.domain.graph import ConceptGraph
from osamu_dazai.domain.knowledge import KnowledgeBase
from osamu_dazai.domain.project import BriefField, CourseBrief, FieldOrigin
from osamu_dazai.graph import to_mermaid
from osamu_dazai.pipeline.book import BookWriter
from osamu_dazai.pipeline.curriculum import BriefNotConfirmed, CurriculumArchitect
from osamu_dazai.pipeline.llm_stage import StageFailed
from osamu_dazai.pipeline.planner import EducationalPlanner, accept_all, confirm
from osamu_dazai.pipeline.teacher import TeacherGuideWriter
from osamu_dazai.providers import ProviderConfig, ProviderRegistry


def _show(brief: CourseBrief) -> None:
    for name in type(brief).model_fields:
        v = getattr(brief, name)
        if isinstance(v, BriefField):
            mark = "✓" if v.origin is FieldOrigin.CONFIRMED else "?"
            value = v.value.model_dump(mode="json") if hasattr(v.value, "model_dump") else v.value
            print(f"  [{mark}] {name}: {value}")


def _write(a: argparse.Namespace, registry: ProviderRegistry) -> int:
    course = Course.model_validate_json((a.course_dir / "course.json").read_text(encoding="utf-8"))
    graph = ConceptGraph.model_validate_json((a.course_dir / "learning_graph.json").read_text(encoding="utf-8"))
    kb = (KnowledgeBase.model_validate_json(a.kb.read_text(encoding="utf-8")) if a.kb
          else KnowledgeBase(project_id=course.project_id))
    try:
        res = asyncio.run(BookWriter(registry, execute_code=a.execute_code).write(
            course, graph, kb, n_chapters=a.chapters, words_per_chapter=a.words, only=a.only))
    except StageFailed as e:
        print(e)
        return 1
    out = a.course_dir
    (out / "student_book.json").write_text(res.book.model_dump_json(indent=2), encoding="utf-8")
    (out / "student_book.md").write_text(render_student_book(res.book), encoding="utf-8")
    (out / "knowledge_base.json").write_text(res.kb.model_dump_json(indent=2), encoding="utf-8")
    (out / "book_warnings.txt").write_text("\n\n".join(i.render() for i in res.warnings) or "No warnings.",
                                           encoding="utf-8")
    print(f"{len(res.book.chapters)} chapter(s) written; attempts {res.attempts}; {len(res.warnings)} warning(s)")
    print(f"→ {out}/student_book.md (DRAFT — needs human review)")
    return 0


def _teach(a: argparse.Namespace, registry: ProviderRegistry) -> int:
    d = a.course_dir
    course = Course.model_validate_json((d / "course.json").read_text(encoding="utf-8"))
    graph = ConceptGraph.model_validate_json((d / "learning_graph.json").read_text(encoding="utf-8"))
    book = StudentBook.model_validate_json((d / "student_book.json").read_text(encoding="utf-8"))
    kb_path = d / "knowledge_base.json"
    kb = (KnowledgeBase.model_validate_json(kb_path.read_text(encoding="utf-8")) if kb_path.exists()
          else KnowledgeBase(project_id=course.project_id))
    try:
        res = asyncio.run(TeacherGuideWriter(registry).write(course, graph, book, kb, n_chapters=a.chapters,
                                                             teaching_style=a.style))
    except (StageFailed, ValueError) as e:
        print(e)
        return 1
    (d / "teacher_guide.json").write_text(res.guide.model_dump_json(indent=2), encoding="utf-8")
    (d / "teacher_guide.md").write_text(render_teacher_guide(res.guide, course, book), encoding="utf-8")
    print(f"Teacher's guide: {len(res.guide.lessons)} lesson plans; attempts {res.attempts}")
    print(f"→ {d}/teacher_guide.md (DRAFT — needs human review)")
    return 0


def _visuals(a: argparse.Namespace, registry: ProviderRegistry) -> int:
    import json

    from osamu_dazai.storage.assets import AssetStore
    from osamu_dazai.visuals.builder import VisualBuilder

    d = a.course_dir
    course = Course.model_validate_json((d / "course.json").read_text(encoding="utf-8"))
    graph = ConceptGraph.model_validate_json((d / "learning_graph.json").read_text(encoding="utf-8"))
    book = StudentBook.model_validate_json((d / "student_book.json").read_text(encoding="utf-8"))
    kb_path = d / "knowledge_base.json"
    kb = (KnowledgeBase.model_validate_json(kb_path.read_text(encoding="utf-8")) if kb_path.exists()
          else KnowledgeBase(project_id=course.project_id))
    builder = VisualBuilder(registry, AssetStore(d / "assets"), generate_images=not a.no_images)
    try:
        res = asyncio.run(builder.build(book, course, graph, kb))
    except StageFailed as e:
        print(e)
        return 1
    figures = {vid: f"assets/{path}" for vid, path in res.figures.items()}
    # figure map read by the document exporters (osamu_dazai.documents.figures.load_figures)
    (d / "figures.json").write_text(json.dumps(figures, indent=2, ensure_ascii=False), encoding="utf-8")
    (d / "student_book.json").write_text(res.book.model_dump_json(indent=2), encoding="utf-8")
    (d / "student_book.md").write_text(render_student_book(res.book, figures=figures), encoding="utf-8")
    (d / "visuals.json").write_text(json.dumps([v.model_dump(mode="json") for v in res.visuals], indent=2,
                                               ensure_ascii=False), encoding="utf-8")
    (d / "images.json").write_text(json.dumps([i.model_dump(mode="json") for i in res.images], indent=2,
                                              ensure_ascii=False), encoding="utf-8")
    print(f"{len(res.visuals)} visual(s), {len(res.images)} file(s) in {d / 'assets'}; attempts {res.attempts}")
    return 0


def _assess(a: argparse.Namespace, registry: ProviderRegistry) -> int:
    import json

    from osamu_dazai.documents.markdown import render_answer_key, render_assessment
    from osamu_dazai.questions.generator import AssessmentGenerator
    from osamu_dazai.questions.shuffle import make_versions

    d = a.course_dir
    course = Course.model_validate_json((d / "course.json").read_text(encoding="utf-8"))
    graph = ConceptGraph.model_validate_json((d / "learning_graph.json").read_text(encoding="utf-8"))
    kb_path = d / "knowledge_base.json"
    kb = (KnowledgeBase.model_validate_json(kb_path.read_text(encoding="utf-8")) if kb_path.exists()
          else KnowledgeBase(project_id=course.project_id))
    try:
        res = asyncio.run(AssessmentGenerator(registry).generate_all(course, graph, kb, code_language=a.code_language))
    except StageFailed as e:
        print(e)
        return 1
    out = d / "assessments"
    out.mkdir(exist_ok=True)
    lang = course.languages.assessment
    everything = []
    for k, master in enumerate(res.assessments, start=1):
        stem = f"{k:02d}"
        (out / f"{stem}_master.md").write_text(render_assessment(master, lang), encoding="utf-8")
        (out / f"{stem}_master_key.md").write_text(render_answer_key(master, lang), encoding="utf-8")
        everything.append(master)
        if a.versions > 1 and any(g.questions and g.type.value == "multiple_choice" for g in master.groups):
            for v in make_versions(master, a.versions):
                (out / f"{stem}_version_{v.version_label}.md").write_text(render_assessment(v, lang), encoding="utf-8")
                (out / f"{stem}_version_{v.version_label}_key.md").write_text(render_answer_key(v, lang),
                                                                              encoding="utf-8")
                everything.append(v)
    (d / "assessments.json").write_text(json.dumps([x.model_dump(mode="json") for x in everything], indent=2,
                                                   ensure_ascii=False), encoding="utf-8")
    print(f"{len(res.assessments)} assessment(s), {len(everything)} file set(s) → {out}; attempts {res.attempts}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m osamu_dazai.pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="infer a course brief from a request")
    p.add_argument("request")
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--out", type=Path, default=Path("brief.json"))
    c = sub.add_parser("confirm", help="confirm inferred brief fields")
    c.add_argument("brief", type=Path)
    g = c.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true")
    g.add_argument("--fields", nargs="+")
    d = sub.add_parser("design", help="learning graph + curriculum from a confirmed brief")
    d.add_argument("brief", type=Path)
    d.add_argument("--config", type=Path, required=True)
    d.add_argument("--out-dir", type=Path, default=Path("course"))
    d.add_argument("--project-id", default="prj_cli")
    t = sub.add_parser("term", help="approve a term translation in the knowledge base (e.g. variable = o‘zgaruvchi)")
    t.add_argument("kb", type=Path, help="knowledge base JSON (created if missing)")
    t.add_argument("key", help="language-neutral key, e.g. variables")
    t.add_argument("lang", choices=[x.value for x in Lang])
    t.add_argument("preferred")
    t.add_argument("--forbid", nargs="*", default=[])
    w = sub.add_parser("write", help="write the student book from a designed course")
    w.add_argument("course_dir", type=Path, help="folder with course.json and learning_graph.json")
    w.add_argument("--config", type=Path, required=True)
    w.add_argument("--kb", type=Path, help="knowledge base JSON with approved terms")
    w.add_argument("--chapters", type=int, help="number of chapters (default: one per module)")
    w.add_argument("--words", type=int, default=2500, help="target words per chapter")
    w.add_argument("--only", type=int, nargs="*", help="write only these chapter numbers")
    w.add_argument("--execute-code", action="store_true",
                   help="run code examples locally to check their expected output (executes AI-written code)")
    tg = sub.add_parser("teach", help="write the teacher's guide for a written student book")
    tg.add_argument("course_dir", type=Path, help="folder with course.json, learning_graph.json, student_book.json")
    tg.add_argument("--config", type=Path, required=True)
    tg.add_argument("--chapters", type=int, help="must match the value used for 'write'")
    tg.add_argument("--style", default="", help="teaching style, e.g. 'project-based, pair work'")
    vz = sub.add_parser("visuals", help="plan and render the book's figures (SVG/Mermaid; images for illustrations)")
    vz.add_argument("course_dir", type=Path, help="folder with course.json, learning_graph.json, student_book.json")
    vz.add_argument("--config", type=Path, required=True)
    vz.add_argument("--no-images", action="store_true", help="skip image generation for illustrations")
    asm = sub.add_parser("assess", help="generate the course's assessments (quizzes, exams, projects) + versions")
    asm.add_argument("course_dir", type=Path)
    asm.add_argument("--config", type=Path, required=True)
    asm.add_argument("--versions", type=int, default=4, help="shuffled versions per assessment (A, B, …)")
    asm.add_argument("--code-language", default="", help="e.g. python / javascript: adds programming tasks")
    a = ap.parse_args(argv)

    if a.cmd == "term":
        kb = (KnowledgeBase.model_validate_json(a.kb.read_text(encoding="utf-8")) if a.kb.exists()
              else KnowledgeBase(project_id="prj_cli"))
        kb.approve_term(a.key, Lang(a.lang), a.preferred, forbidden=a.forbid)
        a.kb.write_text(kb.model_dump_json(indent=2), encoding="utf-8")
        print(f"Approved {a.key} → {a.preferred} ({a.lang}); {len(kb.terms)} term(s) in {a.kb}")
        return 0

    if a.cmd == "confirm":
        brief = CourseBrief.model_validate_json(a.brief.read_text(encoding="utf-8"))
        brief = accept_all(brief) if a.all else confirm(brief, **dict.fromkeys(a.fields, True))
        a.brief.write_text(brief.model_dump_json(indent=2), encoding="utf-8")
        _show(brief)
        return 0

    registry = ProviderRegistry.from_config(ProviderConfig.load(a.config))
    if a.cmd == "write":
        return _write(a, registry)
    if a.cmd == "teach":
        return _teach(a, registry)
    if a.cmd == "visuals":
        return _visuals(a, registry)
    if a.cmd == "assess":
        return _assess(a, registry)
    if a.cmd == "plan":
        res = asyncio.run(EducationalPlanner(registry).plan(a.request))
        a.out.write_text(res.brief.model_dump_json(indent=2), encoding="utf-8")
        print("Brief ([?] = inferred, needs your confirmation):")
        _show(res.brief)
        print("\nQuestions for the teacher:")
        for q in res.questions:
            print(f"  - {q}")
        print(f"\nSaved → {a.out}. Edit it if needed, then: python -m osamu_dazai.pipeline confirm {a.out} --all")
        return 0

    brief = CourseBrief.model_validate_json(a.brief.read_text(encoding="utf-8"))
    try:
        result = asyncio.run(CurriculumArchitect(registry).design(brief, a.project_id))
    except (BriefNotConfirmed, StageFailed) as e:
        print(e)
        return 1
    a.out_dir.mkdir(parents=True, exist_ok=True)
    (a.out_dir / "course.json").write_text(result.course.model_dump_json(indent=2), encoding="utf-8")
    (a.out_dir / "learning_graph.json").write_text(result.graph.model_dump_json(indent=2), encoding="utf-8")
    (a.out_dir / "learning_graph.mmd").write_text(to_mermaid(result.graph), encoding="utf-8")
    issues = "\n\n".join(i.render() for i in [*result.validation.issues, *result.graph_warnings]) or "No issues."
    (a.out_dir / "validation.txt").write_text(issues, encoding="utf-8")
    course = result.course
    print(f"{course.title}: {len(course.modules)} modules, {len(course.all_lessons())} lessons, "
          f"{len(result.graph.concepts)} concepts; attempts {result.attempts}")
    print(f"Validation: {'PASSED' if result.validation.passed else 'FAILED'} → {a.out_dir}/")
    return 0 if result.validation.passed else 1


if __name__ == "__main__":
    sys.exit(main())
