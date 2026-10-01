"""Self-contained HTML for the student book, teacher guide and assessments.

One file per document: CSS inline, SVG figures inline (raster images as data
URIs), print styles so the same file prints cleanly to PDF. All content text
is HTML-escaped; only Osamu Dazai's own generated SVG is embedded verbatim.
"""

from __future__ import annotations

import base64
import re
from html import escape

from osamu_dazai.documents.figures import Figure
from osamu_dazai.documents.inline import to_html
from osamu_dazai.documents.markdown import ASSESS_LABELS, LABELS, TEACHER_LABELS
from osamu_dazai.domain.common import Lang
from osamu_dazai.domain.content import Chapter, StudentBook
from osamu_dazai.domain.curriculum import Course
from osamu_dazai.domain.questions import Assessment
from osamu_dazai.domain.teacher import TeacherGuide

CSS = """
:root { --ink:#1f2933; --muted:#616e7c; --accent:#1f3a5f; --line:#cbd2d9; --code:#f3f4f6; }
* { box-sizing: border-box; }
body { margin:0; background:#fff; color:var(--ink); font:16px/1.6 "Noto Sans","Segoe UI",Arial,sans-serif; }
main { max-width: 820px; margin: 0 auto; padding: 32px 20px 64px; }
h1,h2,h3,h4 { color: var(--accent); line-height: 1.25; }
h1.title { text-align:center; font-size: 2.1em; margin: 1.5em 0 .3em; }
p.subtitle { text-align:center; color: var(--muted); }
nav.toc ol { padding-left: 1.2em; } nav.toc a { color: var(--accent); text-decoration: none; }
pre { background: var(--code); padding: 12px 14px; border-radius: 6px; overflow-x: auto; font-size: .9em; }
pre.output { background: #fff; border: 1px dashed var(--line); }
code { font-family: Consolas, "Courier New", monospace; }
.callout { border-left: 5px solid var(--accent); background: #f5f8fc; padding: 10px 14px; margin: 1em 0;
  border-radius: 4px; }
.callout.common_mistake { border-color:#c0392b; background:#fdecec; } .callout.tip { border-color:#2f9e6e;
  background:#eaf7ee; } .callout.warning { border-color:#e69f00; background:#fff4e0; }
table { border-collapse: collapse; width: 100%; margin: 1em 0; font-size: .95em; }
th, td { border: 1px solid var(--line); padding: 6px 8px; text-align: left; vertical-align: top; }
th { background: #e3f2fd; }
figure { margin: 1.2em 0; text-align: center; } figure svg, figure img { max-width: 100%; height: auto; }
figcaption { color: var(--muted); font-style: italic; font-size: .9em; }
ol.exercises li { margin: .4em 0; } ol.options { list-style: upper-alpha; }
.answer-line { border-bottom: 1px solid var(--ink); height: 1.6em; }
.muted { color: var(--muted); }
@media print {
  body { font-size: 11pt; } main { max-width: none; padding: 0; }
  section.chapter, section.lesson-chapter { break-before: page; }
  figure, table, pre, .callout { break-inside: avoid; }
  nav.toc a::after { content: ""; }
}
"""


def _page(title: str, lang: str, body: str) -> str:
    return (f'<!doctype html><html lang="{escape(lang)}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{escape(title)}</title><style>{CSS}</style></head><body><main>{body}</main></body></html>")


def _p(text: str) -> str:
    return f"<p>{to_html(text)}</p>"


def _figure_html(fig: Figure | None, caption: str) -> str:
    if fig is None:
        return f'<p class="muted">[{escape(caption)}]</p>'
    if fig.is_svg:
        svg = re.sub(r"^<\?xml[^>]*>", "", fig.svg_text()).strip()
        inner = svg
    else:
        mime = "image/png" if fig.path.suffix.lower() == ".png" else "image/jpeg"
        data = base64.b64encode(fig.path.read_bytes()).decode()
        inner = f'<img alt="{escape(caption)}" src="data:{mime};base64,{data}">'
    return f"<figure>{inner}<figcaption>{escape(caption)}</figcaption></figure>"


def _chapter_html(ch: Chapter, L: dict[str, str], figures: dict[str, Figure]) -> str:
    groups = {g.id: g for g in ch.exercises}
    out = [f'<section class="chapter" id="ch{ch.number}"><h2>{escape(L["chapter"])} {ch.number}. '
           f"{escape(ch.title)}</h2>"]
    n_fig = 0
    for s in ch.sections:
        out.append(f"<h3>{escape(s.title)}</h3>")
        for b in s.blocks:
            k = b.kind
            if k == "heading":
                out.append(f"<h4>{escape(b.text)}</h4>")
            elif k == "paragraph":
                out.append(_p(b.text))
            elif k == "list":
                tag = "ol" if b.ordered else "ul"
                out.append(f"<{tag}>" + "".join(f"<li>{to_html(i)}</li>" for i in b.items) + f"</{tag}>")
            elif k == "code":
                out.append(f'<pre><code class="language-{escape(b.language)}">{escape(b.code)}</code></pre>')
                if b.expected_output:
                    out.append(f'<pre class="output"><code>{escape(b.expected_output)}</code></pre>')
            elif k == "callout":
                title = f"<strong>{escape(b.title)}</strong><br>" if b.title else ""
                out.append(f'<div class="callout {escape(b.style)}">{title}{to_html(b.text)}</div>')
            elif k == "table":
                cap = f"<caption>{escape(b.caption)}</caption>" if b.caption else ""
                head = "".join(f"<th>{to_html(h)}</th>" for h in b.header)
                rows = "".join("<tr>" + "".join(f"<td>{to_html(c)}</td>" for c in r) + "</tr>" for r in b.rows)
                out.append(f"<table>{cap}<thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>")
            elif k == "equation":
                out.append(f'<p class="equation"><code>{escape(b.latex)}</code></p>')
            elif k == "visual_ref":
                n_fig += 1
                spec = ch.visual_specs.get(b.visual_id)
                cap = f"{L['figure']} {ch.number}.{n_fig}: {b.caption or (spec.purpose if spec else '')}"
                out.append(_figure_html(figures.get(b.visual_id), cap))
            elif k == "question_ref" and b.question_group_id in groups:
                items = []
                for q in groups[b.question_group_id].questions:
                    opts = ("<ol class='options'>" + "".join(f"<li>{to_html(o.text)}</li>" for o in q.options)
                            + "</ol>") if q.options else ""
                    items.append(f'<li value="{q.number}">{to_html(q.stem)}{opts}</li>')
                out.append(f'<ol class="exercises">{"".join(items)}</ol>')
    out.append("</section>")
    return "".join(out)


def student_book_html(book: StudentBook, *, figures: dict[str, Figure] | None = None, answer_key: bool = True) -> str:
    L = LABELS.get(book.lang, LABELS[Lang.EN])
    toc = "".join(f'<li><a href="#ch{c.number}">{escape(L["chapter"])} {c.number}. {escape(c.title)}</a></li>'
                  for c in book.chapters)
    body = [f'<h1 class="title">{escape(book.title)}</h1>', f'<nav class="toc"><ol>{toc}</ol></nav>']
    body += [_chapter_html(c, L, figures or {}) for c in book.chapters]
    if book.glossary:
        rows = "".join(f"<tr><th>{escape(g.term)}</th><td>{to_html(g.definition)}</td></tr>" for g in book.glossary)
        body.append(f'<section class="chapter"><h2>{escape(L["glossary"])}</h2><table>{rows}</table></section>')
    if answer_key:
        parts = []
        for c in book.chapters:
            rows = "".join(f'<li value="{q.number}">{to_html(q.answer.accepted[0])}</li>' for g in c.exercises
                           for q in g.questions if q.answer)
            if rows:
                parts.append(f"<h3>{escape(L['chapter'])} {c.number}</h3><ol>{rows}</ol>")
        body.append(f'<section class="chapter"><h2>{escape(L["answers"])}</h2>{"".join(parts)}</section>')
    return _page(book.title, book.lang.value, "".join(body))


def teacher_guide_html(guide: TeacherGuide, course: Course, book: StudentBook) -> str:
    L, BL = TEACHER_LABELS.get(guide.lang, TEACHER_LABELS[Lang.EN]), LABELS.get(guide.lang, LABELS[Lang.EN])
    objectives = course.all_objectives()
    lessons = {les.id: les for les in course.all_lessons()}
    chapters = {ch.id: ch for ch in book.chapters}
    out = [f'<h1 class="title">{escape(guide.title)}</h1>']

    def ul(title: str, items: list[str]) -> str:
        return (f"<h4>{escape(title)}</h4><ul>" + "".join(f"<li>{to_html(i)}</li>" for i in items) + "</ul>"
                if items else "")

    def key(ch: Chapter) -> str:
        rows = "".join(f"<tr><td>{q.number}</td><td>{to_html(q.stem)}</td><td>{escape(' | '.join(q.answer.accepted))}"
                       f"</td></tr>" for g in ch.exercises for q in g.questions if q.answer)
        return f"<h3>{escape(L['answers'])} {ch.number}</h3><table>{rows}</table>" if rows else ""

    current = None
    for tl in guide.lessons:
        if tl.chapter_id != current:
            if current in chapters:
                out.append(key(chapters[current]) + "</section>")
            current = tl.chapter_id
            ch = chapters.get(current)
            out.append(f'<section class="lesson-chapter"><h2>{escape(BL["chapter"])} {ch.number}. '
                       f"{escape(ch.title)}</h2>" if ch else '<section class="lesson-chapter">')
        les = lessons.get(tl.lesson_id)
        out.append(f"<h3>{escape(L['lesson'])} {les.number}. {escape(les.title)} ({les.minutes} {escape(L['min'])})</h3>"
                   if les else f"<h3>{escape(L['lesson'])}</h3>")
        out.append(ul(L["objectives"], [objectives[o].text for o in tl.objectives if o in objectives]))
        out.append(ul(L["prep"], tl.preparation) + ul(L["resources"], tl.resources))
        if tl.sequence:
            rows = "".join(f"<tr><td>{s.minutes}</td><td>{to_html(s.activity)}</td><td>{to_html(s.teacher_actions)}</td>"
                           f"<td>{to_html(s.student_actions)}</td></tr>" for s in tl.sequence)
            out.append(f"<table><caption>{escape(L['plan'])}</caption><thead><tr><th>{escape(L['min'])}</th>"
                       f"<th>{escape(L['activity'])}</th><th>{escape(L['teacher'])}</th><th>{escape(L['students'])}"
                       f"</th></tr></thead><tbody>{rows}</tbody></table>")
        out.append(ul(L["points"], tl.explanation_points) + ul(L["demo"], tl.demonstrations)
                   + ul(L["activities"], tl.activities))
        if tl.questions:
            qs = "".join(f"<li>{to_html(q.question)}<br><em>{escape(L['expected'])}:</em> {to_html(q.expected_answer)}"
                         f"</li>" for q in tl.questions)
            out.append(f"<h4>{escape(L['questions'])}</h4><ol>{qs}</ol>")
        out.append(ul(L["misconceptions"], [f"**{m.misconception}** — {m.how_to_address}" for m in tl.misconceptions]))
        out.append(ul(L["support"], tl.differentiation.support) + ul(L["extension"], tl.differentiation.extension)
                   + ul(L["assessment"], tl.assessment))
        if tl.homework:
            out.append(f"<h4>{escape(L['homework'])}</h4>{_p(tl.homework)}<p><em>{escape(L['key'])}:</em> "
                       f"{to_html(tl.homework_key)}</p>")
    if current in chapters:
        out.append(key(chapters[current]) + "</section>")
    return _page(guide.title, guide.lang.value, "".join(out))


def assessment_html(a: Assessment, lang: Lang, *, answer_key: bool = False) -> str:
    L = ASSESS_LABELS.get(lang, ASSESS_LABELS[Lang.EN])
    title = a.title + (f" — {L['version']} {a.version_label}" if a.version_label else "")
    out = [f'<h1 class="title">{escape((L["key"] + ": ") if answer_key else "")}{escape(title)}</h1>']
    if not answer_key:
        out.append(f"<p>{escape(L['name'])}: ____________________ &nbsp; {escape(L['date'])}: ____________</p>")
        if a.instructions:
            out.append(_p(a.instructions))
    for g in a.groups:
        out.append(f"<h2>{escape(L.get(g.title, g.title))}</h2><ol class='exercises'>")
        for q in g.questions:
            if answer_key:
                if q.answer:
                    first = q.answer.accepted[0]
                    shown = L.get(first.upper(), first) if q.type.value == "true_false" else first
                    out.append(f'<li value="{q.number}"><strong>{escape(shown)}</strong>'
                               + (f"<br><span class='muted'>{to_html(q.answer.explanation)}</span>"
                                  if q.answer.explanation else "") + "</li>")
                continue
            opts = ("<ol class='options'>" + "".join(f"<li>{to_html(o.text)}</li>" for o in q.options) + "</ol>"
                    if q.options else "")
            tf = f"<p>☐ {escape(L['TRUE'])} &nbsp; ☐ {escape(L['FALSE'])}</p>" if q.type.value == "true_false" else ""
            line = '<div class="answer-line"></div>' if q.type.value in ("short_answer", "completion") else ""
            out.append(f'<li value="{q.number}">{to_html(q.stem)}{opts}{tf}{line}</li>')
        out.append("</ol>")
    return _page(title, lang.value, "".join(out))
