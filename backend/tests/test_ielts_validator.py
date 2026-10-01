import pytest

from osamu_dazai.domain.questions import CompletionForm
from osamu_dazai.domain.questions import QuestionType as QT
from osamu_dazai.ielts import IELTSDocumentValidator, lines_from_text, parse
from osamu_dazai.ielts import contract as C
from tests.ielts_helpers import sample_lines, sample_text

V = IELTSDocumentValidator()


def codes(text: str) -> list[str]:
    return [i.code for i in V.validate_text(text).issues]


def errors(text: str) -> list[str]:
    return [i.code for i in V.validate_text(text).errors]


def edit(old: str, new: str) -> str:
    text = sample_text()
    assert old in text, old
    return text.replace(old, new, 1)


def index_of(prefix: str) -> int:
    return next(i for i, ln in enumerate(sample_lines()) if ln.startswith(prefix))


# ---------------------------------------------------------------------------
def test_clean_sample_passes_with_no_issues():
    r = V.validate_text(sample_text())
    assert r.passed, [i.render() for i in r.issues]
    assert r.issues == []


def test_parser_reads_structure_and_types():
    p = parse(lines_from_text(sample_text()))
    assert [ps.number for ps in p.passages] == [1, 2, 3]
    assert [ps.title for ps in p.passages] == ["The Rise of the Tulip", "Bees in the City", "Sleep and Memory"]
    got = {g.label: (g.type, g.form) for g in p.groups()}
    assert got == {
        "Questions 1-5": (QT.MATCHING_HEADINGS, None),
        "Questions 6-7": (QT.MULTIPLE_CHOICE_MULTI, None),
        "Questions 8-13": (QT.TRUE_FALSE_NOT_GIVEN, None),
        "Questions 14-17": (QT.MULTIPLE_CHOICE, None),
        "Questions 18-21": (QT.MATCHING_INFORMATION, None),
        "Questions 22-24": (QT.MATCHING_FEATURES, None),
        "Questions 25-26": (QT.COMPLETION, CompletionForm.SENTENCE),
        "Questions 27-31": (QT.YES_NO_NOT_GIVEN, None),
        "Questions 32-35": (QT.COMPLETION, CompletionForm.SUMMARY),
        "Questions 36-38": (QT.MATCHING_SENTENCE_ENDINGS, None),
        "Questions 39-40": (QT.SHORT_ANSWER, None),
    }
    assert sorted(n for it in p.items() for n in it.numbers) == list(range(1, 41))
    compound = p.groups()[1]
    assert compound.items[0].numbers == [6, 7] and len(compound.options) == 5
    assert len(p.groups()[0].romans) == 8
    assert [a.numbers for a in p.answers][5] == [6, 7]


# ---- §20 question numbers ---------------------------------------------------
def test_spec_example_glued_number_detected():
    bad = edit("12. Some contracts in the 1630s were for bulbs that had not yet been dug up.\n13. ",
               "12. Some bulbs stored a small amount of magnetic energy 13 ")
    r = V.validate_text(bad)
    glued = [i for i in r.issues if i.code == "ielts.question.glued"]
    assert len(glued) == 1
    issue = glued[0]
    assert issue.location.question == 13 and issue.location.passage == 1
    assert "energy 13 The" in issue.location.excerpt
    assert "line break before '13'" in issue.suggestion
    assert not r.passed


def test_glued_into_option_line_detected():
    bad = edit("D. could replace farming.\n15. ", "D. could replace farming. 15. ")
    assert "ielts.question.glued" in errors(bad)


def test_glued_in_heading_items():
    bad = edit("4. Paragraph D\n5. Paragraph E", "4. Paragraph D 5. Paragraph E")
    assert "ielts.question.glued" in errors(bad)


def test_glued_first_question_of_group_found_in_previous_group():
    # question 8 is the first of its group; glue it onto the last legend line
    bad = edit("NOT GIVEN if there is no information on this\n8. Tulips",
               "NOT GIVEN if there is no information on this 8. Tulips")
    assert "ielts.question.glued" in errors(bad)


def test_missing_number():
    bad = edit("10. Clusius was paid by the Ottoman court.\n", "")
    errs = errors(bad)
    assert "ielts.question.missing" in errs


def test_duplicate_number():
    bad = edit("10. Clusius was paid", "9. Clusius was paid")
    assert "ielts.question.duplicate" in errors(bad)


def test_out_of_order():
    t = sample_text()
    a = "9. Clusius kept written records of his tulips."
    b = "10. Clusius was paid by the Ottoman court."
    bad = t.replace(f"{a}\n{b}", f"{b}\n{a}")
    assert "ielts.question.order" in errors(bad)


def test_range_not_matching_contents():
    bad = edit("Questions 8-13", "Questions 8-12")
    errs = errors(bad)
    assert "ielts.question.out_of_range" in errs
    assert "ielts.group.gap" in errs  # 14-17 now follows a group ending at 12


def test_lowercase_number_in_text_is_not_called_glued():
    # "13 countries" inside question 12 is a normal number, not a glued question
    bad = edit("12. Some contracts in the 1630s were for bulbs that had not yet been dug up.\n13. "
               "The Haarlem auction was attended mainly by foreign buyers.",
               "12. Bulbs were sold in 13 countries.")
    r = V.validate_text(bad)
    assert "ielts.question.missing" in [i.code for i in r.errors]
    assert "ielts.question.glued" not in [i.code for i in r.issues]


# ---- §18 / §19 headers ------------------------------------------------------
def test_passage_header_glued_before_and_after():
    assert "ielts.passage.header_glued" in errors(edit("\nPASSAGE 2\n", "\nSome text PASSAGE 2\n"))
    assert "ielts.passage.header_glued" in errors(edit("PASSAGE 1\nThe Rise", "PASSAGE 1 The Rise"))


def test_reading_passage_wording_flagged():
    assert "ielts.passage.header_wording" in errors(edit("PASSAGE 2\n", "READING PASSAGE 2\n"))


def test_passage_title_missing():
    bad = edit("PASSAGE 2\nBees in the City\n", "PASSAGE 2\n")
    # the first paragraph becomes the "title" → suspicious; body still present
    assert "ielts.passage.title_suspicious" in codes(bad)


def test_questions_header_with_trailing_text():
    bad = edit("Questions 14-17\n", "Questions 14-17 based on the information below\n")
    assert "ielts.group.header_glued" in errors(bad)


@pytest.mark.parametrize("header", ["Questions 19 to 22", "Questions 19–22", "Questions 19—22", "Questions 19-22"])
def test_valid_range_header_forms(header):
    assert C.QUESTIONS_HEADER.match(header)


def test_instruction_mentioning_questions_is_not_a_header():
    assert C.header_splits("You should spend about 20 minutes on Questions 1-13, which are based on "
                           "Reading Passage 1 below.") == []
    assert C.header_splits("Write your answers in boxes 1-6 on your answer sheet.") == []


# ---- §21–30 question types ----------------------------------------------------
def test_compound_split_into_numbered_questions():
    bad = edit("Which TWO statements about 'broken' tulips are true according to the passage?",
               "6. Which TWO statements about 'broken' tulips are true according to the passage?\n7. (second box)")
    assert "ielts.compound.split" in errors(bad)


def test_compound_choose_mismatch():
    assert "ielts.compound.choose_mismatch" in errors(edit("Choose TWO letters, A-E.", "Choose THREE letters, A-E."))


def test_matching_information_without_list_is_marked_unsafe_not_guessed():
    t = sample_text()
    for c in "ABCDE":
        t = t.replace(f"\n{c} Paragraph {c}\n", "\n", 1)
    r = V.validate_text(t)
    unsafe = [i for i in r.issues if i.code == "ielts.matching_information.auto_detect_unsafe"]
    assert len(unsafe) == 1 and "AUTO-DETECTION NOT SAFE" in unsafe[0].problem
    assert unsafe[0].severity.value == "warning"


def test_headings_need_literal_roman_list():
    t = sample_text()
    for r_ in ["i ", "ii ", "iii ", "iv ", "v ", "vi ", "vii ", "viii "]:
        t = t.replace(f"\n{r_}", "\n", 1)
    assert "ielts.headings.list_missing" in errors(t)


def test_completion_blank_missing():
    assert "ielts.completion.blank_missing" in errors(edit("varroa ______ is", "varroa mite is"))


def test_completion_word_limit_missing():
    bad = edit("Complete the sentences below.\nChoose NO MORE THAN TWO WORDS from the passage for each answer.",
               "Complete the sentences below.")
    assert "ielts.completion.word_limit_missing" in errors(bad)


def test_summary_inline_blank_numbers():
    p = parse(lines_from_text(sample_text()))
    summary = p.groups()[8]
    assert [it.numbers[0] for it in summary.items] == [32, 33, 34, 35]
    assert all(it.inline for it in summary.items)
    assert C.find_inline_items("Trade grew because of 37……………… investment.") == [(37, 22)]
    assert C.find_blanks("He paused... then left.") == []  # an ellipsis is not a blank


def test_short_answer_rules():
    bad = edit("Answer the questions below.\nChoose NO MORE THAN THREE WORDS from the passage for each answer.",
               "Answer the questions below.")
    assert "ielts.short_answer.word_limit_missing" in errors(bad)
    bad = edit("39. Which animals were used in the maze experiments?", "39. The animals used were ______.")
    assert "ielts.short_answer.has_blank" in errors(bad)


def test_unknown_instruction_type():
    assert "ielts.group.type_unknown" in errors(edit("Choose the correct letter, A, B, C or D.",
                                                     "Think about these."))


# ---- §31 answer key -------------------------------------------------------------
def test_answer_key_missing():
    t = sample_text()
    assert "ielts.answer_key.missing" in errors(t[: t.index("ANSWER KEY")])


@pytest.mark.parametrize("heading", ["ANSWER KEY", "ANSWERS KEY", "Answer Sheet", "Complete answer sheet"])
def test_answer_key_heading_variants(heading):
    assert V.validate_text(sample_text().replace("ANSWER KEY", heading)).passed


def test_answer_sheet_instruction_is_not_a_key():
    bad = edit("Write the correct letter, A-E. You may use any letter more than once.",
               "Write the correct letter, A-E, in boxes 18-21 on your answer sheet.")
    assert V.validate_text(bad).passed


def test_answer_missing_and_invalid():
    assert "ielts.answer_key.answer_missing" in errors(edit("\n10. NOT GIVEN\n", "\n"))
    assert "ielts.answer_key.answer_invalid" in errors(edit("\n10. NOT GIVEN\n", "\n10. MAYBE\n"))
    assert "ielts.answer_key.answer_invalid" in errors(edit("\n1. i\n", "\n1. ix\n"))
    assert "ielts.answer_key.answer_invalid" in errors(edit("\n14. B\n", "\n14. F\n"))


def test_compound_answer_per_box_rejected():
    bad = edit("\n6-7. A, C\n", "\n6. A\n7. C\n")
    assert "ielts.answer_key.compound_split" in errors(bad)


def test_compound_answer_count():
    assert "ielts.answer_key.compound_count" in errors(edit("\n6-7. A, C\n", "\n6-7. A\n"))


def test_glued_answers():
    assert "ielts.answer_key.glued" in errors(edit("\n1. i\n2. iv\n", "\n1. i 2. iv\n"))


def test_explanations_inside_key_rejected():
    assert "ielts.answer_key.unparsed_line" in errors(edit("\n1. i\n", "\n1. i\nParagraph A explains the origin.\n"))


def test_answer_key_before_last_group_is_misplaced():
    t = sample_text()
    key_block = t[t.index("ANSWER KEY"):]
    moved = t[: t.index("PASSAGE 3")] + key_block + "\n" + t[t.index("PASSAGE 3"): t.index("ANSWER KEY")]
    errs = errors(moved)
    # after the key everything is answers: passage 3 lines become unparsed answer lines
    assert "ielts.answer_key.unparsed_line" in errs or "ielts.answer_key.misplaced" in errs


def test_answer_alternatives():
    p = parse(lines_from_text(sample_text()))
    a40 = next(a for a in p.answers if a.numbers == [40])
    assert a40.alternatives == ["short daytime nap", "daytime nap", "nap"]


def test_issue_render_format():
    bad = edit("dug up.\n13. ", "dug up. 13 ")
    issue = next(i for i in V.validate_text(bad).issues if i.code.startswith("ielts.question"))
    text = issue.render()
    for part in ("ERROR", "Location:", "Problem:", "Expected structure:"):
        assert part in text
