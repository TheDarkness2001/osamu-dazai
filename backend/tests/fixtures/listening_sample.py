"""Original IELTS Listening fixture (written for Osamu Dazai's tests): 4 parts, 20 questions."""

from __future__ import annotations

from osamu_dazai.ielts.listening import GenGroup, GenItem, GenPart, GenPlanItem, GenTurn, LGroupSpec, PartSpec

PLAN = [
    PartSpec(1, "joining a sports centre", True, (LGroupSpec("form", 4, "ONE WORD AND/OR A NUMBER"),
                                                 LGroupSpec("note", 2, "ONE WORD AND/OR A NUMBER")), words=(80, 2000)),
    PartSpec(2, "a guide at a country park", False, (LGroupSpec("mc", 2, options=3),
                                                     LGroupSpec("map", 3, options=5)), words=(80, 2000)),
    PartSpec(3, "two students planning a project", True, (LGroupSpec("mc", 2, options=3),
                                                          LGroupSpec("matching", 3, options=4)), words=(80, 2000)),
    PartSpec(4, "a lecture on urban bees", False, (LGroupSpec("note", 4, "ONE WORD ONLY"),), words=(80, 2000)),
]


def T(speaker: str, text: str) -> GenTurn:
    return GenTurn(speaker=speaker, text=text)


def part1() -> GenPart:
    R, C = "Receptionist", "Daniel"
    return GenPart(
        context="A telephone conversation between a sports centre receptionist and a caller.",
        speakers=[R, C],
        transcript=[
            T(R, "Good morning, Riverside Sports Centre. How can I help?"),
            T(C, "Hi, I'd like to become a member. Could you take my details?"),
            T(R, "Of course. What's your surname?"),
            T(C, "It's Harper. That's H-A-R-P-E-R."),
            T(R, "And your address?"),
            T(C, "I live at 12 Ferndale Road. Sorry, not Fernhill — Ferndale."),
            T(R, "Lovely. And a contact number?"),
            T(C, "My mobile is 07791234567."),
            T(R, "What will you mainly use the centre for?"),
            T(C, "I thought tennis at first, but actually mostly swimming."),
            T(R, "Great. A couple of things to note. Please bring a photo for your membership card, and parking is "
                 "free after 6pm."),
            T(C, "Perfect, thank you."),
        ],
        groups=[
            GenGroup(title="Riverside Sports Centre — Membership form", lines=[
                "Surname: {1}", "Address: 12 {2} Road", "Mobile: {3}", "Main activity: {4}"],
                items=[GenItem(answers=["Harper"]), GenItem(answers=["Ferndale"]),
                       GenItem(answers=["07791234567"]), GenItem(answers=["swimming"])]),
            GenGroup(title="Notes", lines=["Bring a {1} for the card", "Parking is free after {2}"],
                     items=[GenItem(answers=["photo"]), GenItem(answers=["6pm"])]),
        ])


def part2() -> GenPart:
    G = "Guide"
    return GenPart(
        context="A guide welcoming visitors to a country park.",
        speakers=[G],
        transcript=[T(G, (
            "Welcome to Oakfield Country Park. The park first opened to the public in 1985, although the woodland "
            "itself is much older. Most visitors come for the lake, but our wildlife survey shows the meadow has the "
            "greatest variety of birds. Now, let me show you around the map. As you come through the main gate, the "
            "café is immediately on your left. The toilets are next to the car park, opposite the café. If you "
            "follow the path towards the lake, you'll find the boat hire right at the water's edge. Enjoy your day."))],
        groups=[
            GenGroup(items=[
                GenItem(stem="When did the park open to the public?", options=["1958", "1985", "1995"],
                        answers=["B"], evidence="opened to the public in 1985"),
                GenItem(stem="Where are the most kinds of birds found?", options=["the lake", "the woodland",
                                                                                   "the meadow"],
                        answers=["C"], evidence="the meadow has the greatest variety of birds"),
            ]),
            GenGroup(items=[
                GenItem(stem="Café", answers=["A"], evidence="the café is immediately on your left"),
                GenItem(stem="Toilets", answers=["D"], evidence="the toilets are next to the car park"),
                GenItem(stem="Boat hire", answers=["E"], evidence="the boat hire right at the water's edge"),
            ]),
        ],
        plan_title="Oakfield Country Park",
        plan=[GenPlanItem(label="Main gate", x=0, y=10, w=3, h=2), GenPlanItem(label="A", x=0, y=7, w=3, h=2),
              GenPlanItem(label="B", x=4, y=7, w=2, h=2), GenPlanItem(label="Car park", x=7, y=9, w=5, h=3),
              GenPlanItem(label="C", x=4, y=3, w=2, h=2), GenPlanItem(label="D", x=7, y=6, w=2, h=2),
              GenPlanItem(label="Lake", x=6, y=0, w=6, h=4), GenPlanItem(label="E", x=10, y=4, w=2, h=2)],
    )


def part3() -> GenPart:
    A, B = "Amira", "Tom"
    return GenPart(
        context="Two students, Amira and Tom, planning a research project on city transport.",
        speakers=[A, B],
        transcript=[
            T(A, "So, Tom, should we focus on buses or on cycling for our project?"),
            T(B, "Buses have more data, but I think cycling is more interesting, so let's choose cycling."),
            T(A, "Agreed. And the deadline is the end of May, isn't it?"),
            T(B, "No, they moved it — it's now the middle of June."),
            T(A, "Good. What about sources? The council report seemed a bit out of date."),
            T(B, "True. The university survey is recent and very detailed, though."),
            T(A, "And the newspaper articles were useful for quotations but not for numbers."),
        ],
        groups=[
            GenGroup(items=[
                GenItem(stem="What will the students study?", options=["buses", "cycling", "trains"], answers=["B"],
                        evidence="let's choose cycling"),
                GenItem(stem="When is the project deadline?", options=["the end of May", "the middle of June",
                                                                        "the end of June"],
                        answers=["B"], evidence="it's now the middle of June"),
            ]),
            GenGroup(shared_options=["out of date", "recent and detailed", "good for quotations", "too expensive"],
                     items=[
                         GenItem(stem="the council report", answers=["A"], evidence="the council report seemed a bit "
                                                                                    "out of date"),
                         GenItem(stem="the university survey", answers=["B"],
                                 evidence="the university survey is recent and very detailed"),
                         GenItem(stem="the newspaper articles", answers=["C"],
                                 evidence="the newspaper articles were useful for quotations"),
                     ]),
        ])


def part4() -> GenPart:
    L = "Lecturer"
    return GenPart(
        context="Part of a lecture about bees in cities.",
        speakers=[L],
        transcript=[T(L, (
            "Good afternoon, everyone. Today I want to look at bees in cities, a topic that has attracted a lot of "
            "public attention in recent years. City gardens often contain a wider range of flowers than "
            "farmland, which gives bees a varied diet. However, managed hives can compete with wild bees for "
            "pollen. Disease is another concern, especially a parasite called varroa, which spreads quickly between "
            "crowded hives. For this reason, many cities now encourage planting rather than beekeeping. Next week "
            "we will compare these city policies in more detail."))],
        groups=[GenGroup(title="Bees in cities", lines=[
            "Gardens offer bees a varied {1}", "Managed hives compete with wild bees for {2}",
            "A parasite called {3} spreads between crowded hives", "Cities now encourage {4} rather than beekeeping"],
            items=[GenItem(answers=["diet"]), GenItem(answers=["pollen"]), GenItem(answers=["varroa"]),
                   GenItem(answers=["planting"])])])


def parts() -> list[GenPart]:
    return [part1(), part2(), part3(), part4()]
