"""Builders for well-formed planner / graph / curriculum drafts (what a good LLM would return)."""

from __future__ import annotations

from osamu_dazai.domain.common import BloomLevel
from osamu_dazai.pipeline.curriculum import (
    AssessmentDraft,
    ConceptDraft,
    CurriculumDraft,
    GraphDraft,
    LessonDraft,
    LessonObjectiveDraft,
    ModuleDraft,
    ObjectiveDraft,
)
from osamu_dazai.pipeline.planner import BriefDraft

REQUEST = "Create a beginner Python textbook for Uzbek teenagers."

# key, name, prerequisites, difficulty, group — in teaching order
PYTHON_CONCEPTS = [
    ("print_output", "Output with print()", [], 1, "basics"),
    ("variables", "Variables", ["print_output"], 1, "basics"),
    ("data_types", "Data types", ["variables"], 1, "basics"),
    ("user_input", "User input", ["variables"], 1, "basics"),
    ("arithmetic", "Arithmetic operators", ["data_types"], 1, "basics"),
    ("strings", "Strings", ["data_types"], 2, "basics"),
    ("type_conversion", "Type conversion", ["data_types", "user_input"], 2, "basics"),
    ("comparison", "Comparison operators", ["arithmetic"], 2, "control flow"),
    ("boolean_logic", "Boolean logic", ["comparison"], 2, "control flow"),
    ("conditions", "Conditions: if / elif / else", ["boolean_logic"], 2, "control flow"),
    ("while_loop", "While loops", ["conditions"], 2, "control flow"),
    ("for_loop", "For loops", ["conditions"], 3, "control flow"),
    ("range_function", "The range() function", ["for_loop"], 3, "control flow"),
    ("lists", "Lists", ["for_loop"], 3, "data structures"),
    ("list_methods", "List methods", ["lists"], 3, "data structures"),
    ("tuples", "Tuples", ["lists"], 3, "data structures"),
    ("dictionaries", "Dictionaries", ["lists"], 3, "data structures"),
    ("functions", "Functions", ["conditions"], 3, "functions"),
    ("parameters", "Parameters and return values", ["functions"], 3, "functions"),
    ("scope", "Variable scope", ["parameters"], 4, "functions"),
    ("modules", "Modules and imports", ["functions"], 3, "functions"),
    ("error_handling", "Error handling", ["conditions", "functions"], 4, "robust programs"),
    ("files", "Reading and writing files", ["strings", "error_handling"], 4, "robust programs"),
    ("program_design", "Designing a program", ["functions", "lists", "dictionaries"], 4, "projects"),
]

COURSE_OBJECTIVES = [
    ("write_programs", "Write short Python programs that solve everyday problems", BloomLevel.APPLY, "write"),
    ("explain_code", "Explain what a given Python program does, line by line", BloomLevel.UNDERSTAND, "explain"),
    ("debug_code", "Find and fix errors in Python programs", BloomLevel.ANALYZE, "debug"),
    ("build_project", "Design and build a small project using functions and data structures",
     BloomLevel.CREATE, "design"),
]


def brief_draft(**over) -> BriefDraft:
    data = dict(subject="Python programming", level="beginner", age_min=13, age_max=16, duration_weeks=26,
                lessons_per_week=3, minutes_per_lesson=45, explanation_language="uz", terminology_language="en",
                assessment_language="uz", goal="Teach programming from zero", teaching_style="project-based",
                target_book_pages=220, outputs=["student_book", "teacher_guide", "exercises", "assessments"],
                questions_for_teacher=["Do students have their own computers?", "Which Python editor is used?"])
    data.update(over)
    return BriefDraft(**data)


def graph_draft(n: int = len(PYTHON_CONCEPTS)) -> GraphDraft:
    return GraphDraft(concepts=[
        ConceptDraft(key=k, name=name, description=f"{name} in Python", difficulty=d, prerequisites=pre, group=g)
        for k, name, pre, d, g in PYTHON_CONCEPTS[:n]])


def _module_kinds(per_module: int) -> list[str]:
    kinds: list[str] = []
    run = 0
    while len(kinds) < per_module - 1:
        if run == 6:
            kinds.append("review")
            run = 0
        else:
            kinds.append("teach")
            run += 1
    return [*kinds, "assessment"]


def curriculum_draft(n_concepts: int, modules: int, per_module: int) -> CurriculumDraft:
    keys = [c[0] for c in PYTHON_CONCEPTS[:n_concepts]]
    kinds = [k for _ in range(modules) for k in _module_kinds(per_module)]
    teach_positions = [i for i, k in enumerate(kinds) if k == "teach"]
    intro: dict[int, list[str]] = {}
    for ci, key in enumerate(keys):
        intro.setdefault(teach_positions[ci * len(teach_positions) // len(keys)], []).append(key)
    co_keys = [c[0] for c in COURSE_OBJECTIVES]
    mods, idx, teach_no = [], 0, 0
    for m in range(modules):
        lessons = []
        for _ in range(per_module):
            kind = kinds[idx]
            objs = []
            if kind == "teach":
                objs = [LessonObjectiveDraft(text=f"Write a program using {', '.join(intro.get(idx, ['earlier ideas']))}",
                                             bloom_level=BloomLevel.APPLY, verb="write",
                                             supports=[co_keys[teach_no % len(co_keys)]])]
                teach_no += 1
            lessons.append(LessonDraft(title=f"Lesson {idx + 1}", kind=kind, introduces=intro.get(idx, []),
                                       objectives=objs))
            idx += 1
        mods.append(ModuleDraft(title=f"Module {m + 1}", summary="…", lessons=lessons,
                                project_title=f"Mini project {m + 1}"))
    assessments = [AssessmentDraft(title=f"Module {m + 1} test", kind="quiz", after_lesson=(m + 1) * per_module,
                                   objectives=co_keys[: 2 + m % 3]) for m in range(modules)]
    assessments.append(AssessmentDraft(title="Final project", kind="project", after_lesson=modules * per_module,
                                       objectives=co_keys))
    return CurriculumDraft(
        title="Python dasturlash: noldan boshlab",
        course_objectives=[ObjectiveDraft(key=k, text=t, bloom_level=b, verb=v) for k, t, b, v in COURSE_OBJECTIVES],
        modules=mods, assessments=assessments)
