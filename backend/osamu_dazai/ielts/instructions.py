"""Standard IELTS Reading instruction wording, generated deterministically.

The LLM never writes instructions: the parser detects question types from
this wording (contract.detect_type), so it must be exact.
"""

from __future__ import annotations

from osamu_dazai.domain.questions import CompletionForm as CF
from osamu_dazai.domain.questions import QuestionType as QT

WORD_LIMIT_PHRASES = {
    1: "ONE WORD ONLY",
    2: "NO MORE THAN TWO WORDS",
    3: "NO MORE THAN THREE WORDS",
}
CHOOSE_WORDS = {2: "TWO", 3: "THREE"}


def letters(n: int) -> str:
    return "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[:n]


def listening_instructions(kind: str, *, first: int, last: int, options: int = 0, word_limit: str = "") -> list[str]:
    """Standard IELTS Listening instruction wording (detected by contract.detect_type)."""
    last_opt = letters(max(options, 1))[-1]
    if kind == "form":
        return ["Complete the form below.", f"Write {word_limit} for each answer."]
    if kind == "note":
        return ["Complete the notes below.", f"Write {word_limit} for each answer."]
    if kind == "table":
        return ["Complete the table below.", f"Write {word_limit} for each answer."]
    if kind == "sentence":
        return ["Complete the sentences below.", f"Write {word_limit} for each answer."]
    if kind == "mc":
        return [f"Choose the correct letter, {', '.join(letters(options)[:-1])} or {last_opt}."]
    if kind == "map":
        return ["Label the plan below.", f"Write the correct letter, A-{last_opt}, next to Questions {first}-{last}."]
    if kind == "matching":
        return ["Look at the following statements and the list below.",
                f"Match each statement with the correct item, A-{last_opt}. You may use any letter more than once."]
    raise ValueError(f"no listening instruction template for {kind}")


def instructions(
    qtype: QT,
    *,
    passage: int,
    paragraphs: int,
    options: int = 0,
    choose: int | None = None,
    form: CF | None = None,
    word_limit: int | None = None,
) -> list[str]:
    last = letters(max(paragraphs, 1))[-1]
    last_opt = letters(max(options, 1))[-1]
    limit = WORD_LIMIT_PHRASES.get(word_limit or 0, "")
    if qtype is QT.MATCHING_HEADINGS:
        return [f"Reading Passage {passage} has {paragraphs} paragraphs, A-{last}.",
                "Choose the correct heading for each paragraph from the list of headings below."]
    if qtype is QT.MULTIPLE_CHOICE_MULTI:
        return [f"Choose {CHOOSE_WORDS[choose or 2]} letters, A-{last_opt}."]
    if qtype is QT.MULTIPLE_CHOICE:
        return ["Choose the correct letter, A, B, C or D."]
    if qtype is QT.TRUE_FALSE_NOT_GIVEN:
        return [f"Do the following statements agree with the information given in Reading Passage {passage}?",
                "Write",
                "TRUE if the statement agrees with the information",
                "FALSE if the statement contradicts the information",
                "NOT GIVEN if there is no information on this"]
    if qtype is QT.YES_NO_NOT_GIVEN:
        return [f"Do the following statements agree with the claims of the writer in Reading Passage {passage}?",
                "Write",
                "YES if the statement agrees with the claims of the writer",
                "NO if the statement contradicts the claims of the writer",
                "NOT GIVEN if it is impossible to say what the writer thinks about this"]
    if qtype is QT.MATCHING_INFORMATION:
        return [f"Reading Passage {passage} has {paragraphs} paragraphs, A-{last}.",
                "Which paragraph contains the following information?",
                f"Write the correct letter, A-{last}. You may use any letter more than once."]
    if qtype is QT.MATCHING_FEATURES:
        return ["Look at the following statements and the list below.",
                f"Match each statement with the correct item, A-{last_opt}. You may use any letter more than once."]
    if qtype is QT.MATCHING_SENTENCE_ENDINGS:
        return [f"Complete each sentence with the correct ending, A-{last_opt}, below."]
    if qtype is QT.COMPLETION and form is CF.SUMMARY:
        return ["Complete the summary below.", f"Choose {limit} from the passage for each answer."]
    if qtype is QT.COMPLETION and form is CF.NOTE:
        return ["Complete the notes below.", f"Choose {limit} from the passage for each answer."]
    if qtype is QT.COMPLETION:
        return ["Complete the sentences below.", f"Choose {limit} from the passage for each answer."]
    if qtype is QT.SHORT_ANSWER:
        return ["Answer the questions below.", f"Choose {limit} from the passage for each answer."]
    raise ValueError(f"no instruction template for {qtype} / {form}")
