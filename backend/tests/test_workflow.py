import pytest

from osamu_dazai.domain import ReviewStatus as S
from osamu_dazai.domain import ValidationIssue, ValidationResult
from osamu_dazai.domain.common import Severity
from osamu_dazai.storage import init_db, make_engine, session_factory
from osamu_dazai.storage.orm import ReviewEventRow
from osamu_dazai.workflow import Role, TransitionError, check_transition, transition

PASS = ValidationResult(target_id="d", profile="p")
FAIL = ValidationResult(
    target_id="d", profile="p", issues=[ValidationIssue(code="x", severity=Severity.ERROR, problem="bad")]
)


def test_happy_path():
    check_transition(S.DRAFT, S.AI_VALIDATED, Role.SYSTEM, PASS)
    check_transition(S.AI_VALIDATED, S.IN_REVIEW, Role.SYSTEM)
    check_transition(S.IN_REVIEW, S.APPROVED, Role.REVIEWER)
    check_transition(S.APPROVED, S.PUBLISHED, Role.REVIEWER)


def test_ai_cannot_approve_or_publish():
    with pytest.raises(TransitionError):
        check_transition(S.IN_REVIEW, S.APPROVED, Role.SYSTEM)
    with pytest.raises(TransitionError):
        check_transition(S.APPROVED, S.PUBLISHED, Role.SYSTEM)


def test_cannot_skip_review():
    with pytest.raises(TransitionError):
        check_transition(S.DRAFT, S.PUBLISHED, Role.ADMIN)
    with pytest.raises(TransitionError):
        check_transition(S.AI_VALIDATED, S.APPROVED, Role.ADMIN)


def test_failed_validation_blocks():
    with pytest.raises(TransitionError, match="blocking"):
        check_transition(S.DRAFT, S.AI_VALIDATED, Role.SYSTEM, FAIL)
    with pytest.raises(TransitionError, match="requires"):
        check_transition(S.DRAFT, S.AI_VALIDATED, Role.SYSTEM, None)


def test_transition_is_audited():
    engine = make_engine()
    init_db(engine)
    with session_factory(engine)() as s:
        transition(s, "doc_1", S.IN_REVIEW, S.APPROVED, actor="user:aziza", role=Role.REVIEWER, note="ok")
        ev = s.query(ReviewEventRow).one()
        assert (ev.from_status, ev.to_status, ev.actor) == ("in_review", "approved", "user:aziza")
