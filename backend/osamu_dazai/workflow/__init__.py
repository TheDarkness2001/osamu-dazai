"""Review workflow: draft → ai_validated → in_review → approved → published (spec §39).

The AI never approves or publishes. ``ai_validated`` requires a passing
validation result; ``approved`` and ``published`` require a human role.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.orm import Session

from osamu_dazai.domain import ReviewStatus, ValidationResult
from osamu_dazai.domain.common import utcnow
from osamu_dazai.storage.orm import ReviewEventRow

S = ReviewStatus


class Role(StrEnum):
    SYSTEM = "system"  # the AI pipeline
    AUTHOR = "author"
    EDITOR = "editor"
    REVIEWER = "reviewer"
    ADMIN = "admin"


HUMAN_ROLES = {Role.AUTHOR, Role.EDITOR, Role.REVIEWER, Role.ADMIN}
APPROVER_ROLES = {Role.REVIEWER, Role.ADMIN}

# (from, to) -> roles allowed to perform it
TRANSITIONS: dict[tuple[ReviewStatus, ReviewStatus], set[Role]] = {
    (S.DRAFT, S.AI_VALIDATED): {Role.SYSTEM, *HUMAN_ROLES},
    (S.AI_VALIDATED, S.IN_REVIEW): {Role.SYSTEM, *HUMAN_ROLES},
    (S.AI_VALIDATED, S.DRAFT): {Role.SYSTEM, *HUMAN_ROLES},  # content edited after validation
    (S.IN_REVIEW, S.APPROVED): APPROVER_ROLES,
    (S.IN_REVIEW, S.CHANGES_REQUESTED): {Role.EDITOR, *APPROVER_ROLES},
    (S.CHANGES_REQUESTED, S.DRAFT): {Role.SYSTEM, *HUMAN_ROLES},
    (S.APPROVED, S.PUBLISHED): APPROVER_ROLES,
    (S.APPROVED, S.DRAFT): {Role.EDITOR, *APPROVER_ROLES},  # reopen for edits
    (S.PUBLISHED, S.DRAFT): {Role.EDITOR, *APPROVER_ROLES},  # new edition
}


class TransitionError(ValueError):
    pass


@dataclass(frozen=True)
class Transition:
    from_status: ReviewStatus
    to_status: ReviewStatus
    actor: str
    role: Role
    note: str = ""


def check_transition(
    current: ReviewStatus,
    target: ReviewStatus,
    role: Role,
    validation: ValidationResult | None = None,
) -> None:
    allowed = TRANSITIONS.get((current, target))
    if allowed is None:
        raise TransitionError(f"cannot move from {current.value} to {target.value}")
    if role not in allowed:
        raise TransitionError(f"role {role.value} may not move {current.value} → {target.value}")
    if target is S.AI_VALIDATED:
        if validation is None:
            raise TransitionError("ai_validated requires a validation result")
        if not validation.passed:
            raise TransitionError(f"validation has {len(validation.errors)} blocking error(s)")


def transition(
    session: Session,
    target_id: str,
    current: ReviewStatus,
    target: ReviewStatus,
    *,
    actor: str,
    role: Role,
    validation: ValidationResult | None = None,
    note: str = "",
) -> Transition:
    """Validate a transition and record it in the audit trail. Caller updates the entity."""
    check_transition(current, target, role, validation)
    session.add(
        ReviewEventRow(
            target_id=target_id,
            from_status=current.value,
            to_status=target.value,
            actor=actor,
            role=role.value,
            note=note,
            created_at=utcnow(),
        )
    )
    session.flush()
    return Transition(current, target, actor, role, note)
