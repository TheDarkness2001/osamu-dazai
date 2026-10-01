"""The IELTS Reading import contract (spec §17–31), encoded as data.

Everything that decides "is this line a header / question / option / answer?"
lives here, so the renderer, parser, validators and fixer share one definition
of the external fixed-rule parser's expectations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from osamu_dazai.domain.questions import CompletionForm as CF
from osamu_dazai.domain.questions import QuestionType as QT

# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------
_RANGE = r"(\d{1,2})\s*(?:-|–|—|\bto\b)\s*(\d{1,2})"

PASSAGE_HEADER = re.compile(r"^PASSAGE\s+(\d{1,2})$")
PASSAGE_ANYWHERE = re.compile(r"\bPASSAGE\s+(\d{1,2})\b")
PART_HEADER = re.compile(r"^PART\s+(\d)$")
PART_ANYWHERE = re.compile(r"\bPART\s+(\d)\b")


@dataclass(frozen=True)
class SectionStyle:
    """How a document's top-level sections are headed (Reading: PASSAGE N, Listening: PART N)."""

    word: str
    header: re.Pattern[str]
    anywhere: re.Pattern[str]
    require_body: bool  # Reading passages have text; Listening parts only a context line
    profile: str


READING = SectionStyle("PASSAGE", PASSAGE_HEADER, PASSAGE_ANYWHERE, True, "ielts_reading")
LISTENING = SectionStyle("PART", PART_HEADER, PART_ANYWHERE, False, "ielts_listening")

QUESTIONS_HEADER = re.compile(rf"^Questions\s+{_RANGE}$")
QUESTIONS_ANYWHERE = re.compile(rf"\bQuestions\s+{_RANGE}")
SINGLE_QUESTION_HEADER = re.compile(r"^Question\s+\d{1,2}$")

ANSWER_KEY_HEADER = re.compile(
    r"^(?:ANSWER KEY|ANSWERS KEY|Answer Sheet|Complete answer sheet)\s*:?$", re.IGNORECASE
)
# Only the unambiguous uppercase forms are searched mid-line ("…on your answer
# sheet." is a normal IELTS instruction and must never be treated as a heading).
ANSWER_KEY_ANYWHERE = re.compile(r"\b(?:ANSWER KEY|ANSWERS KEY)\b")

# ---------------------------------------------------------------------------
# Item lines
# ---------------------------------------------------------------------------
QUESTION_LINE = re.compile(r"^(\d{1,2})(?:\s*[.)])?\s+(\S.*)$")
ANSWER_LINE = re.compile(r"^(\d{1,2})(?:\s*(?:-|–|—)\s*(\d{1,2}))?\s*[.):]?\s+(\S.*)$")
OPTION_LINE = re.compile(r"^([A-Z])(?:\s*[.)])?\s+(\S.*)$")

ROMANS = [
    "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x",
    "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix", "xx",
]  # fmt: skip
ROMAN_LINE = re.compile(
    r"^(" + "|".join(sorted(ROMANS, key=len, reverse=True)) + r")(?:\s*[.)])?\s+(\S.*)$"
)

# ---------------------------------------------------------------------------
# Blanks and word limits
# ---------------------------------------------------------------------------
_BLANK_RAW = re.compile(r"_{3,}|[.…]{2,}")
BLANK_LINE_DEFAULT = "______"  # sentence completion (spec §28)
BLANK_INLINE_DEFAULT = "………………"  # summary/notes/table/flow-chart (spec §29)


def _blank_weight(s: str) -> int:
    return s.count("_") + s.count(".") + 3 * s.count("…")


def find_blanks(text: str) -> list[tuple[int, int]]:
    """Spans of answer blanks ("______", ".....", "………"). A plain "..." is not a blank."""
    out = []
    for m in _BLANK_RAW.finditer(text):
        s = m.group(0)
        if (s[0] == "_" and len(s) >= 3) or _blank_weight(s) >= 4:
            out.append(m.span())
    return out


_INLINE_NUM = re.compile(r"(?<![\w.])\(?(\d{1,2})\)?\s*(?=_{3}|[.…]{2})")


def find_inline_items(text: str) -> list[tuple[int, int]]:
    """(number, offset) for numbered inline blanks like "37……… investment"."""
    blanks = {start for start, _ in find_blanks(text)}
    out = []
    for m in _INLINE_NUM.finditer(text):
        if m.end() in blanks:
            out.append((int(m.group(1)), m.start()))
    return out


WORD_LIMIT = re.compile(
    r"\b(?:NO MORE THAN\s+)?(?:ONE|TWO|THREE|FOUR)\s+WORDS?(?:\s+ONLY)?"
    r"(?:\s+AND/OR\s+(?:A\s+)?NUMBERS?)?\b|\b(?:ONE|A)\s+NUMBER\b"
)
CHOOSE_N = re.compile(r"\bChoose\s+(TWO|THREE|FOUR|FIVE)\s+letters\b", re.IGNORECASE)
WORD_NUMBERS = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}

TFNG_VALUES = {"TRUE", "FALSE", "NOT GIVEN"}
YNNG_VALUES = {"YES", "NO", "NOT GIVEN"}

# Completion forms whose numbers sit inline next to the blank (spec §29).
INLINE_FORMS = {CF.SUMMARY, CF.NOTE, CF.TABLE, CF.FLOW_CHART, CF.FORM, CF.DIAGRAM}

# Question types that use a shared lettered / roman list.
LIST_TYPES = {
    QT.MATCHING_HEADINGS,
    QT.MATCHING_INFORMATION,
    QT.MATCHING_FEATURES,
    QT.MATCHING_SENTENCE_ENDINGS,
    QT.MATCHING,
}


# ---------------------------------------------------------------------------
# Question-type detection from instructions
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DetectedType:
    type: QT
    form: CF | None = None
    choose: int | None = None


def detect_type(instructions: str) -> DetectedType | None:
    """Classify a question group from its instruction text. Order matters."""
    t = " ".join(instructions.split())
    low = t.lower()
    if m := CHOOSE_N.search(t):
        return DetectedType(QT.MULTIPLE_CHOICE_MULTI, choose=WORD_NUMBERS[m.group(1).upper()])
    if re.search(r"\bTRUE\b", t) and re.search(r"\bFALSE\b", t) and "NOT GIVEN" in t:
        return DetectedType(QT.TRUE_FALSE_NOT_GIVEN)
    if re.search(r"\bYES\b", t) and re.search(r"\bNO\b", t) and "NOT GIVEN" in t:
        return DetectedType(QT.YES_NO_NOT_GIVEN)
    if "choose the correct heading" in low or re.search(r"matching headings?|list of headings", low):
        return DetectedType(QT.MATCHING_HEADINGS)
    if re.search(r"which (?:paragraph|section) contains", low):
        return DetectedType(QT.MATCHING_INFORMATION)
    if "correct ending" in low or "sentence endings" in low:
        return DetectedType(QT.MATCHING_SENTENCE_ENDINGS)
    if re.search(r"\bmatch each\b|\bmatch the following\b|\bmatch\b.*\bwith\b", low):
        return DetectedType(QT.MATCHING_FEATURES)
    if "label the" in low and "letter" in low:
        return DetectedType(QT.LABELLING)  # map / plan labelling: write the letter shown on the plan
    for phrase, form in (
        ("complete the summary", CF.SUMMARY),
        ("complete the notes", CF.NOTE),
        ("complete the table", CF.TABLE),
        ("complete the flow-chart", CF.FLOW_CHART),
        ("complete the flow chart", CF.FLOW_CHART),
        ("complete the form", CF.FORM),
        ("label the", CF.DIAGRAM),
    ):
        if phrase in low:
            qt = QT.LABELLING if form is CF.DIAGRAM else QT.COMPLETION
            return DetectedType(qt, form=form)
    if re.search(r"complete (?:the|each) sentences?", low):
        return DetectedType(QT.COMPLETION, form=CF.SENTENCE)
    if "choose the correct letter" in low:
        return DetectedType(QT.MULTIPLE_CHOICE)
    if "answer the questions" in low or "answer the question" in low:
        return DetectedType(QT.SHORT_ANSWER)
    return None


def is_inline(qtype: QT | None, form: CF | None) -> bool:
    return form in INLINE_FORMS


# ---------------------------------------------------------------------------
# Glued-structure detection (shared by validator and fixer)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Split:
    """Insert a line break at ``offset`` in a line."""

    offset: int
    confidence: float
    reason: str


_SENTENCE_END = ".?!…\"”’)"


def header_splits(text: str, style: SectionStyle = READING) -> list[Split]:
    """Places where a section / Questions / ANSWER KEY header shares a line with other text."""
    s = text.rstrip()
    out: list[Split] = []
    if style.header.match(s) or QUESTIONS_HEADER.match(s) or ANSWER_KEY_HEADER.match(s):
        return out

    for m in style.anywhere.finditer(s):
        before = s[: m.start()].rstrip()
        if before:
            if before.split()[-1].upper() in ("READING", "LISTENING"):
                continue  # "READING PASSAGE 1": wording issue, not a glue — validator flags it
            out.append(Split(m.start(), 0.95, f"text before {style.word} header"))
        if s[m.end() :].strip():
            out.append(Split(m.end(), 0.9, f"text after {style.word} header"))

    for m in QUESTIONS_ANYWHERE.finditer(s):
        before = s[: m.start()].rstrip()
        after = s[m.end() :]
        if before:
            # Only a real glue when the previous text has ended a sentence;
            # "…20 minutes on Questions 1-13, which…" is an ordinary instruction.
            if before[-1] in _SENTENCE_END and (not after.strip() or after.lstrip()[:1].isupper()):
                out.append(Split(m.start(), 0.85, "text before Questions header"))
            else:
                continue
        if after.strip():
            if after[:1].isspace():
                out.append(Split(m.end(), 0.85, "instruction text on the Questions header line"))
            # "Questions 1-6, which…" (punctuation) is prose — leave it

    for m in ANSWER_KEY_ANYWHERE.finditer(s):
        if s[: m.start()].strip():
            out.append(Split(m.start(), 0.9, "text before ANSWER KEY heading"))
        if s[m.end() :].strip(" :"):
            out.append(Split(m.end(), 0.9, "text after ANSWER KEY heading"))
    return out


_LETTER_MARK = re.compile(r"(?:(?<=\s)|^)([A-H])[.)]\s+(?=\S)")
_ROMAN_MARK = re.compile(
    r"(?:(?<=\s)|^)(" + "|".join(sorted(ROMANS[:12], key=len, reverse=True)) + r")[.)]\s+(?=\S)"
)


def list_marker_splits(text: str, *, roman: bool = False) -> list[Split]:
    """Glued list entries, e.g. "A. one B. two C. three" or "14. Why…? A. x B. y".

    Requires a run of punctuated markers in sequence (A., B., C. … or i., ii. …)
    starting from the first list label, so ordinary prose rarely triggers it.
    """
    order = ROMANS if roman else [chr(c) for c in range(ord("A"), ord("I"))]
    marks = [(m.group(1), m.start()) for m in (_ROMAN_MARK if roman else _LETTER_MARK).finditer(text)]
    lead = len(text) - len(text.lstrip())
    for start_idx, (label, _pos) in enumerate(marks):
        if label != order[0] and not (start_idx == 0 and _pos <= lead and label in order):
            continue
        want = order.index(label)
        chain = []
        for lab, pos in marks[start_idx:]:
            if want < len(order) and lab == order[want]:
                chain.append(pos)
                want += 1
        if len(chain) >= 2:
            return [Split(p, 0.85, "list entries glued on one line") for p in chain if p > lead]
    return []


def glued_number_splits(text: str, number: int, *, answer_key: bool = False) -> list[Split]:
    """Places where question ``number`` starts mid-line (e.g. "…energy 13 The author…").

    Only positions after whitespace count, and never at the start of the line.
    In question text the next token must look like a new sentence (capital,
    quote, or a blank); in the answer key any token may follow.
    """
    out = []
    pat = re.compile(rf"(?<=\s)({number})(?:\s*[.)])?\s+(?=\S)")
    lead = len(text) - len(text.lstrip())
    for m in pat.finditer(text):
        if m.start() <= lead:
            continue
        nxt = text[m.end()]
        prev = text[: m.start()].rstrip()[-1:]
        if answer_key:
            out.append(Split(m.start(), 0.9, f"answer {number} glued to previous answer"))
            continue
        if nxt.isupper() or nxt in "\"'“‘(" or find_blanks(text[m.end() : m.end() + 8]):
            conf = 0.95 if prev and prev in _SENTENCE_END else 0.9
            out.append(Split(m.start(), conf, f"question {number} glued to previous text"))
        else:
            out.append(Split(m.start(), 0.5, f"'{number}' mid-line followed by lowercase text"))
    return out
