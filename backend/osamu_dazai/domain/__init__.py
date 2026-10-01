"""Osamu Dazai domain schemas (Phase 3). Pure data + invariants; no I/O."""

from osamu_dazai.domain.common import (
    BloomLevel,
    Entity,
    Lang,
    LanguageSettings,
    Model,
    Provenance,
    ReviewStatus,
    Severity,
    new_id,
)
from osamu_dazai.domain.content import Block, Chapter, GlossaryEntry, Section, SectionKind, StudentBook
from osamu_dazai.domain.curriculum import Course, LearningObjective, Lesson, Module
from osamu_dazai.domain.documents import (
    Document,
    DocumentKind,
    DocumentVersion,
    ExportFormat,
    GenerationJob,
    JobStatus,
    ValidationStatus,
)
from osamu_dazai.domain.graph import Concept, ConceptGraph
from osamu_dazai.domain.knowledge import KnowledgeBase, Term
from osamu_dazai.domain.project import CourseBrief, Project, ProjectKind, Schedule
from osamu_dazai.domain.questions import (
    Answer,
    Assessment,
    AssessmentKind,
    Option,
    Question,
    QuestionGroup,
    QuestionType,
    Rubric,
    WordLimit,
)
from osamu_dazai.domain.sources import Source, SourceKind, VerificationMethod
from osamu_dazai.domain.teacher import TeacherGuide, TeacherLesson
from osamu_dazai.domain.validation import Location, ValidationIssue, ValidationResult
from osamu_dazai.domain.visuals import Image, Visual, VisualSpec

# Top-level entities persisted by the generic entity store, keyed by type name.
# (Project, Document and DocumentVersion have dedicated tables.)
ENTITY_TYPES: dict[str, type[Entity]] = {
    cls.__name__: cls
    for cls in (
        Course,
        ConceptGraph,
        StudentBook,
        TeacherGuide,
        Assessment,
        KnowledgeBase,
        Visual,
        Image,
        Source,
        ValidationResult,
        GenerationJob,
    )
}

__all__ = [
    "ENTITY_TYPES",
    "Answer",
    "Assessment",
    "AssessmentKind",
    "BloomLevel",
    "Block",
    "Chapter",
    "Concept",
    "ConceptGraph",
    "Course",
    "CourseBrief",
    "Document",
    "DocumentKind",
    "DocumentVersion",
    "Entity",
    "ExportFormat",
    "GenerationJob",
    "GlossaryEntry",
    "Image",
    "JobStatus",
    "KnowledgeBase",
    "Lang",
    "LanguageSettings",
    "LearningObjective",
    "Lesson",
    "Location",
    "Model",
    "Module",
    "Option",
    "Project",
    "ProjectKind",
    "Provenance",
    "Question",
    "QuestionGroup",
    "QuestionType",
    "ReviewStatus",
    "Rubric",
    "Schedule",
    "Section",
    "SectionKind",
    "Severity",
    "Source",
    "SourceKind",
    "StudentBook",
    "TeacherGuide",
    "TeacherLesson",
    "Term",
    "ValidationIssue",
    "ValidationResult",
    "ValidationStatus",
    "VerificationMethod",
    "Visual",
    "VisualSpec",
    "WordLimit",
    "new_id",
]
