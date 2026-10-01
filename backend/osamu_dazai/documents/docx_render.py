"""Student book, teacher guide and assessments → DOCX via the DocumentTemplateEngine."""

from __future__ import annotations

from osamu_dazai.documents.docx_engine import DocumentTemplateEngine
from osamu_dazai.documents.figures import Figure
from osamu_dazai.documents.markdown import ASSESS_LABELS, LABELS, TEACHER_LABELS
from osamu_dazai.documents.template import EXAM, TEACHER_GUIDE, TEXTBOOK, DocTemplate
from osamu_dazai.domain.common import Lang
from osamu_dazai.domain.content import Chapter, StudentBook
from osamu_dazai.domain.curriculum import Course
from osamu_dazai.domain.questions import Assessment, QuestionGroup
from osamu_dazai.domain.teacher import TeacherGuide

TOC = {Lang.EN: "Contents", Lang.UZ: "Mundarija", Lang.UZ_CYRL: "Мундарижа", Lang.RU: "Содержание"}


def _labels(table: dict, lang: Lang) -> dict[str, str]:
    return table.get(lang, table[Lang.EN])


def _exercises(e: DocumentTemplateEngine, group: QuestionGroup) -> None:
    for q in group.questions:
        e.paragraph(f"**{q.number}.** {q.stem}")
        for o in q.options:
            e.paragraph(f"{o.label}) {o.text}", indent_cm=0.8)


def _chapter(e: DocumentTemplateEngine, ch: Chapter, L: dict[str, str], figures: dict[str, Figure]) -> None:
    groups = {g.id: g for g in ch.exercises}
    e.heading(f"{L['chapter']} {ch.number}. {ch.title}", 1)
    n_fig = 0
    for s in ch.sections:
        e.heading(s.title, 2)
        for b in s.blocks:
            k = b.kind
            if k == "heading":
                e.heading(b.text, min(4, b.level + 2))
            elif k == "paragraph":
                e.paragraph(b.text)
            elif k == "list":
                e.bullets(b.items, ordered=b.ordered)
            elif k == "code":
                e.code(b.code, output=b.expected_output)
            elif k == "callout":
                e.callout(b.style, b.title, b.text)
            elif k == "table":
                e.table(b.header, b.rows, caption=b.caption)
            elif k == "equation":
                e.paragraph(f"`{b.latex}`")
            elif k == "visual_ref":
                n_fig += 1
                spec = ch.visual_specs.get(b.visual_id)
                cap = f"{L['figure']} {ch.number}.{n_fig}: {b.caption or (spec.purpose if spec else '')}"
                if b.visual_id in figures:
                    e.figure(figures[b.visual_id], cap)
                else:
                    e.figure_placeholder(cap)
            elif k == "question_ref" and b.question_group_id in groups:
                _exercises(e, groups[b.question_group_id])


def student_book_docx(book: StudentBook, *, figures: dict[str, Figure] | None = None,
                      template: DocTemplate = TEXTBOOK, answer_key: bool = True) -> bytes:
    L = _labels(LABELS, book.lang)
    e = DocumentTemplateEngine(template, title=book.title, lang=book.lang.value)
    e.title_block(book.title)
    e.page_break()
    e.toc(TOC.get(book.lang, "Contents"))
    for i, ch in enumerate(book.chapters):
        if i and template.chapter_page_breaks:
            e.page_break()
        _chapter(e, ch, L, figures or {})
    if book.glossary:
        e.page_break()
        e.heading(L["glossary"], 1)
        e.table(["", ""], [[f"**{g.term}**", g.definition] for g in book.glossary], widths_cm=[4.5, 11.5])
    if answer_key:
        e.page_break()
        e.heading(L["answers"], 1)
        for ch in book.chapters:
            rows = [(q.number, q.answer.accepted[0]) for g in ch.exercises for q in g.questions if q.answer]
            if rows:
                e.heading(f"{L['chapter']} {ch.number}", 2)
                e.bullets([f"{n}. {a}" for n, a in rows])
    return e.to_bytes()


def teacher_guide_docx(guide: TeacherGuide, course: Course, book: StudentBook, *,
                       template: DocTemplate = TEACHER_GUIDE) -> bytes:
    L, BL = _labels(TEACHER_LABELS, guide.lang), _labels(LABELS, guide.lang)
    e = DocumentTemplateEngine(template, title=guide.title, lang=guide.lang.value)
    e.title_block(guide.title, {Lang.UZ: "O‘qituvchi uchun qo‘llanma", Lang.RU: "Книга для учителя"}.get(
        guide.lang, "Teacher's guide"))
    e.page_break()
    e.toc(TOC.get(guide.lang, "Contents"))
    objectives = course.all_objectives()
    lessons = {les.id: les for les in course.all_lessons()}
    chapters = {ch.id: ch for ch in book.chapters}
    current = None

    def answer_key(ch: Chapter) -> None:
        rows = [[str(q.number), q.stem, " | ".join(q.answer.accepted)] for g in ch.exercises for q in g.questions
                if q.answer]
        if rows:
            e.heading(f"{L['answers']} {ch.number}", 2)
            e.table(["#", "", L["key"]], rows, widths_cm=[1.2, 9.5, 5.5])

    for tl in guide.lessons:
        if tl.chapter_id != current:
            if current in chapters:
                answer_key(chapters[current])
                e.page_break()
            current = tl.chapter_id
            if (ch := chapters.get(current)) is not None:
                e.heading(f"{BL['chapter']} {ch.number}. {ch.title}", 1)
        les = lessons.get(tl.lesson_id)
        e.heading(f"{L['lesson']} {les.number}. {les.title} ({les.minutes} {L['min']})" if les else L["lesson"], 2)

        def section(title: str, items: list[str]) -> None:
            if items:
                e.paragraph(title, bold=True)
                e.bullets(items)

        section(L["objectives"], [objectives[o].text for o in tl.objectives if o in objectives])
        section(L["prep"], tl.preparation)
        section(L["resources"], tl.resources)
        if tl.sequence:
            e.table([L["min"], L["activity"], L["teacher"], L["students"]],
                    [[str(s.minutes), s.activity, s.teacher_actions, s.student_actions] for s in tl.sequence],
                    caption=L["plan"], widths_cm=[1.4, 4.2, 5.3, 5.3])
        section(L["points"], tl.explanation_points)
        section(L["demo"], tl.demonstrations)
        section(L["activities"], tl.activities)
        if tl.questions:
            e.paragraph(L["questions"], bold=True)
            for i, q in enumerate(tl.questions, start=1):
                e.paragraph(f"{i}. {q.question}")
                e.paragraph(f"*{L['expected']}:* {q.expected_answer}", indent_cm=0.8)
        if tl.misconceptions:
            e.paragraph(L["misconceptions"], bold=True)
            e.bullets([f"**{m.misconception}** — {L['why']}: {m.why_it_happens} {L['address']}: {m.how_to_address}"
                       for m in tl.misconceptions])
        section(L["support"], tl.differentiation.support)
        section(L["extension"], tl.differentiation.extension)
        section(L["assessment"], tl.assessment)
        if tl.homework:
            e.paragraph(f"**{L['homework']}:** {tl.homework}")
            e.paragraph(f"*{L['key']}:* {tl.homework_key}", indent_cm=0.8)
        section(L["more"], tl.extension_activities)
    if current in chapters:
        answer_key(chapters[current])
    return e.to_bytes()


def assessment_docx(a: Assessment, lang: Lang, *, answer_key: bool = False, template: DocTemplate = EXAM) -> bytes:
    L = _labels(ASSESS_LABELS, lang)
    title = a.title + (f" — {L['version']} {a.version_label}" if a.version_label else "")
    e = DocumentTemplateEngine(template, title=title, lang=lang.value)
    e.title_block(f"{L['key']}: {title}" if answer_key else title)
    if not answer_key:
        e.paragraph(f"{L['name']}: ______________________________      {L['date']}: ______________")
        if a.duration_minutes:
            e.paragraph(f"{a.duration_minutes} {L['minutes']}", italic=True)
        if a.instructions:
            e.paragraph(a.instructions)
    for g in a.groups:
        e.heading(L.get(g.title, g.title), 2)
        for q in g.questions:
            if answer_key:
                if not q.answer:
                    continue
                first, *alts = q.answer.accepted
                shown = L.get(first.upper(), first) if q.type.value == "true_false" else first
                if q.type.value == "code":
                    e.paragraph(f"**{q.number}.**")
                    e.code(first)
                else:
                    e.paragraph(f"**{q.number}.** {shown}" + (f" ({L['also']}: {' | '.join(alts)})" if alts else ""))
                if q.answer.explanation:
                    e.paragraph(q.answer.explanation, italic=True, indent_cm=0.8)
                continue
            pts = f" ({q.points:g} {L['points']})" if q.points != 1 else ""
            e.paragraph(f"**{q.number}.** {q.stem}{pts}")
            for o in q.options:
                e.paragraph(f"{o.label}) {o.text}", indent_cm=0.8)
            if q.type.value == "true_false":
                e.paragraph(f"☐ {L['TRUE']}      ☐ {L['FALSE']}", indent_cm=0.8)
            if q.type.value in ("short_answer", "completion"):
                e.paragraph("_" * 60, indent_cm=0.8)
            if q.type.value in ("code", "essay"):
                for _ in range(6 if q.type.value == "code" else 12):
                    e.paragraph("_" * 70)
    for r in a.rubrics:
        e.heading(f"{L['rubric']}: {r.title}", 2)
        levels = sorted({lv.score for c in r.criteria for lv in c.levels}, reverse=True)
        rows = []
        for c in r.criteria:
            by = {lv.score: lv.descriptor for lv in c.levels}
            rows.append([f"{c.name} (×{c.weight:g})", *(by.get(s, "—") for s in levels)])
        e.table([L["criterion"], *(f"{s:g}" for s in levels)], rows)
    return e.to_bytes()
