"""Documents, their versions, and generation jobs (spec §37–38)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from osamu_dazai.domain.common import Entity, Model, ReviewStatus, id_field, utcnow


class DocumentKind(StrEnum):
    STUDENT_BOOK = "student_book"
    TEACHER_GUIDE = "teacher_guide"
    CURRICULUM = "curriculum"
    ASSESSMENT = "assessment"
    IELTS_TEST = "ielts_test"
    IMPORTED = "imported"
    OTHER = "other"


class ExportFormat(StrEnum):
    DOCX = "docx"
    PDF = "pdf"
    HTML = "html"
    MARKDOWN = "md"
    JSON = "json"


class ValidationStatus(StrEnum):
    NOT_RUN = "not_run"
    PASSED = "passed"
    WARNINGS = "warnings"
    FAILED = "failed"


class Document(Entity):
    """A versioned, reviewable deliverable. Its content lives in DocumentVersion snapshots."""

    ID_PREFIX = "doc"
    id: str = id_field(ID_PREFIX)
    project_id: str
    kind: DocumentKind
    title: str
    subject_entity_id: str | None = None  # the StudentBook / Assessment / ... it renders
    status: ReviewStatus = ReviewStatus.DRAFT
    current_version: int = 0


class DocumentVersion(Model):
    """Immutable snapshot. Restoring creates a *new* version (history is append-only)."""

    document_id: str
    document_version: int = Field(gt=0)
    created_at: datetime = Field(default_factory=utcnow)
    changed_by: str  # user id, or "ai:<stage>"
    change_note: str = ""
    generation_model: str | None = None
    generation_prompt_version: str | None = None
    source_version: int | None = None  # version this one was derived/restored from
    validation_status: ValidationStatus = ValidationStatus.NOT_RUN
    content_hash: str
    snapshot: dict[str, Any]


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class LLMCallRecord(Model):
    provider: str
    model: str
    prompt_version: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0


class GenerationJob(Entity):
    ID_PREFIX = "job"
    id: str = id_field(ID_PREFIX)
    project_id: str
    stage: str  # e.g. "curriculum_architect"
    status: JobStatus = JobStatus.QUEUED
    input_ref: str | None = None
    output_ref: str | None = None
    calls: list[LLMCallRecord] = Field(default_factory=list)
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
