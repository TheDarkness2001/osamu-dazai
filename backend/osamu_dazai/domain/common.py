"""Shared vocabulary for all domain models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


def new_id(prefix: str) -> str:
    """Readable, globally unique id, e.g. ``con_3f9a1c0b7d2e4a51``."""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def utcnow() -> datetime:
    return datetime.now(UTC)


class Model(BaseModel):
    """Base for every domain model: strict about unknown fields, JSON-friendly."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, use_enum_values=False)


class Lang(StrEnum):
    """Content languages. Extend freely; nothing is hard-coded to one language."""

    EN = "en"
    UZ = "uz"  # Uzbek (Latin script)
    UZ_CYRL = "uz-Cyrl"
    RU = "ru"


class LanguageSettings(Model):
    """Explanation, terminology and assessment languages are independent (spec §43)."""

    explanation: Lang = Lang.EN
    terminology: Lang = Lang.EN
    assessment: Lang = Lang.EN


class Provenance(StrEnum):
    """Where a piece of content came from (spec §44)."""

    SOURCE_BACKED = "source_backed"
    AI_GENERATED = "ai_generated"
    TEACHER_AUTHORED = "teacher_authored"
    USER_PROVIDED = "user_provided"
    IMPORTED = "imported"


class ReviewStatus(StrEnum):
    """Human-review workflow (spec §39)."""

    DRAFT = "draft"
    AI_VALIDATED = "ai_validated"
    IN_REVIEW = "in_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    PUBLISHED = "published"


class BloomLevel(StrEnum):
    """Bloom's taxonomy, 2001 revision."""

    REMEMBER = "remember"
    UNDERSTAND = "understand"
    APPLY = "apply"
    ANALYZE = "analyze"
    EVALUATE = "evaluate"
    CREATE = "create"


class Severity(StrEnum):
    ERROR = "error"  # blocks export
    WARNING = "warning"
    INFO = "info"


def id_field(prefix: str):  # noqa: ANN201 - returns a pydantic FieldInfo
    """Field with an auto-generated prefixed id."""
    return Field(default_factory=lambda: new_id(prefix))


class Entity(Model):
    """Base for persisted entities: identity, timestamps, provenance, review status.

    Subclasses set ``ID_PREFIX`` and redeclare ``id = id_field(ID_PREFIX)``.
    """

    ID_PREFIX: ClassVar[str] = "ent"

    id: str
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
