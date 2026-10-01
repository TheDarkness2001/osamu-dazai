import pytest

from osamu_dazai.domain.graph import Concept, ConceptGraph
from osamu_dazai.graph import depth, find_cycle, prerequisite_violations, to_mermaid, topological_order, validate_graph


def g(*specs) -> ConceptGraph:
    """specs: (id, name, prerequisites[, difficulty])"""
    return ConceptGraph(course_id="c", concepts=[
        Concept(id=s[0], name=s[1], prerequisites=list(s[2]), difficulty=s[3] if len(s) > 3 else 1) for s in specs])


CHAIN = g(("var", "Variables", []), ("type", "Data types", ["var"]), ("loop", "Loops", ["type"]),
          ("func", "Functions", ["type"]), ("proj", "Project", ["loop", "func"]))


def test_acyclic_order_and_depth():
    assert find_cycle(CHAIN) is None
    order = topological_order(CHAIN)
    assert order.index("var") < order.index("type") < order.index("loop") < order.index("proj")
    assert depth(CHAIN) == {"var": 0, "type": 1, "loop": 2, "func": 2, "proj": 3}


def test_cycle_detected_and_named():
    cyc = g(("a", "A", ["c"]), ("b", "B", ["a"]), ("c", "C", ["b"]))
    found = find_cycle(cyc)
    assert found[0] == found[-1] and set(found) == {"a", "b", "c"}
    with pytest.raises(ValueError, match="cycle"):
        topological_order(cyc)
    issue = validate_graph(cyc)[0]
    assert issue.code == "graph.cycle" and "→" in issue.problem


def test_quality_warnings():
    graph = g(("var", "Variables", [], 3), ("vars", "variable", []), ("loop", "Loops", ["var"], 1),
              ("lonely", "Recursion", []))
    codes = {i.code for i in validate_graph(graph)}
    assert {"graph.duplicate_concept", "graph.difficulty_inversion", "graph.isolated"} <= codes


def test_prerequisite_violations():
    introduced = {"var": (1, 0), "type": (1, 1), "loop": (2, 0), "func": (4, 0), "proj": (3, 0)}
    assert prerequisite_violations(CHAIN, introduced) == [("proj", "func")]
    same_lesson_wrong_order = {**introduced, "var": (1, 1), "type": (1, 0)}
    assert ("type", "var") in prerequisite_violations(CHAIN, same_lesson_wrong_order)


def test_mermaid():
    text = to_mermaid(CHAIN)
    assert text.startswith("flowchart TD") and 'c0["Variables"]' in text and "c0 --> c1" in text
