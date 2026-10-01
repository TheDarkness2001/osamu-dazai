"""Deterministic SVG renderers for educational diagrams and charts.

No external tools: layouts are computed here so the same spec always gives
the same figure. Output is print-friendly (white background, dark ink,
Okabe–Ito colour-blind-safe palette) and accessible (<title>/<desc>).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from xml.sax.saxutils import escape

from osamu_dazai.visuals.specs import EdgeD, NodeD, VisualDraft

FONT = "Noto Sans, Segoe UI, Arial, sans-serif"
INK, LINE, MUTED = "#1f2933", "#52606d", "#7b8794"
FILL = {"start": "#e3f2fd", "end": "#e3f2fd", "process": "#f5f7fa", "decision": "#fff8e1", "io": "#e8f5e9"}
STROKE = "#3e4c59"
PALETTE = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#F0E442", "#000000"]
CHAR_W, LINE_H, FONT_SIZE = 7.2, 16, 13
MARGIN = 24


@dataclass(frozen=True)
class RenderedSvg:
    svg: str
    width: int
    height: int


def esc(s: str) -> str:
    return escape(s, {'"': "&quot;"})


def wrap(text: str, width: int = 22) -> list[str]:
    lines: list[str] = []
    cur = ""
    for word in text.split():
        while len(word) > width:  # break very long tokens
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(word[:width])
            word = word[width:]
        if not cur:
            cur = word
        elif len(cur) + 1 + len(word) <= width:
            cur += " " + word
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def text(x: float, y: float, lines: list[str], *, size: int = FONT_SIZE, anchor: str = "middle",
         weight: str = "normal", fill: str = INK) -> str:
    """Multi-line text vertically centred on y."""
    top = y - (len(lines) - 1) * LINE_H / 2
    spans = "".join(f'<tspan x="{x:.1f}" y="{top + i * LINE_H:.1f}">{esc(t)}</tspan>' for i, t in enumerate(lines))
    return (f'<text font-family="{FONT}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}" dominant-baseline="middle">{spans}</text>')


def document(width: float, height: float, body: list[str], title: str, desc: str) -> RenderedSvg:
    w, h = int(math.ceil(width)), int(math.ceil(height))
    defs = (f'<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" '
            f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{LINE}"/></marker></defs>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
           f'role="img"><title>{esc(title)}</title><desc>{esc(desc)}</desc>{defs}'
           f'<rect width="100%" height="100%" fill="#ffffff"/>{"".join(body)}</svg>')
    return RenderedSvg(svg, w, h)


# ---------------------------------------------------------------------------
# Layered layout for flowcharts and concept maps
# ---------------------------------------------------------------------------
@dataclass
class Box:
    id: str
    lines: list[str]
    shape: str
    w: float
    h: float
    x: float = 0.0  # centre
    y: float = 0.0


def node_box(n: NodeD) -> Box:
    lines = wrap(n.label, 22)
    w = max(84.0, max(len(t) for t in lines) * CHAR_W + 28)
    h = len(lines) * LINE_H + 20
    if n.shape == "decision":
        w, h = w * 1.45, max(h * 1.6, 64)
    return Box(n.id, lines, n.shape, w, h)


def back_edges(ids: list[str], edges: list[EdgeD]) -> set[tuple[str, str]]:
    """Edges that close a cycle (e.g. a loop going back to its condition), found by DFS in node order."""
    adj: dict[str, list[str]] = {i: [] for i in ids}
    for e in edges:
        adj[e.source].append(e.target)
    color = dict.fromkeys(ids, 0)
    back: set[tuple[str, str]] = set()

    def visit(n: str) -> None:
        color[n] = 1
        for m in adj[n]:
            if color[m] == 1:
                back.add((n, m))
            elif color[m] == 0:
                visit(m)
        color[n] = 2

    for i in ids:
        if color[i] == 0:
            visit(i)
    return back


def layers(ids: list[str], edges: list[tuple[str, str]]) -> list[list[str]]:
    """Longest-path layering of a DAG, then one barycentre pass to reduce crossings."""
    preds: dict[str, list[str]] = {i: [] for i in ids}
    for a, b in edges:
        preds[b].append(a)
    layer: dict[str, int] = {}

    def depth(n: str) -> int:
        if n not in layer:
            layer[n] = 1 + max((depth(p) for p in preds[n]), default=-1)
        return layer[n]

    for i in ids:
        depth(i)
    rows: list[list[str]] = [[] for _ in range(max(layer.values(), default=-1) + 1)]
    for i in ids:
        rows[layer[i]].append(i)
    for r in range(1, len(rows)):
        pos = {n: k for k, n in enumerate(rows[r - 1])}
        rows[r].sort(key=lambda n: sum(pos.get(p, 0) for p in preds[n]) / max(1, len(preds[n])))
    return rows


def render_flow(d: VisualDraft) -> RenderedSvg:
    boxes = {n.id: node_box(n) for n in d.nodes}
    ids = [n.id for n in d.nodes]
    back = back_edges(ids, d.edges)
    forward = [(e.source, e.target) for e in d.edges if (e.source, e.target) not in back]
    rows = layers(ids, forward)
    gap_x, gap_y = 36, 60
    row_w = [sum(boxes[i].w for i in r) + gap_x * (len(r) - 1) for r in rows]
    content_w = max(row_w, default=0)
    y = MARGIN
    for r, wid in zip(rows, row_w, strict=True):
        rh = max(boxes[i].h for i in r)
        x = MARGIN + (content_w - wid) / 2
        for i in r:
            b = boxes[i]
            b.x, b.y = x + b.w / 2, y + rh / 2
            x += b.w + gap_x
        y += rh + gap_y
    lane = MARGIN + content_w + 24
    body: list[str] = []

    def label_at(x: float, y: float, s: str) -> None:
        if s:
            lines = wrap(s, 18)
            w = max(len(t) for t in lines) * 6.4 + 10
            body.append(f'<rect x="{x - w / 2:.1f}" y="{y - len(lines) * 8 - 2:.1f}" width="{w:.1f}" '
                        f'height="{len(lines) * 16 + 4}" fill="#ffffff"/>')
            body.append(text(x, y, lines, size=11, fill=LINE))

    for k, e in enumerate(d.edges):
        a, b = boxes[e.source], boxes[e.target]
        if (e.source, e.target) in back:
            lx = lane + 14 * k
            body.append(f'<path d="M{a.x + a.w / 2:.1f},{a.y:.1f} H{lx:.1f} V{b.y:.1f} H{b.x + b.w / 2:.1f}" '
                        f'fill="none" stroke="{LINE}" stroke-width="1.5" marker-end="url(#arrow)"/>')
            label_at(lx, (a.y + b.y) / 2, e.label)
        else:
            x1, y1, x2, y2 = a.x, a.y + a.h / 2, b.x, b.y - b.h / 2
            body.append(f'<path d="M{x1:.1f},{y1:.1f} C{x1:.1f},{(y1 + y2) / 2:.1f} {x2:.1f},{(y1 + y2) / 2:.1f} '
                        f'{x2:.1f},{y2:.1f}" fill="none" stroke="{LINE}" stroke-width="1.5" '
                        f'marker-end="url(#arrow)"/>')
            label_at((x1 + x2) / 2, (y1 + y2) / 2, e.label)
    for b in boxes.values():
        fill, l, t = FILL.get(b.shape, FILL["process"]), b.x - b.w / 2, b.y - b.h / 2
        if b.shape == "decision":
            body.append(f'<polygon points="{b.x:.1f},{t:.1f} {l + b.w:.1f},{b.y:.1f} {b.x:.1f},{t + b.h:.1f} '
                        f'{l:.1f},{b.y:.1f}" fill="{fill}" stroke="{STROKE}" stroke-width="1.5"/>')
        elif b.shape == "io":
            s = 12
            body.append(f'<polygon points="{l + s:.1f},{t:.1f} {l + b.w:.1f},{t:.1f} {l + b.w - s:.1f},{t + b.h:.1f} '
                        f'{l:.1f},{t + b.h:.1f}" fill="{fill}" stroke="{STROKE}" stroke-width="1.5"/>')
        else:
            rx = b.h / 2 if b.shape in ("start", "end") else 6
            body.append(f'<rect x="{l:.1f}" y="{t:.1f}" width="{b.w:.1f}" height="{b.h:.1f}" rx="{rx:.1f}" '
                        f'fill="{fill}" stroke="{STROKE}" stroke-width="1.5"/>')
        body.append(text(b.x, b.y, b.lines))
    width = lane + (14 * len(d.edges) if back else 0) + MARGIN
    return document(width, y - gap_y + MARGIN, body, d.title, d.alt_text)


# ---------------------------------------------------------------------------
# Mind map (horizontal tree)
# ---------------------------------------------------------------------------
def render_mindmap(d: VisualDraft) -> RenderedSvg:
    children: dict[str, list[str]] = {n.id: [] for n in d.nodes}
    for e in d.edges:
        children[e.source].append(e.target)
    labels = {n.id: n.label for n in d.nodes}
    depth_of: dict[str, int] = {}
    y_of: dict[str, float] = {}
    slot = [0]

    def place(n: str, depth: int) -> float:
        depth_of[n] = depth
        kids = children[n]
        if not kids:
            y_of[n] = MARGIN + 30 + slot[0] * 52
            slot[0] += 1
        else:
            ys = [place(k, depth + 1) for k in kids]
            y_of[n] = sum(ys) / len(ys)
        return y_of[n]

    place(d.root, 0)
    col_w: dict[int, float] = {}
    lines_of = {n: wrap(labels[n], 20) for n in depth_of}
    for n, dep in depth_of.items():
        col_w[dep] = max(col_w.get(dep, 0), max(len(t) for t in lines_of[n]) * CHAR_W + 28)
    col_x, x = {}, MARGIN
    for dep in sorted(col_w):
        col_x[dep] = x
        x += col_w[dep] + 56
    body: list[str] = []
    for n, kids in children.items():
        if n not in depth_of:
            continue
        for k in kids:
            x1, y1 = col_x[depth_of[n]] + col_w[depth_of[n]], y_of[n]
            x2, y2 = col_x[depth_of[k]], y_of[k]
            body.append(f'<path d="M{x1:.1f},{y1:.1f} C{x1 + 28:.1f},{y1:.1f} {x2 - 28:.1f},{y2:.1f} {x2:.1f},{y2:.1f}" '
                        f'fill="none" stroke="{PALETTE[depth_of[k] % len(PALETTE)]}" stroke-width="2"/>')
    for n, dep in depth_of.items():
        lines, w = lines_of[n], col_w[dep]
        h = len(lines) * LINE_H + 16
        fill = "#0072B2" if dep == 0 else "#f5f7fa"
        ink = "#ffffff" if dep == 0 else INK
        body.append(f'<rect x="{col_x[dep]:.1f}" y="{y_of[n] - h / 2:.1f}" width="{w:.1f}" height="{h:.1f}" rx="10" '
                    f'fill="{fill}" stroke="{STROKE}" stroke-width="1.2"/>')
        body.append(text(col_x[dep] + w / 2, y_of[n], lines, weight="bold" if dep == 0 else "normal", fill=ink))
    height = MARGIN * 2 + 30 + max(slot[0] - 1, 0) * 52 + 30
    return document(x - 56 + MARGIN, height, body, d.title, d.alt_text)


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------
def render_timeline(d: VisualDraft) -> RenderedSvg:
    n = len(d.events)
    step = 150
    width = MARGIN * 2 + max(1, n - 1) * step + 140
    axis_y = 150
    body = [f'<line x1="{MARGIN}" y1="{axis_y}" x2="{width - MARGIN}" y2="{axis_y}" stroke="{LINE}" '
            f'stroke-width="2" marker-end="url(#arrow)"/>']
    for i, ev in enumerate(d.events):
        x = MARGIN + 70 + i * step
        up = i % 2 == 0
        body.append(f'<circle cx="{x}" cy="{axis_y}" r="6" fill="{PALETTE[0]}"/>')
        body.append(f'<line x1="{x}" y1="{axis_y}" x2="{x}" y2="{axis_y + (-36 if up else 36)}" stroke="{MUTED}"/>')
        label = wrap(ev.label, 20)
        if up:
            body.append(text(x, axis_y - 50 - (len(label) - 1) * LINE_H / 2 - 18, [ev.date], weight="bold"))
            body.append(text(x, axis_y - 50 - (len(label) - 1) * LINE_H / 2, label, size=12))
        else:
            body.append(text(x, axis_y + 50, [ev.date], weight="bold"))
            body.append(text(x, axis_y + 68 + (len(label) - 1) * LINE_H / 2, label, size=12))
    return document(width, 300, body, d.title, d.alt_text)


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
def nice_step(span: float, ticks: int = 5) -> float:
    if span <= 0:
        return 1.0
    raw = span / ticks
    mag = 10 ** math.floor(math.log10(raw))
    return next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)


def _fmt(v: float) -> str:
    return f"{v:g}" if abs(v) < 1e6 else f"{v:.3g}"


def render_chart(d: VisualDraft, note: str = "") -> RenderedSvg:
    if d.chart_type == "pie":
        return _pie(d, note)
    pw, ph, left, top = 520, 300, 70, 30 + (24 if len(d.series) > 1 else 0)
    values = [v for s in d.series for v in s.values]
    lo, hi = min(0.0, min(values)), max(0.0, max(values))
    step = nice_step(hi - lo)
    lo, hi = math.floor(lo / step) * step, math.ceil(hi / step) * step or step
    def y(v: float) -> float:
        return top + ph - (v - lo) / (hi - lo) * ph

    body: list[str] = []
    t = lo
    while t <= hi + step / 2:
        body.append(f'<line x1="{left}" y1="{y(t):.1f}" x2="{left + pw}" y2="{y(t):.1f}" stroke="#e4e7eb"/>')
        body.append(text(left - 8, y(t), [_fmt(t)], size=11, anchor="end", fill=LINE))
        t += step
    body.append(f'<line x1="{left}" y1="{y(0):.1f}" x2="{left + pw}" y2="{y(0):.1f}" stroke="{LINE}" stroke-width="1.5"/>')
    n = len(d.categories)
    group = pw / n
    for ci, cat in enumerate(d.categories):
        cx = left + group * ci + group / 2
        body.append(text(cx, top + ph + 22, wrap(cat, 14), size=11, fill=INK))
    if d.chart_type == "line":
        for si, s in enumerate(d.series):
            pts = [(left + group * i + group / 2, y(v)) for i, v in enumerate(s.values)]
            body.append(f'<polyline points="{" ".join(f"{px:.1f},{py:.1f}" for px, py in pts)}" fill="none" '
                        f'stroke="{PALETTE[si % 8]}" stroke-width="2.5"/>')
            body += [f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="{PALETTE[si % 8]}"/>' for px, py in pts]
    else:
        bw = group * 0.75 / len(d.series)
        for si, s in enumerate(d.series):
            for i, v in enumerate(s.values):
                x = left + group * i + group * 0.125 + bw * si
                y0, y1 = sorted((y(0), y(v)))
                body.append(f'<rect x="{x:.1f}" y="{y0:.1f}" width="{bw:.1f}" height="{y1 - y0:.1f}" '
                            f'fill="{PALETTE[si % 8]}"/>')
    if d.y_label:
        body.append(f'<text font-family="{FONT}" font-size="12" fill="{LINE}" text-anchor="middle" '
                    f'transform="translate(16,{top + ph / 2:.1f}) rotate(-90)">{esc(d.y_label)}</text>')
    bottom = top + ph + 50
    if d.x_label:
        body.append(text(left + pw / 2, bottom, [d.x_label], size=12, fill=LINE))
        bottom += 20
    if len(d.series) > 1:
        x = left
        for si, s in enumerate(d.series):
            body.append(f'<rect x="{x}" y="12" width="12" height="12" fill="{PALETTE[si % 8]}"/>')
            body.append(text(x + 18, 18, [s.name], size=12, anchor="start"))
            x += 30 + len(s.name) * CHAR_W
    if note:
        body.append(text(left + pw, bottom, [note], size=11, anchor="end", fill=MUTED))
        bottom += 18
    return document(left + pw + MARGIN, bottom + MARGIN / 2, body, d.title, d.alt_text)


def _pie(d: VisualDraft, note: str) -> RenderedSvg:
    vals = d.series[0].values
    total = sum(vals)
    cx, cy, r = 170, 170, 140
    body: list[str] = []
    a0 = -math.pi / 2
    for i, v in enumerate(vals):
        a1 = a0 + 2 * math.pi * v / total
        large = 1 if a1 - a0 > math.pi else 0
        x0, y0, x1, y1 = cx + r * math.cos(a0), cy + r * math.sin(a0), cx + r * math.cos(a1), cy + r * math.sin(a1)
        if len(vals) == 1:
            body.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{PALETTE[0]}"/>')
        else:
            body.append(f'<path d="M{cx},{cy} L{x0:.1f},{y0:.1f} A{r},{r} 0 {large},1 {x1:.1f},{y1:.1f} z" '
                        f'fill="{PALETTE[i % 8]}" stroke="#ffffff" stroke-width="2"/>')
        a0 = a1
    for i, (cat, v) in enumerate(zip(d.categories, vals, strict=True)):
        y = 50 + i * 26
        body.append(f'<rect x="340" y="{y - 7}" width="14" height="14" fill="{PALETTE[i % 8]}"/>')
        body.append(text(362, y, [f"{cat} — {v / total:.0%}"], size=12, anchor="start"))
    h = max(340, 50 + len(vals) * 26) + (24 if note else 0)
    if note:
        body.append(text(MARGIN, h - 14, [note], size=11, anchor="start", fill=MUTED))
    width = 362 + max(len(f"{c} — 100%") for c in d.categories) * CHAR_W + MARGIN
    return document(width, h, body, d.title, d.alt_text)


# ---------------------------------------------------------------------------
# Comparison table and memory diagram
# ---------------------------------------------------------------------------
def render_comparison(d: VisualDraft) -> RenderedSvg:
    cols = ["", *d.columns]
    grid = [cols, *[[c, *row] for c, row in zip(d.criteria, d.cells, strict=True)]]
    wrapped = [[wrap(cell, 24) for cell in row] for row in grid]
    col_w = [max(max(len(t) for t in wrapped[r][c]) * CHAR_W + 20 for r in range(len(grid))) for c in range(len(cols))]
    row_h = [max(len(cell) for cell in row) * LINE_H + 16 for row in wrapped]
    body: list[str] = []
    y = MARGIN
    for r, row in enumerate(wrapped):
        x = MARGIN
        for c, cell in enumerate(row):
            head = r == 0 or c == 0
            fill = "#e3f2fd" if r == 0 else "#f5f7fa" if c == 0 else "#ffffff"
            body.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{col_w[c]:.1f}" height="{row_h[r]}" fill="{fill}" '
                        f'stroke="{STROKE}" stroke-width="1"/>')
            body.append(text(x + col_w[c] / 2, y + row_h[r] / 2, cell, weight="bold" if head else "normal"))
            x += col_w[c]
        y += row_h[r]
    return document(MARGIN * 2 + sum(col_w), y + MARGIN, body, d.title, d.alt_text)


def render_memory(d: VisualDraft) -> RenderedSvg:
    per_row, bw, bh, gap = 4, 150, 54, 30
    body: list[str] = []
    for i, v in enumerate(d.variables):
        r, c = divmod(i, per_row)
        x, y = MARGIN + c * (bw + gap), MARGIN + 22 + r * (bh + 64)
        body.append(text(x + bw / 2, y - 12, [v.name], weight="bold"))
        body.append(f'<rect x="{x}" y="{y}" width="{bw}" height="{bh}" rx="6" fill="{FILL["process"]}" '
                    f'stroke="{STROKE}" stroke-width="1.5"/>')
        body.append(text(x + bw / 2, y + bh / 2, wrap(v.value, 18)[:2]))
        if v.type:
            body.append(text(x + bw / 2, y + bh + 14, [v.type], size=11, fill=MUTED))
    rows = math.ceil(len(d.variables) / per_row)
    width = MARGIN * 2 + min(len(d.variables), per_row) * (bw + gap) - gap
    return document(width, MARGIN * 2 + rows * (bh + 64), body, d.title, d.alt_text)


def render_svg(d: VisualDraft, kind: str, note: str = "") -> RenderedSvg:
    return {
        "flow": render_flow, "mindmap": render_mindmap, "timeline": render_timeline,
        "comparison": render_comparison, "memory": render_memory,
    }[kind](d) if kind != "chart" else render_chart(d, note)


# ---------------------------------------------------------------------------
# Map / floor plan (IELTS Listening plan labelling)
# ---------------------------------------------------------------------------
def render_plan(items: list[tuple[str, int, int, int, int]], title: str, desc: str, cell: int = 48) -> RenderedSvg:
    """Boxes on a 12×12 grid. Single capital letters are answer locations (highlighted, letter only);
    other labels are landmarks drawn with their name."""
    body = [f'<rect x="{MARGIN}" y="{MARGIN}" width="{12 * cell}" height="{12 * cell}" fill="#fafafa" '
            f'stroke="{STROKE}" stroke-width="2"/>']
    for label, x, y, w, h in items:
        px, py, pw, ph = MARGIN + x * cell, MARGIN + y * cell, w * cell, h * cell
        letter = len(label) == 1 and label.isupper()
        fill = "#fff8e1" if letter else "#e3f2fd"
        body.append(f'<rect x="{px + 3}" y="{py + 3}" width="{pw - 6}" height="{ph - 6}" rx="4" fill="{fill}" '
                    f'stroke="{STROKE}" stroke-width="1.2"/>')
        if letter:
            body.append(f'<circle cx="{px + pw / 2:.1f}" cy="{py + ph / 2:.1f}" r="15" fill="#ffffff" '
                        f'stroke="{INK}" stroke-width="1.5"/>')
            body.append(text(px + pw / 2, py + ph / 2, [label], size=16, weight="bold"))
        else:
            body.append(text(px + pw / 2, py + ph / 2, wrap(label, max(6, int(pw / CHAR_W) - 2)), size=12))
    return document(MARGIN * 2 + 12 * cell, MARGIN * 2 + 12 * cell, body, title, desc)
