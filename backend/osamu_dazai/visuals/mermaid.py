"""Mermaid source for the same specs (used by HTML/Markdown outputs)."""

from __future__ import annotations

import re

from osamu_dazai.visuals.specs import VisualDraft


def _q(s: str) -> str:
    return s.replace('"', "'").replace("\n", " ")


def _mid(s: str) -> str:
    return "n_" + re.sub(r"\W", "_", s)


_SHAPES = {"start": '(["{}"])', "end": '(["{}"])', "process": '["{}"]', "decision": '{{"{}"}}', "io": '[/"{}"/]'}


def to_mermaid(d: VisualDraft, kind: str) -> str | None:
    if kind == "flow":
        lines = ["flowchart TD"]
        lines += [f"    {_mid(n.id)}{_SHAPES[n.shape].format(_q(n.label))}" for n in d.nodes]
        for e in d.edges:
            arrow = f'-- "{_q(e.label)}" -->' if e.label else "-->"
            lines.append(f"    {_mid(e.source)} {arrow} {_mid(e.target)}")
        return "\n".join(lines)
    if kind == "mindmap":
        children: dict[str, list[str]] = {}
        for e in d.edges:
            children.setdefault(e.source, []).append(e.target)
        labels = {n.id: n.label for n in d.nodes}
        lines = ["mindmap", f"  root(({_q(labels[d.root])}))"]

        def walk(n: str, depth: int) -> None:
            for k in children.get(n, []):
                lines.append("  " * depth + _q(labels[k]))
                walk(k, depth + 1)

        walk(d.root, 2)
        return "\n".join(lines)
    if kind == "timeline":
        return "\n".join(["timeline", f"    title {_q(d.title)}",
                          *(f"    {_q(ev.date)} : {_q(ev.label)}" for ev in d.events)])
    if kind == "chart" and d.chart_type == "pie":
        return "\n".join([f'pie title {_q(d.title)}',
                          *(f'    "{_q(c)}" : {v:g}' for c, v in zip(d.categories, d.series[0].values, strict=True))])
    return None  # comparison / memory / bar / line: SVG only
