"""Deterministic question/assessment validator (spec §14 'Questions').

Duplicate or missing numbers, missing answers, answers of the wrong type,
invalid structures (too few / duplicate options, blanks missing, essays
without rubrics), code answers that do not parse, and answer-leaking
patterns (correct option longest far more often than chance).
"""

from __future__ import annotations

import re

from osamu_dazai.domain.common import Severity
from osamu_dazai.domain.questions import Assessment, Question, QuestionType
from osamu_dazai.domain.validation import Location, ValidationIssue, ValidationResult
from osamu_dazai.ielts.contract import find_blanks
from osamu_dazai.questions.shuffle import longest_answer_bias
from osamu_dazai.quality.code import check_syntax

E, W = Severity.ERROR, Severity.WARNING
QT = QuestionType
TF_VALUES = {"TRUE", "FALSE"}
BANNED_OPTIONS = re.compile(r"^(all|none|both) of the (above|options)\.?$|^(barchasi|hech biri|все|ни один)"
                            r"( (to‘g‘ri|javob|из вышеперечисленных))?\.?$", re.IGNORECASE)


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", s.casefold()).split())


def question_issues(q: Question, *, code_language: str = "") -> list[tuple[str, Severity, str]]:
    """(code, severity, problem) for one question."""
    out: list[tuple[str, Severity, str]] = []
    if not q.stem.strip():
        out.append(("question.empty_stem", E, "Question has no text"))
    if q.answer is None or not any(a.strip() for a in q.answer.accepted):
        out.append(("question.answer_missing", E, "Question has no answer"))
        return out
    ans = [a.strip() for a in q.answer.accepted]
    if q.type in (QT.MULTIPLE_CHOICE, QT.MULTIPLE_CHOICE_MULTI):
        labels = [o.label for o in q.options]
        if len(q.options) < 3:
            out.append(("question.mc_too_few_options", E, f"Only {len(q.options)} options"))
        if len(set(labels)) != len(labels):
            out.append(("question.mc_duplicate_labels", E, "Option labels repeat"))
        texts = [_norm(o.text) for o in q.options]
        if len(set(texts)) != len(texts):
            out.append(("question.mc_duplicate_options", E, "Two options have the same text"))
        if any(BANNED_OPTIONS.match(o.text.strip()) for o in q.options):
            out.append(("question.mc_all_none_of_above", W, "'All/none of the above' weakens the item"))
        bad = [a for a in ans if a not in labels]
        if bad:
            out.append(("question.answer_wrong_type", E, f"Answer {bad} is not one of the option letters {labels}"))
        if q.type is QT.MULTIPLE_CHOICE and len(ans) != 1:
            out.append(("question.answer_wrong_type", E, "Single-answer multiple choice needs exactly one letter"))
    elif q.type is QT.TRUE_FALSE:
        if ans[0].upper() not in TF_VALUES:
            out.append(("question.answer_wrong_type", E, f"True/false answer is '{ans[0]}'"))
    elif q.type is QT.COMPLETION:
        if not find_blanks(q.stem):
            out.append(("question.completion_no_blank", E, "Completion item has no blank (______)"))
    elif q.type is QT.CODE and code_language:
        chk = check_syntax(code_language, ans[0])
        if not chk.ok:
            out.append(("question.code_answer_invalid", E, f"Model answer: {chk.message}"))
    return out


def validate_assessment(a: Assessment, *, code_language: str = "") -> ValidationResult:
    issues: list[ValidationIssue] = []

    def add(code: str, sev: Severity, problem: str, number: int | None = None, suggestion: str = "") -> None:
        issues.append(ValidationIssue(code=code, severity=sev, problem=problem, suggestion=suggestion,
                                      location=Location(question=number, excerpt=a.title)))

    questions = [q for g in a.groups for q in g.questions]
    numbers = [n for q in questions for n in q.numbers()]
    seen: set[int] = set()
    for n in numbers:
        if n in seen:
            add("question.duplicate_number", E, f"Question number {n} is used twice", n)
        seen.add(n)
    if numbers and sorted(set(numbers)) != list(range(1, max(numbers) + 1)):
        missing = sorted(set(range(1, max(numbers) + 1)) - set(numbers))
        add("question.missing_number", E, f"Numbering skips {missing}")
    if numbers != sorted(numbers):
        add("question.order", E, "Questions are not in numerical order")
    stems: dict[str, int] = {}
    for q in questions:
        n = q.numbers()[0]
        for code, sev, problem in question_issues(q, code_language=code_language):
            add(code, sev, problem, n)
        key = _norm(q.stem)
        if key and key in stems:
            add("question.duplicate_stem", E, f"Same question as number {stems[key]}", n)
        stems.setdefault(key, n)
        if q.type is QT.ESSAY and not a.rubrics:
            add("question.essay_without_rubric", E, "Essay/project task without a marking rubric", n)
    for r in a.rubrics:
        for c in r.criteria:
            scores = [lv.score for lv in c.levels]
            if len(set(scores)) != len(scores) or len(scores) < 2:
                add("rubric.levels", E, f"Rubric criterion '{c.name}' needs ≥2 levels with distinct scores")
            if c.weight <= 0:
                add("rubric.weight", E, f"Rubric criterion '{c.name}' has non-positive weight")
    leaky = longest_answer_bias(questions)
    if leaky:
        add("question.longest_answer_bias", W,
            f"The correct option is the longest in questions {[q.numbers()[0] for q in leaky]} — "
            "test-wise students can guess it", suggestion="Rewrite distractors so lengths are comparable")
    return ValidationResult(target_id=a.id, profile="assessment", issues=issues)
