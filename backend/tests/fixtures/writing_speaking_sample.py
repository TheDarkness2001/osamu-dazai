"""Original IELTS Writing / Speaking fixtures (written for Osamu Dazai's tests)."""

from __future__ import annotations

from osamu_dazai.ielts.bands import SPEAKING, WRITING_T1, WRITING_T2
from osamu_dazai.ielts.speaking import CueCard, GenAnswer, GenSpeaking, Part1Topic
from osamu_dazai.ielts.speaking import GenScore as SScore
from osamu_dazai.ielts.writing import GenSample, GenScore, GenTask1, GenTask2, GenWriting
from osamu_dazai.visuals.specs import SeriesD, VisualDraft

CHART = VisualDraft(
    visual_id="task1", kind="chart", chart_type="bar", title="How commuters travelled to work in Riverton (%)",
    caption="Share of commuters by transport mode, 2000-2020", alt_text="Bar chart of bus, car and bicycle shares",
    categories=["2000", "2010", "2020"],
    series=[SeriesD(name="Bus", values=[40, 35, 30]), SeriesD(name="Car", values=[45, 50, 48]),
            SeriesD(name="Bicycle", values=[15, 15, 22])],
    y_label="% of commuters", data_provenance="illustrative")

T1_75 = (
    "The bar chart compares the proportions of commuters in Riverton who travelled to work by bus, car and "
    "bicycle in 2000, 2010 and 2020. Overall, the car remained the most popular mode throughout the period, "
    "while the share of bus users declined steadily and cycling became noticeably more common in the final "
    "decade. In 2000, 45% of commuters drove, compared with 40% who took the bus and 15% who cycled. Over the "
    "next ten years, car use rose to a peak of 50%, whereas the figure for buses fell by 5 percentage points to "
    "35%. Cycling, by contrast, stayed unchanged at 15%. By 2020 the picture had shifted again. Driving dipped "
    "slightly to 48%, and bus travel continued its decline, reaching 30%, which was 10 points below its 2000 "
    "level. The most striking change was in cycling, which rose to 22%, the highest proportion recorded for "
    "this mode in the whole period. In summary, private cars dominated commuting, but there was a gradual "
    "move away from buses and a recent growth in cycling.")
T1_55 = (
    "The chart show how people go to work in Riverton in 2000, 2010 and 2020 by bus, car and bicycle. In 2000 "
    "the bus was 40% and the car was 45% and bicycle was 15%. In 2010 the car go up to 50% and the bus go down "
    "to 35%. The bicycle is same, 15%. In 2020 the car is 48% and bus is 30% and bicycle is 22%. So the car is "
    "always the most popular. The bus is going down every time and it is the biggest change because it lose "
    "10 percent. Bicycle is going up in the last year. I think many people like bicycle now because it is "
    "healthy and cheap and good for environment. In general the car is the highest and the bus is decreasing "
    "and the bicycle is increasing at the end. This information show that people change how they travel to "
    "work in this city over twenty years and the bicycle become more popular than before for many workers.")

T2_75 = " ".join([
    "Some people argue that cities should spend more money on cycle lanes than on new roads. I largely agree,",
    "because well-designed cycling infrastructure tends to reduce congestion, improve public health and make",
    "urban space fairer, although roads will always remain necessary for some purposes.",
    "To begin with, new roads rarely solve traffic problems for long. Extra lanes often encourage more people to",
    "drive, so within a few years the same queues return. Cycle lanes, by contrast, move far more people through",
    "the same amount of space, and every commuter who switches to a bicycle frees room for buses, deliveries and",
    "emergency vehicles that genuinely need the road.",
    "Moreover, the benefits extend beyond transport. Regular cycling builds exercise into daily routines, which",
    "can lower the risk of many common illnesses and reduce pressure on health services. Safer streets also",
    "allow children and older residents to travel independently, something that car-centred planning tends to",
    "ignore. In this sense, investment in cycling is also an investment in public health and social inclusion.",
    "Admittedly, cycling is not practical for everyone. People with disabilities, those who live far from their",
    "workplace and businesses that transport goods will still depend on roads. However, this is an argument for",
    "maintaining the existing network well, not for building ever more of it, and adapted bicycles and good",
    "connections to public transport can widen access considerably.",
    "In conclusion, while roads keep an essential role, I believe the balance of spending should shift towards",
    "cycle lanes, because they deliver lasting improvements to traffic, health and the quality of city life."])
T2_55 = " ".join([
    "Nowadays many people think government must spend more money for cycle lanes and not for new roads. In my",
    "opinion I agree with this idea but also roads are important and we need them.",
    "Firstly, cycle lanes are good for health. When people ride bicycle every day they do exercise and they",
    "become more healthy. Also the air in the city is more clean because there is less cars. For example in my",
    "city there is a lot of traffic and the air is very bad in the morning, so if people use bicycle it will be",
    "better for everybody and also for children.",
    "Secondly, bicycle is cheap. People do not need to buy petrol and they save money. Many students cannot buy",
    "a car so they need bicycle and safe lanes for go to university. If there is no lane it is dangerous because",
    "the cars are very fast and drivers do not look.",
    "On the other hand, roads are also necessary. Buses, taxis and trucks use roads and the shops need the",
    "trucks to bring products. Also some people live very far and they cannot ride bicycle for one hour every",
    "day, especially in winter when it is cold and raining. So government cannot stop to build roads completely",
    "because the economy need it.",
    "In conclusion, I think cycle lanes are very useful and government should spend more money on them, but",
    "they must also repair the old roads so everybody can travel. Both are important for the people in the",
    "city in the future."])


def scores(criteria: list[str], bands: list[int], cls=GenScore) -> list:
    return [cls(criterion=c, band=b, comment=f"{c}: clear evidence for this level in the response.")
            for c, b in zip(criteria, bands, strict=True)]


def writing_draft() -> GenWriting:
    def sample(band, text, crit, bands):
        return GenSample(target_band=band, text=text, scores=scores(crit, bands),
                         examiner_comment="A response typical of this band.",
                         strengths=["Clear overall structure"], improvements=["Vary sentence structures more"])

    return GenWriting(
        task1=GenTask1(prompt="The chart below shows the percentage of commuters in Riverton who travelled to work "
                              "by bus, car and bicycle in 2000, 2010 and 2020.", visual=CHART,
                       samples=[sample(7.5, T1_75, WRITING_T1, [7, 8, 7, 8]),
                                sample(5.5, T1_55, WRITING_T1, [5, 6, 5, 6])]),
        task2=GenTask2(task_type="opinion",
                       prompt="Some people believe cities should spend more on cycle lanes than on new roads. "
                              "To what extent do you agree or disagree?",
                       samples=[sample(7.5, T2_75, WRITING_T2, [8, 7, 8, 7]),
                                sample(5.5, T2_55, WRITING_T2, [6, 5, 6, 5])]))


P1_ANSWER = ("I'm from Samarkand, which is a historic city in the centre of Uzbekistan. What I like most is the "
             "atmosphere in the old town in the evening, when families walk around the squares.")
P2_ANSWER = " ".join(["I'd like to describe a teacher who really influenced me, my maths teacher at secondary school,",
                      "Mrs Karimova. She taught me for three years, from when I was about thirteen until I was",
                      "sixteen, and I still remember her lessons quite vividly. She wasn't the kind of teacher who",
                      "just wrote formulas on the board. Instead, she started almost every lesson with a puzzle",
                      "from everyday life, like working out the cheapest mobile phone plan or planning a school",
                      "trip on a budget. At first a lot of us found it strange, but gradually we realised that",
                      "maths was actually a way of thinking rather than a list of rules. What made her special,",
                      "though, was how patient she was. If someone made a mistake, she would ask them to explain",
                      "their reasoning, and quite often the mistake turned out to be an interesting idea that the",
                      "whole class could learn from. I was quite shy back then, so that approach made a huge",
                      "difference to my confidence. The reason she influenced me so much is that she changed how I",
                      "deal with problems in general. Even now, when I face something difficult at work, I try to",
                      "break it into smaller parts, the way she taught us, and I'm not afraid of getting it wrong",
                      "the first time. I think that's probably the most valuable thing a teacher can give you."])
P3_ANSWER = ("I think it's a mixture of personality and training. Some people are naturally good at explaining "
             "things, but the best teachers I've met also work very hard at understanding why students get "
             "stuck. Patience matters a lot, and so does being able to make a subject feel relevant, because "
             "students learn much more when they can see why something is useful in real life.")


def speaking_draft() -> GenSpeaking:
    pron = "Pronunciation: listen for clear word stress and natural intonation when the answer is spoken aloud."

    def sc(bands):
        out = scores(SPEAKING, bands, cls=SScore)
        out[3] = SScore(criterion="Pronunciation", band=bands[3], comment=pron)
        return out

    part1 = [Part1Topic(topic="Home town", questions=["Where are you from?", "What do you like about your home town?",
                                                       "Has your home town changed in recent years?"]),
             Part1Topic(topic="Free time", questions=["What do you do in your free time?",
                                                       "Do you prefer spending free time alone or with others?",
                                                       "Is there a hobby you would like to try?"])]
    card = CueCard(task="Describe a teacher who has influenced you.",
                   prompts=["who this teacher was", "what subject they taught", "what their lessons were like"],
                   explain="and explain why this teacher influenced you.",
                   rounding_off=["Do you still keep in touch with this teacher?"])
    part3 = ["What makes someone a good teacher?", "Should teachers be paid more than they are now?",
             "How has technology changed the way teachers work?", "Will teachers ever be replaced by computers?"]
    return GenSpeaking(part1=part1, part2=card, part3=part3, model_answers=[
        GenAnswer(part=1, question="Where are you from?", target_band=7, answer=P1_ANSWER, scores=sc([7, 7, 7, 7])),
        GenAnswer(part=1, question="What do you like about your home town?", target_band=7, answer=P1_ANSWER,
                  scores=sc([7, 7, 7, 7])),
        GenAnswer(part=2, question="Describe a teacher who has influenced you.", target_band=7, answer=P2_ANSWER,
                  scores=sc([7, 7, 7, 7])),
        GenAnswer(part=3, question="What makes someone a good teacher?", target_band=7, answer=P3_ANSWER,
                  scores=sc([7, 8, 7, 7])),
        GenAnswer(part=3, question="Should teachers be paid more than they are now?", target_band=7, answer=P3_ANSWER,
                  scores=sc([7, 7, 7, 7])),
    ])
