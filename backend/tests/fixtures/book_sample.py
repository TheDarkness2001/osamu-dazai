"""Builds chapter drafts a well-behaved LLM might return for the Uzbek Python course."""

from __future__ import annotations

from osamu_dazai.domain.content import SectionKind as SK
from osamu_dazai.domain.graph import ConceptGraph
from osamu_dazai.pipeline.book import BlockDraft, ChapterDraft, ChapterPlan, ExerciseDraft, GlossaryDraft, SectionDraft

UZ_TERMS = {
    "print_output": "chiqarish", "variables": "o‘zgaruvchi", "data_types": "ma’lumot turi",
    "user_input": "foydalanuvchi kiritishi", "arithmetic": "arifmetik amal", "strings": "satr",
    "type_conversion": "turni o‘zgartirish", "comparison": "taqqoslash", "boolean_logic": "mantiqiy ifoda",
    "conditions": "shart", "while_loop": "while sikli", "for_loop": "for sikli",
}

FILLER = ("Bu bobda biz dasturlashning muhim gʻoyalarini oddiy misollar bilan oʻrganamiz va har bir qadamni "
          "diqqat bilan tushuntiramiz.")


def chapter_draft(plan: ChapterPlan, graph: ConceptGraph, *, code: str = 'ism = "Ali"\nprint(ism)',
                  expected: str = "Ali", include_review: bool = True, glossary_terms: dict[str, str] | None = None,
                  extra_text: str = "") -> ChapterDraft:
    by = graph.by_id()
    terms = {**UZ_TERMS, **(glossary_terms or {})}
    keys = [c.removeprefix("con_") for c in plan.introduces]
    explain = [BlockDraft(kind="paragraph",
                          text=f"{terms.get(k, k)} ({by['con_' + k].name}) — {FILLER} {extra_text}".strip())
               for k in keys] or [BlockDraft(kind="paragraph", text=FILLER)]
    sections = [
        SectionDraft(kind=SK.OBJECTIVES, title="Maqsadlar",
                     blocks=[BlockDraft(kind="list", items=[o.text for o in plan.objectives] or ["Mashq qilish"])]),
        SectionDraft(kind=SK.INTRODUCTION, title="Kirish", blocks=[BlockDraft(kind="paragraph", text=FILLER)]),
        SectionDraft(kind=SK.EXPLANATION, title="Tushuntirish", blocks=explain),
        SectionDraft(kind=SK.WORKED_EXAMPLE, title="Namuna", blocks=[
            BlockDraft(kind="code", language="python", code=code, expected_output=expected),
            BlockDraft(kind="visual", visual_kind="flowchart", title="Dastur qadamlari",
                       visual_purpose="dastur ketma-ketligini ko‘rsatish",
                       visual_description="start → qiymat berish → chiqarish → tugash")]),
        SectionDraft(kind=SK.COMMON_MISTAKES, title="Keng tarqalgan xatolar",
                     blocks=[BlockDraft(kind="callout", style="common_mistake", title="Diqqat", text=FILLER)]),
        SectionDraft(kind=SK.GUIDED_PRACTICE, title="Birgalikda mashq",
                     blocks=[BlockDraft(kind="paragraph", text=FILLER)]),
        SectionDraft(kind=SK.QUIZ, title="Test", blocks=[BlockDraft(kind="paragraph", text="Savollarga javob bering.")]),
    ]
    if include_review:
        sections.append(SectionDraft(kind=SK.REVIEW, title="Takrorlash",
                                     blocks=[BlockDraft(kind="list", items=[terms.get(k, k) for k in keys] or [FILLER])]))
    return ChapterDraft(
        title=f"{plan.number}-bob: " + (", ".join(by[c].name for c in plan.introduces[:2]) or "Takrorlash"),
        summary=f"Bob {plan.number}: {', '.join(keys) or 'takrorlash'}.",
        sections=sections,
        exercises=[
            ExerciseDraft(section="guided_practice", kind="code", prompt="Ismingizni chiqaradigan dastur yozing.",
                          answer='print("Ali")', difficulty=1),
            ExerciseDraft(section="guided_practice", kind="short_answer", prompt="print() nima qiladi?",
                          answer="Ekranga matn chiqaradi.", difficulty=1),
            ExerciseDraft(section="quiz", kind="multiple_choice", prompt="Qaysi biri to‘g‘ri?",
                          options=["print(1)", "print 1", "echo 1"], answer="A", difficulty=1),
        ],
        glossary=[GlossaryDraft(key=k, term=terms.get(k, k), definition=FILLER) for k in keys],
        examples_used=[f"ch{plan.number}-ism-chiqarish"],
    )
