"""Repositories: projects, generic entities, and versioned documents."""

from __future__ import annotations

import hashlib
import json
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from osamu_dazai.domain import ENTITY_TYPES, Document, DocumentVersion, Entity, Project
from osamu_dazai.domain.common import utcnow
from osamu_dazai.domain.documents import ValidationStatus
from osamu_dazai.storage.orm import DocumentRow, DocumentVersionRow, EntityRow, ProjectRow

E = TypeVar("E", bound=Entity)

_PARENT_FIELDS = ("course_id", "student_book_id", "chapter_id", "target_id")


class NotFound(LookupError):
    pass


def content_hash(snapshot: dict[str, Any]) -> str:
    canonical = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ProjectRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def save(self, project: Project) -> Project:
        project.updated_at = utcnow()
        row = self.s.get(ProjectRow, project.id) or ProjectRow(id=project.id, created_at=project.created_at)
        row.name, row.kind, row.status = project.name, project.kind.value, project.status.value
        row.payload = project.model_dump(mode="json")
        row.updated_at = project.updated_at
        self.s.add(row)
        self.s.flush()
        return project

    def get(self, project_id: str) -> Project:
        row = self.s.get(ProjectRow, project_id)
        if row is None:
            raise NotFound(f"project {project_id}")
        return Project.model_validate(row.payload)

    def list(self) -> list[Project]:
        rows = self.s.scalars(select(ProjectRow).order_by(ProjectRow.created_at))
        return [Project.model_validate(r.payload) for r in rows]


class EntityRepository:
    """Stores any registered domain entity as validated JSON."""

    def __init__(self, session: Session) -> None:
        self.s = session

    @staticmethod
    def _type_name(cls: type[Entity]) -> str:
        name = cls.__name__
        if ENTITY_TYPES.get(name) is not cls:
            raise TypeError(f"{name} is not a registered entity type")
        return name

    def save(self, entity: Entity, project_id: str) -> Entity:
        type_name = self._type_name(type(entity))
        entity.updated_at = utcnow()
        parent = next((getattr(entity, f) for f in _PARENT_FIELDS if getattr(entity, f, None)), None)
        status = getattr(entity, "status", None)
        row = self.s.get(EntityRow, entity.id)
        if row is None:
            row = EntityRow(id=entity.id, created_at=entity.created_at)
        elif row.entity_type != type_name or row.project_id != project_id:
            raise ValueError(f"entity id {entity.id} already used by another type/project")
        row.project_id, row.entity_type, row.parent_id = project_id, type_name, parent
        row.status = status.value if status is not None else None
        row.payload = entity.model_dump(mode="json")
        row.updated_at = entity.updated_at
        self.s.add(row)
        self.s.flush()
        return entity

    def get(self, cls: type[E], entity_id: str) -> E:
        row = self.s.get(EntityRow, entity_id)
        if row is None or row.entity_type != self._type_name(cls):
            raise NotFound(f"{cls.__name__} {entity_id}")
        return cls.model_validate(row.payload)

    def list(self, cls: type[E], project_id: str, parent_id: str | None = None) -> list[E]:
        q = select(EntityRow).where(
            EntityRow.project_id == project_id, EntityRow.entity_type == self._type_name(cls)
        )
        if parent_id is not None:
            q = q.where(EntityRow.parent_id == parent_id)
        return [cls.model_validate(r.payload) for r in self.s.scalars(q.order_by(EntityRow.created_at))]

    def delete(self, cls: type[E], entity_id: str) -> None:
        row = self.s.get(EntityRow, entity_id)
        if row is None or row.entity_type != self._type_name(cls):
            raise NotFound(f"{cls.__name__} {entity_id}")
        self.s.delete(row)
        self.s.flush()


class DocumentRepository:
    """Documents with append-only version history (spec §38)."""

    def __init__(self, session: Session) -> None:
        self.s = session

    # ---- documents -------------------------------------------------------
    def create(self, doc: Document) -> Document:
        if self.s.get(DocumentRow, doc.id) is not None:
            raise ValueError(f"document {doc.id} already exists")
        self.s.add(
            DocumentRow(
                id=doc.id,
                project_id=doc.project_id,
                kind=doc.kind.value,
                title=doc.title,
                subject_entity_id=doc.subject_entity_id,
                status=doc.status.value,
                current_version=doc.current_version,
                created_at=doc.created_at,
                updated_at=doc.updated_at,
            )
        )
        self.s.flush()
        return doc

    def _row(self, document_id: str) -> DocumentRow:
        row = self.s.get(DocumentRow, document_id)
        if row is None:
            raise NotFound(f"document {document_id}")
        return row

    def get(self, document_id: str) -> Document:
        r = self._row(document_id)
        return Document(
            id=r.id,
            project_id=r.project_id,
            kind=r.kind,
            title=r.title,
            subject_entity_id=r.subject_entity_id,
            status=r.status,
            current_version=r.current_version,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )

    def set_status(self, document_id: str, status: str) -> None:
        row = self._row(document_id)
        row.status = status
        row.updated_at = utcnow()
        self.s.flush()

    # ---- versions --------------------------------------------------------
    def commit(
        self,
        document_id: str,
        snapshot: dict[str, Any],
        *,
        changed_by: str,
        change_note: str = "",
        generation_model: str | None = None,
        generation_prompt_version: str | None = None,
        source_version: int | None = None,
        validation_status: ValidationStatus = ValidationStatus.NOT_RUN,
        allow_identical: bool = False,
    ) -> DocumentVersion:
        """Append a new version. Identical content returns the current version unless forced."""
        row = self._row(document_id)
        digest = content_hash(snapshot)
        if row.current_version and not allow_identical:
            current = self.version(document_id, row.current_version)
            if current.content_hash == digest:
                return current
        ver = DocumentVersion(
            document_id=document_id,
            document_version=row.current_version + 1,
            changed_by=changed_by,
            change_note=change_note,
            generation_model=generation_model,
            generation_prompt_version=generation_prompt_version,
            source_version=source_version if source_version is not None else (row.current_version or None),
            validation_status=validation_status,
            content_hash=digest,
            snapshot=snapshot,
        )
        self.s.add(DocumentVersionRow(**ver.model_dump(mode="python")))
        row.current_version = ver.document_version
        row.updated_at = ver.created_at
        self.s.flush()
        return ver

    def version(self, document_id: str, number: int) -> DocumentVersion:
        row = self.s.scalar(
            select(DocumentVersionRow).where(
                DocumentVersionRow.document_id == document_id,
                DocumentVersionRow.document_version == number,
            )
        )
        if row is None:
            raise NotFound(f"document {document_id} version {number}")
        return _version_from_row(row)

    def latest(self, document_id: str) -> DocumentVersion:
        return self.version(document_id, self._row(document_id).current_version)

    def history(self, document_id: str) -> list[DocumentVersion]:
        rows = self.s.scalars(
            select(DocumentVersionRow)
            .where(DocumentVersionRow.document_id == document_id)
            .order_by(DocumentVersionRow.document_version)
        )
        return [_version_from_row(r) for r in rows]

    def set_validation_status(self, document_id: str, number: int, status: ValidationStatus) -> None:
        row = self.s.scalar(
            select(DocumentVersionRow).where(
                DocumentVersionRow.document_id == document_id,
                DocumentVersionRow.document_version == number,
            )
        )
        if row is None:
            raise NotFound(f"document {document_id} version {number}")
        row.validation_status = status.value
        self.s.flush()

    def restore(self, document_id: str, number: int, *, changed_by: str) -> DocumentVersion:
        """Restore = new version copying an old snapshot. History is never rewritten."""
        old = self.version(document_id, number)
        return self.commit(
            document_id,
            old.snapshot,
            changed_by=changed_by,
            change_note=f"Restored from version {number}",
            generation_model=old.generation_model,
            generation_prompt_version=old.generation_prompt_version,
            source_version=number,
            allow_identical=True,
        )


def _version_from_row(r: DocumentVersionRow) -> DocumentVersion:
    return DocumentVersion(
        document_id=r.document_id,
        document_version=r.document_version,
        created_at=r.created_at,
        changed_by=r.changed_by,
        change_note=r.change_note,
        generation_model=r.generation_model,
        generation_prompt_version=r.generation_prompt_version,
        source_version=r.source_version,
        validation_status=r.validation_status,
        content_hash=r.content_hash,
        snapshot=r.snapshot,
    )
