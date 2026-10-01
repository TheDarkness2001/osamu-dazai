"""Learning-graph algorithms (spec §8). Pure functions, no AI.

The concept graph is a DAG: an edge p → c means "p is a prerequisite of c".
"""

from __future__ import annotations

import re
from collections import defaultdict

from osamu_dazai.domain.common import Severity
from osamu_dazai.domain.graph import Concept, ConceptGraph
from osamu_dazai.domain.validation import Location, ValidationIssue

E, W = Severity.ERROR, Severity.WARNING


def find_cycle(graph: ConceptGraph) -> list[str] | None:
    """One prerequisite cycle as [a, b, …, a], or None if the graph is acyclic."""
    deps = {c.id: c.prerequisites for c in graph.concepts}
    WHITE, GREY, BLACK = 0, 1, 2
    color = dict.fromkeys(deps, WHITE)
    stack: list[str] = []

    def visit(n: str) -> list[str] | None:
        color[n] = GREY
        stack.append(n)
        for p in deps[n]:
            if color[p] == GREY:
                return stack[stack.index(p):] + [p]
            if color[p] == WHITE and (cyc := visit(p)):
                return cyc
        stack.pop()
        color[n] = BLACK
        return None

    for n in deps:
        if color[n] == WHITE and (cyc := visit(n)):
            return list(reversed(cyc))
    return None


def topological_order(graph: ConceptGraph) -> list[str]:
    """Prerequisites first; ties keep the graph's own order. Raises on cycles."""
    if (cyc := find_cycle(graph)) is not None:
        raise ValueError(f"cycle: {' → '.join(cyc)}")
    pos = {c.id: i for i, c in enumerate(graph.concepts)}
    indeg = {c.id: len(set(c.prerequisites)) for c in graph.concepts}
    dependents: dict[str, list[str]] = defaultdict(list)
    for c in graph.concepts:
        for p in set(c.prerequisites):
            dependents[p].append(c.id)
    ready = sorted((n for n, d in indeg.items() if d == 0), key=pos.__getitem__)
    out: list[str] = []
    while ready:
        n = ready.pop(0)
        out.append(n)
        for d in dependents[n]:
            indeg[d] -= 1
            if indeg[d] == 0:
                ready.append(d)
                ready.sort(key=pos.__getitem__)
    return out


def depth(graph: ConceptGraph) -> dict[str, int]:
    """Longest prerequisite chain below each concept (foundations = 0)."""
    by = graph.by_id()
    memo: dict[str, int] = {}

    def d(n: str) -> int:
        if n not in memo:
            memo[n] = 1 + max((d(p) for p in by[n].prerequisites), default=-1)
        return memo[n]

    return {c.id: d(c.id) for c in graph.concepts}


def _norm(name: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", name.lower()).split())


def _similar(a: str, b: str) -> bool:
    A, B = _norm(a), _norm(b)
    if A == B or A.rstrip("s") == B.rstrip("s"):
        return True
    ta, tb = set(A.split()), set(B.split())
    return len(ta) > 1 and len(tb) > 1 and len(ta & tb) / len(ta | tb) >= 0.75


def validate_graph(graph: ConceptGraph) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    by = graph.by_id()

    def loc(c: Concept) -> Location:
        return Location(excerpt=f"{c.name} ({c.id})")

    if (cyc := find_cycle(graph)) is not None:
        names = " → ".join(by[n].name for n in cyc)
        issues.append(ValidationIssue(code="graph.cycle", severity=E, location=loc(by[cyc[0]]),
                                      problem=f"Prerequisite cycle: {names}",
                                      expected="a directed acyclic graph",
                                      suggestion="Remove one prerequisite link in the cycle"))
        return issues  # the remaining checks assume a DAG

    has_dependents = {p for c in graph.concepts for p in c.prerequisites}
    if len(graph.concepts) > 1:
        for c in graph.concepts:
            if not c.prerequisites and c.id not in has_dependents:
                issues.append(ValidationIssue(code="graph.isolated", severity=W, location=loc(c),
                                              problem=f"'{c.name}' is not connected to any other concept",
                                              suggestion="Link it to a prerequisite or a dependent concept"))
    for c in graph.concepts:
        for p in c.prerequisites:
            if by[p].difficulty > c.difficulty:
                issues.append(ValidationIssue(
                    code="graph.difficulty_inversion", severity=W, location=loc(c),
                    problem=f"'{c.name}' (difficulty {c.difficulty}) requires harder '{by[p].name}' "
                            f"(difficulty {by[p].difficulty})"))
        if len(set(c.prerequisites)) != len(c.prerequisites):
            issues.append(ValidationIssue(code="graph.duplicate_edge", severity=W, location=loc(c),
                                          problem=f"'{c.name}' lists the same prerequisite twice"))
    concepts = graph.concepts
    for i, a in enumerate(concepts):
        for b in concepts[i + 1:]:
            if _similar(a.name, b.name):
                issues.append(ValidationIssue(code="graph.duplicate_concept", severity=E, location=loc(b),
                                              problem=f"'{b.name}' duplicates '{a.name}'",
                                              suggestion="Merge the two concepts"))
    return issues


def prerequisite_violations(graph: ConceptGraph, introduced_at: dict[str, tuple[int, int]]) -> list[tuple[str, str]]:
    """(concept, prerequisite) pairs where the prerequisite is introduced later.

    ``introduced_at`` maps concept id → (lesson number, position within the
    lesson). A prerequisite introduced earlier in the same lesson is fine.
    """
    out = []
    for c in graph.concepts:
        if c.id not in introduced_at:
            continue
        for p in c.prerequisites:
            if p in introduced_at and introduced_at[p] >= introduced_at[c.id]:
                out.append((c.id, p))
    return out


def to_mermaid(graph: ConceptGraph) -> str:
    """Concept map as a Mermaid flowchart (prerequisite → dependent)."""
    ids = {c.id: f"c{i}" for i, c in enumerate(graph.concepts)}

    def label(s: str) -> str:
        return s.replace('"', "'")

    lines = ["flowchart TD"]
    lines += [f'    {ids[c.id]}["{label(c.name)}"]' for c in graph.concepts]
    lines += [f"    {ids[p]} --> {ids[c.id]}" for c in graph.concepts for p in c.prerequisites]
    return "\n".join(lines)
