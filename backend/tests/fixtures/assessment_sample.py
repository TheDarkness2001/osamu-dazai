"""Builds a valid AssessmentDraft for any blueprint (what a good LLM would return), in Uzbek."""

from __future__ import annotations

from osamu_dazai.domain.common import BloomLevel
from osamu_dazai.questions.generator import AssessmentDraft, Blueprint, CriterionDraft, LevelDraft, QDraft, RubricDraft

OPTION_SETS = [
    ["Ekranga matn chiqaradi", "Faylni o‘chirib yuboradi", "Kompyuterni o‘chiradi", "Yangi papka yaratadi"],
    ["Qiymat saqlovchi nom", "Ekran rangini o‘zgartiradi", "Internetga ulanish usuli", "Klaviatura tugmasi turi"],
    ["Butun son turi", "Matnli xabar turi", "Rasm fayli turi", "Ovozli signal turi"],
    ["Ikki sonni qo‘shadi", "Dasturni to‘xtatadi", "Xatoni yashiradi", "Ekranni tozalaydi"],
]


def assessment_draft(bp: Blueprint) -> AssessmentDraft:
    objs = [o.id for o in bp.objectives]
    concepts = list(bp.taught)
    qs: list[QDraft] = []
    i = 0
    for t, n in bp.mix.items():
        for _ in range(n):
            o = objs[i % len(objs)]
            c = [concepts[i % len(concepts)]]
            bloom = BloomLevel.APPLY if i % 2 == 0 else BloomLevel.UNDERSTAND
            diff = 1 + i % 3
            if t == "multiple_choice":
                opts = OPTION_SETS[i % len(OPTION_SETS)]
                q = QDraft(type=t, stem=f"{i + 1}-savol: quyidagi koddagi buyruq nima vazifani bajaradi?",
                           options=opts, answer="A", explanation="Birinchi variant to‘g‘ri, chunki u vazifani "
                           "aniq tasvirlaydi.", objectives=[o], concepts=c, bloom_level=bloom, difficulty=diff)
            elif t == "true_false":
                q = QDraft(type=t, stem=f"{i + 1}-tasdiq: o‘zgaruvchi nomi raqam bilan boshlanishi mumkin.",
                           answer="FALSE", explanation="Nom harf yoki pastki chiziq bilan boshlanadi.",
                           objectives=[o], concepts=c, bloom_level=bloom, difficulty=diff)
            elif t == "completion":
                q = QDraft(type=t, stem=f"{i + 1}. Ekranga matn chiqarish uchun ______ funksiyasidan foydalanamiz.",
                           answer="print", explanation="print() matnni ekranga chiqaradi.", objectives=[o],
                           concepts=c, bloom_level=bloom, difficulty=diff)
            elif t == "short_answer":
                q = QDraft(type=t, stem=f"{i + 1}. O‘zgaruvchi nima uchun kerakligini o‘z so‘zlaringiz bilan "
                                        "tushuntiring.",
                           answer="Qiymatni saqlash va keyinroq ishlatish uchun.", alternatives=["qiymatni saqlash"],
                           explanation="Asosiy g‘oya — saqlash.", objectives=[o], concepts=c, bloom_level=bloom,
                           difficulty=diff)
            elif t == "code":
                q = QDraft(type=t, stem=f"{i + 1}. Ismingizni o‘zgaruvchiga saqlab, uni ekranga chiqaradigan "
                                        "dastur yozing.",
                           answer='ism = "Ali"\nprint(ism)', explanation="O‘zgaruvchi va print birga ishlatiladi.",
                           objectives=[o], concepts=c, bloom_level=BloomLevel.APPLY, difficulty=diff)
            else:  # essay / project
                q = QDraft(type=t, stem="Kichik loyiha: o‘quvchilar ro‘yxatini saqlaydigan va baholarini "
                                        "hisoblaydigan dastur yarating hamda uni sinfga taqdim eting.",
                           answer="Namuna yechim: ro‘yxat, sikl va funksiyalardan foydalangan dastur.",
                           explanation="Loyiha barcha asosiy ko‘nikmalarni birlashtiradi.", objectives=objs,
                           concepts=concepts[:3], bloom_level=BloomLevel.CREATE, difficulty=4, points=20)
            qs.append(q)
            i += 1
    rubrics = []
    if bp.mix.get("essay"):
        levels = [LevelDraft(score=4, descriptor="A’lo: to‘liq va aniq"), LevelDraft(score=2, descriptor="Qisman"),
                  LevelDraft(score=0, descriptor="Bajarilmagan")]
        rubrics = [RubricDraft(title="Loyiha", criteria=[CriterionDraft(name=n, levels=levels)
                                                         for n in ("To‘g‘ri ishlashi", "Kod sifati", "Taqdimot")])]
    return AssessmentDraft(title=bp.item.title, instructions="Barcha savollarga javob bering. Omad!",
                           questions=qs, rubrics=rubrics)
