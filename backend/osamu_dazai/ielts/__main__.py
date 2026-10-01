"""Command line for IELTS: validate / repair documents, generate Reading, Listening, Writing, Speaking.

    python -m osamu_dazai.ielts validate test.docx [--listening]
    python -m osamu_dazai.ielts fix broken.docx fixed.docx [--threshold 0.8] [--listening]
    python -m osamu_dazai.ielts generate out.docx --config providers.toml --topics "…" "…" "…"
    python -m osamu_dazai.ielts listening out_dir --config providers.toml --topics "…" "…" "…" "…"
    python -m osamu_dazai.ielts writing out_dir --config providers.toml --module academic --task1 "…" --task2 "…"
    python -m osamu_dazai.ielts speaking out_dir --config providers.toml --theme "…" [--band 7]

Plain-text input (.txt / .md) is accepted too. Exit code 0 = clean, 1 = issues.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from osamu_dazai.ielts import contract as C
from osamu_dazai.ielts.exporter import repair_docx, repair_text, validate_docx
from osamu_dazai.ielts.validators import IELTSDocumentValidator


def _validate(path: Path, style: C.SectionStyle = C.READING) -> int:
    if path.suffix.lower() == ".docx":
        result = validate_docx(path, style=style)
    else:
        result = IELTSDocumentValidator(style).validate_text(path.read_text(encoding="utf-8"))
    for issue in result.issues:
        print(issue.render(), end="\n\n")
    errors, warnings = len(result.errors), len(result.issues) - len(result.errors)
    print(f"{'PASSED' if result.passed else 'FAILED'}: {errors} error(s), {warnings} warning(s)")
    return 0 if result.passed else 1


def _fix(src: Path, dest: Path, threshold: float, style: C.SectionStyle = C.READING) -> int:
    if src.suffix.lower() == ".docx":
        out = repair_docx(src, dest, threshold=threshold, style=style)
    else:
        out = repair_text(src.read_text(encoding="utf-8"), dest, threshold=threshold, style=style)
    print(out.report.render())
    print("\nDetected question groups:")
    for line in out.report.group_summary():
        print("  " + line)
    print(f"\n{'Exported → ' + str(dest) if out.exported else 'NOT exported (see errors / review flags above)'}")
    return 0 if out.exported else 1


def _generate(config: Path, topics: list[str], dest: Path, title: str) -> int:
    import asyncio

    from osamu_dazai.ielts.exporter import ExportBlocked, export_reading_test
    from osamu_dazai.ielts.generator import GenerationFailed, IELTSReadingGenerator, default_plan
    from osamu_dazai.providers import ProviderConfig, ProviderRegistry

    registry = ProviderRegistry.from_config(ProviderConfig.load(config))
    plan = default_plan((topics[0], topics[1], topics[2]), title=title)
    try:
        report = asyncio.run(IELTSReadingGenerator(registry).generate(plan))
        export_reading_test(report.test, dest)
    except GenerationFailed as e:
        print(f"Generation failed: {e}")
        return 1
    except ExportBlocked as e:
        print(e)
        return 1
    dest.with_suffix(".json").write_text(report.test.model_dump_json(indent=2), encoding="utf-8")
    print(f"Generated {report.test.question_count()} questions; LLM attempts per passage: {report.attempts}")
    print(f"Exported → {dest} (+ {dest.with_suffix('.json').name}). Status: DRAFT — needs human review.")
    return 0


def _registry(config: Path):  # noqa: ANN202
    from osamu_dazai.providers import ProviderConfig, ProviderRegistry

    return ProviderRegistry.from_config(ProviderConfig.load(config))


def _listening(out: Path, config: Path, topics: list[str]) -> int:
    import asyncio

    from osamu_dazai.ielts.docx_io import docx_bytes, read_docx
    from osamu_dazai.ielts.exporter import ExportBlocked
    from osamu_dazai.ielts.listening import IELTSListeningGenerator, default_plan, render_paper, render_transcript
    from osamu_dazai.ielts.validators import IELTSDocumentValidator
    from osamu_dazai.pipeline.llm_stage import StageFailed
    from osamu_dazai.visuals.svg import render_plan

    try:
        rep = asyncio.run(IELTSListeningGenerator(_registry(config)).generate(default_plan(tuple(topics))))
    except StageFailed as e:
        print(e)
        return 1
    data = docx_bytes(render_paper(rep.test))
    result = IELTSDocumentValidator(C.LISTENING).validate_lines(read_docx(data).lines)
    if not result.passed:
        print(ExportBlocked(result))
        return 1
    out.mkdir(parents=True, exist_ok=True)
    (out / "listening_paper.docx").write_bytes(data)
    (out / "listening_transcript.md").write_text(render_transcript(rep.test), encoding="utf-8")
    (out / "listening.json").write_text(rep.test.model_dump_json(indent=2), encoding="utf-8")
    for part in rep.test.parts:
        if part.plan:
            svg = render_plan([(i.label, i.x, i.y, i.w, i.h) for i in part.plan], part.plan_title, part.context)
            (out / f"listening_part{part.number}_plan.svg").write_text(svg.svg, encoding="utf-8")
    print(f"Listening: {rep.test.question_count()} questions, attempts {rep.attempts} → {out} (DRAFT)")
    return 0


def _writing(out: Path, config: Path, module: str, task1: str, task2: str, task2_type: str) -> int:
    import asyncio

    from osamu_dazai.ielts.writing import IELTSWritingGenerator, WritingSpec, render_samples, render_tasks, task1_figure
    from osamu_dazai.pipeline.llm_stage import StageFailed

    try:
        ws, attempts = asyncio.run(IELTSWritingGenerator(_registry(config)).generate(
            WritingSpec(module, task1, task2, task2_type)))  # type: ignore[arg-type]
    except StageFailed as e:
        print(e)
        return 1
    out.mkdir(parents=True, exist_ok=True)
    (out / "writing_tasks.md").write_text(render_tasks(ws), encoding="utf-8")
    (out / "writing_samples_and_feedback.md").write_text(render_samples(ws), encoding="utf-8")
    (out / "writing.json").write_text(ws.model_dump_json(indent=2), encoding="utf-8")
    if (fig := task1_figure(ws)) is not None:
        (out / "writing_task1.svg").write_text(fig.svg, encoding="utf-8")
    print(f"Writing ({module}): attempts {attempts} → {out} (DRAFT)")
    return 0


def _speaking(out: Path, config: Path, theme: str, band: float) -> int:
    import asyncio

    from osamu_dazai.ielts.speaking import (
        IELTSSpeakingGenerator,
        SpeakingSpec,
        render_cue_card,
        render_examiner_script,
        render_model_answers,
    )
    from osamu_dazai.pipeline.llm_stage import StageFailed

    try:
        test, attempts = asyncio.run(IELTSSpeakingGenerator(_registry(config)).generate(
            SpeakingSpec(theme=theme, target_band=band)))
    except StageFailed as e:
        print(e)
        return 1
    out.mkdir(parents=True, exist_ok=True)
    (out / "speaking_examiner_script.md").write_text(render_examiner_script(test), encoding="utf-8")
    (out / "speaking_cue_card.md").write_text(render_cue_card(test), encoding="utf-8")
    (out / "speaking_model_answers.md").write_text(render_model_answers(test), encoding="utf-8")
    (out / "speaking.json").write_text(test.model_dump_json(indent=2), encoding="utf-8")
    print(f"Speaking: attempts {attempts} → {out} (DRAFT)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m osamu_dazai.ielts")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="generate a 40-question Academic Reading test (uses configured LLM)")
    g.add_argument("dest", type=Path)
    g.add_argument("--config", type=Path, required=True, help="providers.toml")
    g.add_argument("--topics", nargs=3, required=True, metavar=("P1", "P2", "P3"))
    g.add_argument("--title", default="Academic Reading Practice Test")
    v = sub.add_parser("validate", help="run the IELTS document validator")
    v.add_argument("path", type=Path)
    v.add_argument("--listening", action="store_true", help="Listening paper (PART N sections)")
    f = sub.add_parser("fix", help="IELTS Format Repair: fix structure, validate, export DOCX")
    f.add_argument("src", type=Path)
    f.add_argument("dest", type=Path)
    f.add_argument("--threshold", type=float, default=0.8)
    f.add_argument("--listening", action="store_true", help="Listening paper (PART N sections)")
    li = sub.add_parser("listening", help="generate a 40-question Listening test (paper DOCX + audio script)")
    li.add_argument("out", type=Path)
    li.add_argument("--config", type=Path, required=True)
    li.add_argument("--topics", nargs=4, required=True, metavar=("P1", "P2", "P3", "P4"))
    wr = sub.add_parser("writing", help="generate Writing Task 1 + 2 with band samples and feedback")
    wr.add_argument("out", type=Path)
    wr.add_argument("--config", type=Path, required=True)
    wr.add_argument("--module", choices=["academic", "general_training"], default="academic")
    wr.add_argument("--task1", required=True)
    wr.add_argument("--task2", required=True)
    wr.add_argument("--task2-type", default="opinion",
                    choices=["opinion", "discussion", "problem_solution", "advantages_disadvantages", "two_part"])
    sp = sub.add_parser("speaking", help="generate a Speaking test (Parts 1-3) with model answers")
    sp.add_argument("out", type=Path)
    sp.add_argument("--config", type=Path, required=True)
    sp.add_argument("--theme", required=True)
    sp.add_argument("--band", type=float, default=7.0)
    a = ap.parse_args(argv)
    if a.cmd == "listening":
        return _listening(a.out, a.config, a.topics)
    if a.cmd == "writing":
        return _writing(a.out, a.config, a.module, a.task1, a.task2, a.task2_type)
    if a.cmd == "speaking":
        return _speaking(a.out, a.config, a.theme, a.band)
    style = C.LISTENING if getattr(a, "listening", False) else C.READING
    if a.cmd == "validate":
        return _validate(a.path, style)
    if a.cmd == "generate":
        return _generate(a.config, a.topics, a.dest, a.title)
    return _fix(a.src, a.dest, a.threshold, style)


if __name__ == "__main__":
    sys.exit(main())
