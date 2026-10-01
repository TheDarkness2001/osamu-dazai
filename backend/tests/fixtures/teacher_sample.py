"""Teacher-guide drafts a well-behaved LLM might return (Uzbek, Latin script)."""

from __future__ import annotations

from osamu_dazai.pipeline.book import ChapterPlan
from osamu_dazai.pipeline.teacher import (
    MisconceptionDraft,
    QADraft,
    StepDraft,
    TeacherChapterDraft,
    TeacherLessonDraft,
)


def lesson_draft(number: int, minutes: int, *, teaching: bool = True, **over) -> TeacherLessonDraft:
    steps = [
        StepDraft(minutes=5, activity="Isinish savoli", teacher_actions="Doskaga savol yozadi va javoblarni yig‘adi",
                  student_actions="Juftlikda muhokama qiladi"),
        StepDraft(minutes=minutes - 15, activity="Jonli kodlash", teacher_actions="Proyektorda qadamma-qadam yozadi",
                  student_actions="Kuzatadi va natijani oldindan aytadi"),
        StepDraft(minutes=10, activity="Mustaqil mashq", teacher_actions="Sinf bo‘ylab yurib yordam beradi",
                  student_actions="Kompyuterda topshiriqni bajaradi"),
    ]
    data = dict(
        lesson_number=number,
        preparation=["Proyektor va kompyuterlarni tekshiring", "Namuna fayllarni oldindan yuklab qo‘ying"],
        resources=["Proyektor", "Har bir o‘quvchi uchun kompyuter"],
        sequence=steps,
        explanation_points=["Avval kundalik hayotdagi o‘xshatish bilan boshlang, keyin sintaksisga o‘ting"],
        demonstrations=["Xatoni ataylab yozib, tarjimon xabarini birga o‘qing"],
        activities=["Juftlikda: bir o‘quvchi kod yozadi, ikkinchisi natijani tekshiradi"],
        questions=[QADraft(question="Dastur ekranga nima chiqaradi?", expected_answer="Ali"),
                   QADraft(question="Qo‘shtirnoqni olib tashlasak nima bo‘ladi?", expected_answer="NameError xatosi",
                           follow_up="Nega aynan shu xato?")] if teaching else
                  [QADraft(question="Bugun nimani takrorladik?", expected_answer="Chiqarish va o‘zgaruvchilar")],
        misconceptions=[MisconceptionDraft(misconception="Teng belgisi tenglikni bildiradi deb o‘ylash",
                                           why_it_happens="Matematika darslaridagi odat",
                                           how_to_address="Qutichaga yorliq yopishtirish o‘xshatishini ko‘rsating")]
        if teaching else [],
        support=["Tayyor kod shabloni bering"] if teaching else [],
        extension=["Ikki o‘zgaruvchini almashtiruvchi dastur yozishni so‘rang"] if teaching else [],
        assessment=["Chiqish chiptasi: bitta qisqa savol"] if teaching else [],
        homework="Uyda o‘zingiz haqingizda uch qatorli dastur yozing.",
        homework_key="Uch marta print() ishlatilgan, matnlar qo‘shtirnoqda bo‘lishi kerak.",
    )
    data.update(over)
    return TeacherLessonDraft(**data)


def teacher_draft(plan: ChapterPlan, **over) -> TeacherChapterDraft:
    return TeacherChapterDraft(lessons=[
        lesson_draft(les.number, les.minutes, teaching=not (les.is_review or les.is_assessment), **over)
        for les in plan.lessons])
