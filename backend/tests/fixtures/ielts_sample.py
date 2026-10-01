"""Original IELTS Academic Reading test used as the §46 acceptance fixture.

All passages and questions were written for Osamu Dazai's test suite (no third-party
test material). 3 passages, 40 questions, 10 question types.
"""

from __future__ import annotations

from osamu_dazai.domain.common import Provenance
from osamu_dazai.domain.questions import (
    Answer,
    CompletionForm,
    Option,
    Question,
    QuestionGroup,
    WordLimit,
)
from osamu_dazai.domain.questions import QuestionType as QT
from osamu_dazai.ielts.model import IELTSReadingTest, Passage, PassageParagraph, ReadingSection

ORIGINAL = Provenance.TEACHER_AUTHORED


def _q(n: int, t: QT, stem: str, *answers: str, options: list[Option] | None = None) -> Question:
    return Question(number=n, type=t, stem=stem, options=options or [], answer=Answer(accepted=list(answers)),
                    provenance=ORIGINAL)


def _opts(*texts: str, letters: str = "ABCDEFGH") -> list[Option]:
    return [Option(label=letters[i], text=t) for i, t in enumerate(texts)]


def _paras(*texts: str) -> list[PassageParagraph]:
    return [PassageParagraph(label="ABCDEFGH"[i], text=t) for i, t in enumerate(texts)]


TFNG_LEGEND = [
    "Do the following statements agree with the information given in Reading Passage 1?",
    "Write",
    "TRUE if the statement agrees with the information",
    "FALSE if the statement contradicts the information",
    "NOT GIVEN if there is no information on this",
]


def passage_1() -> ReadingSection:
    p = Passage(
        number=1,
        title="The Rise of the Tulip",
        provenance=ORIGINAL,
        source_note="original text written for the Osamu Dazai test suite",
        paragraphs=_paras(
            "The tulip did not originate in the Netherlands. Wild tulips grew across the mountains of Central "
            "Asia, and by the sixteenth century the flower was widely cultivated in the gardens of the Ottoman "
            "Empire, where it was valued as a symbol of abundance.",
            "European interest in the plant grew after diplomats and travellers sent bulbs home from "
            "Constantinople. The botanist Carolus Clusius planted a collection at the university garden in "
            "Leiden in 1594, and his careful records helped growers understand how the bulbs behaved in a "
            "colder climate.",
            "Some bulbs produced flowers with striking feathered stripes. Growers did not know that this pattern "
            "was caused by a virus carried by aphids, so the rare striped varieties appeared almost by chance. "
            "Because they could not be reproduced reliably, these 'broken' tulips became the most desired of all.",
            "During the 1630s, trade in bulbs moved from gardens into taverns, where buyers signed contracts for "
            "bulbs that were still in the ground. Prices for a few celebrated varieties rose quickly, and in early "
            "1637 a single bulb was reportedly offered for more than the annual income of a skilled craftsman.",
            "The market collapsed in February 1637 when buyers failed to appear at an auction in Haarlem. "
            "Historians now argue that the financial damage was smaller than popular accounts suggest, because "
            "many contracts were never enforced and most of the Dutch economy was unaffected.",
        ),
    )
    headings = _opts(
        "A flower from the east",
        "An accidental source of beauty",
        "Government controls on trade",
        "Scientific study in a new climate",
        "A sudden end with limited consequences",
        "The decline of Ottoman gardens",
        "Speculation outside the garden",
        "Modern tulip festivals",
        letters=["i", "ii", "iii", "iv", "v", "vi", "vii", "viii"],  # type: ignore[arg-type]
    )
    g1 = QuestionGroup(
        type=QT.MATCHING_HEADINGS, range=(1, 5),
        instructions=["Reading Passage 1 has five paragraphs, A-E.",
                      "Choose the correct heading for each paragraph from the list of headings below."],
        list_title="List of Headings", shared_options=headings,
        questions=[_q(n, QT.MATCHING_HEADINGS, f"Paragraph {'ABCDE'[n - 1]}", a)
                   for n, a in zip(range(1, 6), ["i", "iv", "ii", "vii", "v"], strict=True)],
    )
    g2 = QuestionGroup(
        type=QT.MULTIPLE_CHOICE_MULTI, range=(6, 7),
        instructions=["Choose TWO letters, A-E."],
        questions=[Question(
            number_range=(6, 7), choose=2, type=QT.MULTIPLE_CHOICE_MULTI,
            stem="Which TWO statements about 'broken' tulips are true according to the passage?",
            options=_opts("Their stripes were caused by a virus.", "Growers could easily produce them.",
                          "The virus was spread by insects.", "They grew only in Leiden.",
                          "They were cheaper than plain tulips."),
            answer=Answer(accepted=["A", "C"], unordered=True), provenance=ORIGINAL)],
    )
    tf = QT.TRUE_FALSE_NOT_GIVEN
    g3 = QuestionGroup(
        type=tf, range=(8, 13), instructions=TFNG_LEGEND,
        questions=[
            _q(8, tf, "Tulips first grew wild in the Netherlands.", "FALSE"),
            _q(9, tf, "Clusius kept written records of his tulips.", "TRUE"),
            _q(10, tf, "Clusius was paid by the Ottoman court.", "NOT GIVEN"),
            _q(11, tf, "Growers in the 1630s understood the cause of striped flowers.", "FALSE"),
            _q(12, tf, "Some contracts in the 1630s were for bulbs that had not yet been dug up.", "TRUE"),
            _q(13, tf, "The Haarlem auction was attended mainly by foreign buyers.", "NOT GIVEN"),
        ],
    )
    return ReadingSection(passage=p, groups=[g1, g2, g3])


def passage_2() -> ReadingSection:
    p = Passage(
        number=2,
        title="Bees in the City",
        provenance=ORIGINAL,
        source_note="original text written for the Osamu Dazai test suite",
        paragraphs=_paras(
            "Over the past two decades, beehives have appeared on rooftops, balconies and office terraces in "
            "cities around the world. Supporters claim that urban hives help to reverse the decline of pollinating "
            "insects, while also connecting city residents with the source of their food.",
            "Cities can offer bees a surprising variety of food. Parks, private gardens and roadside verges often "
            "contain a wider range of flowering plants than intensively farmed countryside, where large fields may "
            "be planted with a single crop. Ecologist Lena Ortiz found that honey from city hives contained pollen "
            "from more plant species than honey from nearby farms.",
            "However, more hives do not always mean more pollination. Honeybees compete with wild bees for nectar "
            "and pollen, and Professor Kamal Haidari warns that a high density of managed hives can leave too "
            "little food for solitary species, which are often more effective pollinators of native plants.",
            "Disease is a further concern. When hives are placed close together, parasites such as the varroa mite "
            "can spread more easily between colonies. Veterinary researcher Sofia Brandt argues that new "
            "beekeepers need formal training, because poorly managed hives may become reservoirs of infection.",
            "Some cities have responded by limiting the number of hives per district and by encouraging residents "
            "to plant flowers instead of keeping bees. Planting, these programmes argue, supports all pollinators "
            "rather than one domesticated species.",
        ),
    )
    mc = QT.MULTIPLE_CHOICE
    g1 = QuestionGroup(
        type=mc, range=(14, 17), instructions=["Choose the correct letter, A, B, C or D."],
        questions=[
            _q(14, mc, "According to paragraph A, supporters of urban beekeeping believe that it", "B",
               options=_opts("increases the price of honey.", "helps reverse the decline of pollinators.",
                             "reduces traffic in cities.", "could replace farming.")),
            _q(15, mc, "Why can cities provide varied food for bees?", "C",
               options=_opts("Cities are warmer than the countryside.", "Farmers use fewer chemicals.",
                             "Urban areas contain many different flowering plants.",
                             "Bees travel further in cities.")),
            _q(16, mc, "What does Professor Haidari say about solitary bees?", "A",
               options=_opts("They are often better pollinators of native plants.", "They produce more honey.",
                             "They are rare in cities.", "They spread disease.")),
            _q(17, mc, "Some cities have responded to these concerns by", "C",
               options=_opts("banning all beehives.", "paying beekeepers.",
                             "limiting hive numbers in each district.", "importing wild bees.")),
        ],
    )
    mi = QT.MATCHING_INFORMATION
    g2 = QuestionGroup(
        type=mi, range=(18, 21),
        instructions=["Reading Passage 2 has five paragraphs, A-E.",
                      "Which paragraph contains the following information?",
                      "Write the correct letter, A-E. You may use any letter more than once."],
        shared_options=[Option(label=c, text=f"Paragraph {c}") for c in "ABCDE"],
        questions=[
            _q(18, mi, "a comparison between the diet of city bees and farm bees", "B"),
            _q(19, mi, "a reason why disease spreads between hives", "D"),
            _q(20, mi, "an alternative to keeping bees", "E"),
            _q(21, mi, "the claimed benefits of rooftop hives", "A"),
        ],
    )
    mf = QT.MATCHING_FEATURES
    g3 = QuestionGroup(
        type=mf, range=(22, 24),
        instructions=["Look at the following statements and the list of researchers below.",
                      "Match each statement with the correct researcher, A, B or C."],
        list_title="List of Researchers",
        shared_options=_opts("Lena Ortiz", "Kamal Haidari", "Sofia Brandt"),
        questions=[
            _q(22, mf, "Too many managed hives can reduce food for other species.", "B"),
            _q(23, mf, "Inexperienced beekeepers should receive training.", "C"),
            _q(24, mf, "City honey shows evidence of a wide range of plants.", "A"),
        ],
    )
    sc = QT.COMPLETION
    g4 = QuestionGroup(
        type=sc, completion_form=CompletionForm.SENTENCE, range=(25, 26),
        instructions=["Complete the sentences below.",
                      "Choose NO MORE THAN TWO WORDS from the passage for each answer."],
        word_limit=WordLimit(max_words=2, raw="NO MORE THAN TWO WORDS"),
        questions=[
            _q(25, sc, "The varroa ______ is a parasite that can spread between colonies.", "mite"),
            _q(26, sc, "In the countryside, large fields are often planted with a single ______.", "crop"),
        ],
    )
    return ReadingSection(passage=p, groups=[g1, g2, g3, g4])


def passage_3() -> ReadingSection:
    p = Passage(
        number=3,
        title="Sleep and Memory",
        provenance=ORIGINAL,
        source_note="original text written for the Osamu Dazai test suite",
        paragraphs=_paras(
            "For much of the twentieth century, sleep was viewed as a passive state in which the brain simply "
            "rested. This view now seems mistaken. Research over the last thirty years suggests that sleep plays an "
            "active role in strengthening memories, and in my view, schools and workplaces have been slow to take "
            "this evidence seriously.",
            "During deep sleep, the brain appears to replay patterns of activity recorded during the day. "
            "Experiments with rats running through mazes showed that cells in the hippocampus fired in the same "
            "sequence during sleep as they had during the task. This replay is thought to help transfer "
            "information to long-term storage in the cortex.",
            "Studies with human volunteers point in the same direction. Participants who slept after learning a "
            "list of word pairs recalled more pairs the next morning than those who stayed awake for the same "
            "period. The benefit was greatest for material that participants had found difficult.",
            "Sleep may also help people to see hidden patterns. In one well-known experiment, volunteers solved a "
            "number puzzle that contained a concealed shortcut. Those who slept between attempts were more than "
            "twice as likely to discover the shortcut as those who did not. It would be wrong, however, to "
            "conclude that sleep makes people more intelligent; rather, it seems to reorganise what they already "
            "know.",
            "These findings have practical implications. Students who sacrifice sleep to revise late at night may "
            "remember less than those who study for a shorter time and sleep well. Even a short daytime nap can "
            "improve recall, although its effects are smaller than those of a full night's sleep.",
        ),
    )
    yn = QT.YES_NO_NOT_GIVEN
    g1 = QuestionGroup(
        type=yn, range=(27, 31),
        instructions=["Do the following statements agree with the claims of the writer in Reading Passage 3?",
                      "Write",
                      "YES if the statement agrees with the claims of the writer",
                      "NO if the statement contradicts the claims of the writer",
                      "NOT GIVEN if it is impossible to say what the writer thinks about this"],
        questions=[
            _q(27, yn, "Schools have been too slow to respond to research on sleep.", "YES"),
            _q(28, yn, "Sleep was correctly understood in the twentieth century.", "NO"),
            _q(29, yn, "Rats sleep for longer after learning a maze.", "NOT GIVEN"),
            _q(30, yn, "Sleep makes people more intelligent.", "NO"),
            _q(31, yn, "Most students prefer to revise late at night.", "NOT GIVEN"),
        ],
    )
    sm = QT.COMPLETION
    g2 = QuestionGroup(
        type=sm, completion_form=CompletionForm.SUMMARY, range=(32, 35),
        instructions=["Complete the summary below.",
                      "Choose ONE WORD ONLY from the passage for each answer."],
        word_limit=WordLimit(max_words=1, raw="ONE WORD ONLY"),
        list_title="How sleep supports memory",
        body=["During deep sleep, the brain seems to {32} activity patterns from the day. In rats, cells in the "
              "{33} fired in the same order as during the maze task. This process may move information into the "
              "{34}, where it is stored for the long term. In human studies, the benefit of sleep was greatest "
              "for {35} material."],
        questions=[_q(32, sm, "", "replay"), _q(33, sm, "", "hippocampus"), _q(34, sm, "", "cortex"),
                   _q(35, sm, "", "difficult")],
    )
    se = QT.MATCHING_SENTENCE_ENDINGS
    g3 = QuestionGroup(
        type=se, range=(36, 38),
        instructions=["Complete each sentence with the correct ending, A-E, below."],
        shared_options=_opts("were more likely to find a hidden shortcut.", "became more intelligent over time.",
                             "recalled more pairs the next morning.",
                             "may remember less than students who sleep well.",
                             "preferred to study in the afternoon."),
        questions=[
            _q(36, se, "Volunteers who slept after learning word pairs", "C"),
            _q(37, se, "Volunteers who slept between puzzle attempts", "A"),
            _q(38, se, "Students who study late at night instead of sleeping", "D"),
        ],
    )
    sa = QT.SHORT_ANSWER
    g4 = QuestionGroup(
        type=sa, range=(39, 40),
        instructions=["Answer the questions below.",
                      "Choose NO MORE THAN THREE WORDS from the passage for each answer."],
        word_limit=WordLimit(max_words=3, raw="NO MORE THAN THREE WORDS"),
        questions=[
            _q(39, sa, "Which animals were used in the maze experiments?", "rats"),
            _q(40, sa, "What can improve recall, although less than a full night's sleep?",
               "short daytime nap", "daytime nap", "nap"),
        ],
    )
    return ReadingSection(passage=p, groups=[g1, g2, g3, g4])


def sample_test() -> IELTSReadingTest:
    return IELTSReadingTest(title="Osamu Dazai Practice Test 1 — Academic Reading",
                            sections=[passage_1(), passage_2(), passage_3()])
