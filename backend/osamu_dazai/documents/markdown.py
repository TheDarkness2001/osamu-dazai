"""Markdown rendering of a StudentBook and its TeacherGuide (output formats, spec §36).

Answers never appear next to exercises; they go to an optional answer-key
appendix (student editions omit it).
"""

from __future__ import annotations

from osamu_dazai.domain.common import Lang
from osamu_dazai.domain.content import Chapter, StudentBook
from osamu_dazai.domain.curriculum import Course
from osamu_dazai.domain.questions import Assessment, QuestionGroup
from osamu_dazai.domain.teacher import TeacherGuide

LABELS = {
    Lang.EN: {"chapter": "Chapter", "glossary": "Glossary", "answers": "Answer key", "figure": "Figure",
              "exercises": "Exercises"},
    Lang.UZ: {"chapter": "Bob", "glossary": "Lug‘at", "answers": "Javoblar", "figure": "Rasm",
              "exercises": "Mashqlar"},
    Lang.UZ_CYRL: {"chapter": "Боб", "glossary": "Луғат", "answers": "Жавоблар", "figure": "Расм",
                   "exercises": "Машқлар"},
    Lang.RU: {"chapter": "Глава", "glossary": "Глоссарий", "answers": "Ответы", "figure": "Рисунок",
              "exercises": "Упражнения"},
}
CALLOUT_ICONS = {"note": "ℹ️", "tip": "💡", "warning": "⚠️", "common_mistake": "❌", "definition": "📘",
                 "example": "✏️"}


def _cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def _group(group: QuestionGroup) -> list[str]:
    out = []
    for q in group.questions:
        out.append(f"{q.number}. {q.stem}")
        out += [f"    {o.label}) {o.text}" for o in q.options]
    return [*out, ""]


def render_chapter(ch: Chapter, labels: dict[str, str], figures: dict[str, str] | None = None) -> list[str]:
    groups = {g.id: g for g in ch.exercises}
    out = [f"## {labels['chapter']} {ch.number}. {ch.title}", ""]
    n_fig = 0
    for s in ch.sections:
        out += [f"### {s.title}", ""]
        for b in s.blocks:
            k = b.kind
            if k == "heading":
                out += [f"{'#' * min(6, b.level + 3)} {b.text}", ""]
            elif k == "paragraph":
                out += [b.text, ""]
            elif k == "list":
                out += [f"{i}. {it}" if b.ordered else f"- {it}" for i, it in enumerate(b.items, start=1)] + [""]
            elif k == "code":
                out += [f"```{b.language}", b.code.rstrip(), "```", ""]
                if b.expected_output:
                    out += ["```text", b.expected_output.rstrip(), "```", ""]
            elif k == "callout":
                icon = CALLOUT_ICONS.get(b.style, "")
                head = f"> {icon} **{b.title}**" if b.title else f"> {icon}"
                out += [head, *(f"> {ln}" for ln in b.text.splitlines()), ""]
            elif k == "table":
                if b.caption:
                    out += [f"**{b.caption}**", ""]
                out += ["| " + " | ".join(map(_cell, b.header)) + " |",
                        "|" + "---|" * len(b.header),
                        *("| " + " | ".join(map(_cell, r)) + " |" for r in b.rows), ""]
            elif k == "equation":
                out += ["$$", b.latex, "$$", ""]
            elif k == "visual_ref":
                n_fig += 1
                spec = ch.visual_specs.get(b.visual_id)
                desc = spec.purpose if spec else ""
                caption = f"{labels['figure']} {ch.number}.{n_fig}: {b.caption or desc}"
                if figures and b.visual_id in figures:
                    out += [f"![{caption}]({figures[b.visual_id]})", "", f"*{caption}*", ""]
                else:
                    out += [f"*[{caption}]*", ""]
            elif k == "question_ref" and b.question_group_id in groups:
                out += _group(groups[b.question_group_id])
    return out


def render_student_book(book: StudentBook, *, answer_key: bool = True,
                        figures: dict[str, str] | None = None) -> str:
    """``figures`` maps visual ids to image paths (relative to where the Markdown is written)."""
    labels = LABELS.get(book.lang, LABELS[Lang.EN])
    out = [f"# {book.title}", ""]
    for ch in book.chapters:
        out += render_chapter(ch, labels, figures)
    if book.glossary:
        out += [f"## {labels['glossary']}", ""]
        out += [f"- **{e.term}** — {e.definition}" for e in book.glossary] + [""]
    if answer_key:
        out += [f"## {labels['answers']}", ""]
        for ch in book.chapters:
            answers = [(q.number, q.answer.accepted[0]) for g in ch.exercises for q in g.questions if q.answer]
            if answers:
                out += [f"### {labels['chapter']} {ch.number}", ""]
                out += [f"{n}. {a}" for n, a in answers] + [""]
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Teacher guide
# ---------------------------------------------------------------------------
TEACHER_LABELS = {
    Lang.EN: {"lesson": "Lesson", "objectives": "Objectives", "plan": "Lesson plan", "min": "min",
              "activity": "Activity", "teacher": "Teacher", "students": "Students", "prep": "Preparation",
              "resources": "Resources", "points": "Key explanation points", "demo": "Demonstrations",
              "activities": "Activities", "questions": "Questions to ask", "expected": "Expected answer",
              "misconceptions": "Common misconceptions", "why": "Why", "address": "How to address",
              "support": "Support", "extension": "Extension", "assessment": "Checking understanding",
              "homework": "Homework", "key": "Key", "more": "Extension activities",
              "answers": "Answer key — chapter"},
    Lang.UZ: {"lesson": "Dars", "objectives": "Maqsadlar", "plan": "Dars rejasi", "min": "daq",
              "activity": "Faoliyat", "teacher": "O‘qituvchi", "students": "O‘quvchilar", "prep": "Tayyorgarlik",
              "resources": "Resurslar", "points": "Asosiy tushuntirish nuqtalari", "demo": "Namoyishlar",
              "activities": "Mashg‘ulotlar", "questions": "Beriladigan savollar", "expected": "Kutilgan javob",
              "misconceptions": "Keng tarqalgan noto‘g‘ri tushunchalar", "why": "Sababi",
              "address": "Qanday bartaraf etish", "support": "Qo‘llab-quvvatlash", "extension": "Chuqurlashtirish",
              "assessment": "Tushunishni tekshirish", "homework": "Uy vazifasi", "key": "Javob",
              "more": "Qo‘shimcha mashg‘ulotlar", "answers": "Javoblar — bob"},
    Lang.RU: {"lesson": "Урок", "objectives": "Цели", "plan": "План урока", "min": "мин",
              "activity": "Деятельность", "teacher": "Учитель", "students": "Ученики", "prep": "Подготовка",
              "resources": "Ресурсы", "points": "Ключевые моменты объяснения", "demo": "Демонстрации",
              "activities": "Задания", "questions": "Вопросы классу", "expected": "Ожидаемый ответ",
              "misconceptions": "Типичные заблуждения", "why": "Почему", "address": "Как исправить",
              "support": "Поддержка", "extension": "Углубление", "assessment": "Проверка понимания",
              "homework": "Домашнее задание", "key": "Ответ", "more": "Дополнительные задания",
              "answers": "Ответы — глава"},
}


def render_teacher_guide(guide: TeacherGuide, course: Course, book: StudentBook) -> str:
    L = TEACHER_LABELS.get(guide.lang, TEACHER_LABELS[Lang.EN])
    objectives = course.all_objectives()
    lessons = {les.id: les for les in course.all_lessons()}
    chapters = {ch.id: ch for ch in book.chapters}
    out = [f"# {guide.title}", ""]

    def bullets(title: str, items: list[str]) -> None:
        if items:
            out.extend([f"**{title}**", "", *(f"- {i}" for i in items), ""])

    current_chapter = None
    for tl in guide.lessons:
        if tl.chapter_id != current_chapter:
            if current_chapter in chapters:
                out.extend(_chapter_answers(chapters[current_chapter], L))
            current_chapter = tl.chapter_id
            ch = chapters.get(tl.chapter_id)
            if ch:
                out += [f"## {LABELS.get(guide.lang, LABELS[Lang.EN])['chapter']} {ch.number}. {ch.title}", ""]
        les = lessons.get(tl.lesson_id)
        head = f"{L['lesson']} {les.number}. {les.title} ({les.minutes} {L['min']})" if les else L["lesson"]
        out += [f"### {head}", ""]
        bullets(L["objectives"], [objectives[o].text for o in tl.objectives if o in objectives])
        bullets(L["prep"], tl.preparation)
        bullets(L["resources"], tl.resources)
        if tl.sequence:
            out += [f"**{L['plan']}**", "",
                    f"| {L['min']} | {L['activity']} | {L['teacher']} | {L['students']} |", "|---|---|---|---|",
                    *(f"| {s.minutes} | {_cell(s.activity)} | {_cell(s.teacher_actions)} | {_cell(s.student_actions)} |"
                      for s in tl.sequence), ""]
        bullets(L["points"], tl.explanation_points)
        bullets(L["demo"], tl.demonstrations)
        bullets(L["activities"], tl.activities)
        if tl.questions:
            out += [f"**{L['questions']}**", ""]
            for i, q in enumerate(tl.questions, start=1):
                out.append(f"{i}. {q.question}  \n   *{L['expected']}:* {q.expected_answer}")
            out.append("")
        if tl.misconceptions:
            out += [f"**{L['misconceptions']}**", ""]
            out += [f"- **{m.misconception}** — {L['why']}: {m.why_it_happens} {L['address']}: {m.how_to_address}"
                    for m in tl.misconceptions] + [""]
        bullets(L["support"], tl.differentiation.support)
        bullets(L["extension"], tl.differentiation.extension)
        bullets(L["assessment"], tl.assessment)
        if tl.homework:
            out += [f"**{L['homework']}:** {tl.homework}", "", f"*{L['key']}:* {tl.homework_key}", ""]
        bullets(L["more"], tl.extension_activities)
    if current_chapter in chapters:
        out.extend(_chapter_answers(chapters[current_chapter], L))
    return "\n".join(out).rstrip() + "\n"


def _chapter_answers(ch: Chapter, L: dict[str, str]) -> list[str]:
    rows = [(q.number, q.stem, " | ".join(q.answer.accepted)) for g in ch.exercises for q in g.questions if q.answer]
    if not rows:
        return []
    return [f"### {L['answers']} {ch.number}", "", *(f"{n}. {stem} — **{a}**" for n, stem, a in rows), ""]


# ---------------------------------------------------------------------------
# Assessments
# ---------------------------------------------------------------------------
ASSESS_LABELS = {
    Lang.EN: {"name": "Name", "date": "Date", "version": "Version", "minutes": "minutes", "points": "points",
              "multiple_choice": "Multiple choice", "true_false": "True or false",
              "completion": "Complete the sentences", "short_answer": "Short answers", "code": "Programming tasks",
              "essay": "Extended task", "TRUE": "True", "FALSE": "False", "key": "Answer key",
              "rubric": "Marking rubric", "criterion": "Criterion", "also": "also accept"},
    Lang.UZ: {"name": "Ism", "date": "Sana", "version": "Variant", "minutes": "daqiqa", "points": "ball",
              "multiple_choice": "Test savollari", "true_false": "To‘g‘ri yoki noto‘g‘ri",
              "completion": "Gaplarni to‘ldiring", "short_answer": "Qisqa javoblar", "code": "Dasturlash topshiriqlari",
              "essay": "Kengaytirilgan topshiriq", "TRUE": "To‘g‘ri", "FALSE": "Noto‘g‘ri", "key": "Javoblar kaliti",
              "rubric": "Baholash mezonlari", "criterion": "Mezon", "also": "shuningdek qabul qilinadi"},
    Lang.RU: {"name": "Имя", "date": "Дата", "version": "Вариант", "minutes": "мин", "points": "балл",
              "multiple_choice": "Тест", "true_false": "Верно или неверно", "completion": "Заполните пропуски",
              "short_answer": "Краткие ответы", "code": "Задания по программированию",
              "essay": "Развёрнутое задание", "TRUE": "Верно", "FALSE": "Неверно", "key": "Ключ ответов",
              "rubric": "Критерии оценивания", "criterion": "Критерий", "also": "также принимается"},
}


def _alabels(lang: Lang) -> dict[str, str]:
    return ASSESS_LABELS.get(lang, ASSESS_LABELS[Lang.EN])


def render_assessment(a: Assessment, lang: Lang) -> str:
    L = _alabels(lang)
    head = f"# {a.title}" + (f" — {L['version']} {a.version_label}" if a.version_label else "")
    out = [head, "", f"{L['name']}: ____________________    {L['date']}: ____________", ""]
    if a.duration_minutes:
        out += [f"⏱ {a.duration_minutes} {L['minutes']}", ""]
    if a.instructions:
        out += [a.instructions, ""]
    for g in a.groups:
        out += [f"## {L.get(g.title, g.title)}", ""]
        for q in g.questions:
            pts = f" *({q.points:g} {L['points']})*" if q.points != 1 else ""
            out.append(f"{q.number}. {q.stem}{pts}")
            out += [f"    {o.label}) {o.text}" for o in q.options]
            if q.type.value == "true_false":
                out.append(f"    ☐ {L['TRUE']}    ☐ {L['FALSE']}")
            out.append("")
    if a.rubrics:
        out.extend(_rubrics(a, L))
    return "\n".join(out).rstrip() + "\n"


def _rubrics(a: Assessment, L: dict[str, str]) -> list[str]:
    out = []
    for r in a.rubrics:
        out += [f"## {L['rubric']}: {r.title}", ""]
        for c in r.criteria:
            out += [f"**{c.name}** (×{c.weight:g})", ""]
            out += [f"- {lv.score:g} — {lv.descriptor}" for lv in sorted(c.levels, key=lambda x: -x.score)] + [""]
    return out


def render_answer_key(a: Assessment, lang: Lang) -> str:
    L = _alabels(lang)
    title = f"# {L['key']}: {a.title}" + (f" — {L['version']} {a.version_label}" if a.version_label else "")
    out = [title, ""]
    for g in a.groups:
        for q in g.questions:
            if not q.answer:
                continue
            first, *alts = q.answer.accepted
            shown = L.get(first.upper(), first) if q.type.value == "true_false" else first
            if q.type.value in ("code",):
                out += [f"{q.number}.", "", "```", first, "```"]
            else:
                out.append(f"{q.number}. **{shown}**" + (f" ({L['also']}: {' | '.join(alts)})" if alts else ""))
            if q.answer.explanation:
                out.append(f"    _{q.answer.explanation}_")
            out.append("")
    if a.rubrics:
        out.extend(_rubrics(a, L))
    return "\n".join(out).rstrip() + "\n"
