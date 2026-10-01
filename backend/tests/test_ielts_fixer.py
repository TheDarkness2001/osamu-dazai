from osamu_dazai.ielts import IELTSFormatRepair, lines_from_text, lines_to_text
from osamu_dazai.ielts.fixer import squash
from tests.ielts_helpers import sample_text

FIX = IELTSFormatRepair()


def edit(old: str, new: str) -> str:
    text = sample_text()
    assert old in text, old
    return text.replace(old, new, 1)


def repaired_text(text: str) -> str:
    return lines_to_text(FIX.repair_text(text).repaired)


def test_clean_document_needs_no_repairs():
    rep = FIX.repair_text(sample_text())
    assert rep.ops == [] and rep.flags == [] and rep.ok
    assert lines_to_text(rep.repaired) == sample_text()


def test_spec_example_energy_13():
    bad = edit("12. Some contracts in the 1630s were for bulbs that had not yet been dug up.\n13. ",
               "12. Some bulbs released a small amount of magnetic energy 13 ")
    rep = FIX.repair_text(bad)
    assert rep.ok, rep.render()
    out = lines_to_text(rep.repaired)
    assert "12. Some bulbs released a small amount of magnetic energy\n13 The Haarlem auction" in out
    assert [o.kind for o in rep.ops] == ["split"]


def test_two_numbers_glued_into_one_line():
    bad = edit("11. Growers in the 1630s understood the cause of striped flowers.\n12. Some contracts in the "
               "1630s were for bulbs that had not yet been dug up.\n13. ",
               "11. Growers in the 1630s understood the cause of striped flowers. 12. Some contracts in the "
               "1630s were for bulbs that had not yet been dug up. 13. ")
    rep = FIX.repair_text(bad)
    assert rep.ok, rep.render()
    assert lines_to_text(rep.repaired) == sample_text()


def test_lowercase_continuation_is_flagged_not_split():
    bad = edit("12. Some contracts in the 1630s were for bulbs that had not yet been dug up.\n13. "
               "The Haarlem auction was attended mainly by foreign buyers.",
               "12. Bulbs were sold in 13 countries.")
    rep = FIX.repair_text(bad)
    assert not rep.ok
    assert any("13" in f.problem for f in rep.flags)
    assert all(o.kind != "split" for o in rep.ops)
    assert "ielts.question.missing" in [i.code for i in rep.validation.errors]


def test_ambiguous_position_is_flagged():
    bad = edit("12. Some contracts in the 1630s were for bulbs that had not yet been dug up.\n13. ",
               "12. Bulbs were planted. 13 Traders arrived. 13 ")
    rep = FIX.repair_text(bad)
    assert not rep.ok
    assert len([f for f in rep.flags if "ambiguous" in f.problem]) == 2


def test_glued_headers_repaired():
    bad = edit("foreign buyers.\nPASSAGE 2\nBees in the City\n", "foreign buyers. PASSAGE 2 Bees in the City\n")
    bad = bad.replace("Questions 14-17\n", "Questions 14-17 Choose the correct letter, A, B, C or D.\n", 1)
    bad = bad.replace("Choose the correct letter, A, B, C or D.\nChoose the correct letter", "Choose the correct letter", 1)
    rep = FIX.repair_text(bad)
    assert rep.ok, rep.render()
    assert repaired_text(bad) == sample_text()


def test_glued_options_repaired():
    bad = edit("A. increases the price of honey.\nB. helps reverse the decline of pollinators.\n"
               "C. reduces traffic in cities.\nD. could replace farming.",
               "A. increases the price of honey. B. helps reverse the decline of pollinators. "
               "C. reduces traffic in cities. D. could replace farming.")
    rep = FIX.repair_text(bad)
    assert rep.ok, rep.render()
    assert lines_to_text(rep.repaired) == sample_text()


def test_options_glued_to_question_line():
    bad = edit("15. Why can cities provide varied food for bees?\nA. Cities",
               "15. Why can cities provide varied food for bees? A. Cities")
    rep = FIX.repair_text(bad)
    assert rep.ok, rep.render()


def test_glued_answers_repaired():
    bad = edit("\n1. i\n2. iv\n3. ii\n", "\n1. i 2. iv 3. ii\n")
    rep = FIX.repair_text(bad)
    assert rep.ok, rep.render()
    assert lines_to_text(rep.repaired) == sample_text()


def test_never_invents_answers():
    t = sample_text()
    rep = FIX.repair_text(t[: t.index("ANSWER KEY")])
    assert not rep.ok
    assert "ielts.answer_key.missing" in [i.code for i in rep.validation.errors]
    assert "ANSWER KEY" not in lines_to_text(rep.repaired)


def test_text_is_preserved_exactly():
    bad = edit("dug up.\n13. ", "dug up. 13. ")
    bad = bad.replace("\n1. i\n2. iv\n", "\n1. i 2. iv\n")
    rep = FIX.repair_text(bad)
    assert rep.preserved
    assert squash(lines_from_text(bad)) == squash(rep.repaired)


def test_wording_change_needed_is_flagged_not_done():
    bad = edit("PASSAGE 2\n", "READING PASSAGE 2\n")
    rep = FIX.repair_text(bad)
    assert "READING PASSAGE 2" in lines_to_text(rep.repaired)  # untouched
    assert "ielts.passage.header_wording" in [i.code for i in rep.validation.errors]


def test_report_renders():
    rep = FIX.repair_text(edit("dug up.\n13. ", "dug up. 13 "))
    text = rep.render()
    assert "Repairs applied: 1" in text and "Validation: PASSED" in text
    assert "P1 Questions 8-13: true_false_not_given" in rep.group_summary()
