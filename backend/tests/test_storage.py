import pytest

from osamu_dazai.domain import (
    Course,
    Document,
    DocumentKind,
    Project,
    ProjectKind,
    ReviewStatus,
    StudentBook,
)
from osamu_dazai.domain.documents import ValidationStatus
from osamu_dazai.storage import (
    DocumentRepository,
    EntityRepository,
    NotFound,
    ProjectRepository,
    init_db,
    make_engine,
    session_factory,
)


@pytest.fixture
def session():
    engine = make_engine()
    init_db(engine)
    with session_factory(engine)() as s:
        yield s


@pytest.fixture
def project(session):
    return ProjectRepository(session).save(Project(name="IELTS Academic Reading", kind=ProjectKind.IELTS))


def test_project_round_trip(session, project):
    repo = ProjectRepository(session)
    assert repo.get(project.id) == project
    assert [p.id for p in repo.list()] == [project.id]
    with pytest.raises(NotFound):
        repo.get("prj_missing")


def test_entity_store_by_type_and_parent(session, project):
    repo = EntityRepository(session)
    course = repo.save(Course(project_id=project.id, title="Python", subject="Python", level="beginner"), project.id)
    book = repo.save(StudentBook(course_id=course.id, title="Python 1"), project.id)
    assert repo.get(Course, course.id) == course
    assert [b.id for b in repo.list(StudentBook, project.id, parent_id=course.id)] == [book.id]
    with pytest.raises(NotFound):
        repo.get(StudentBook, course.id)  # wrong type


def test_entity_store_rejects_unregistered_types(session, project):
    with pytest.raises(TypeError):
        EntityRepository(session).save(project, project.id)


def test_versioning_append_only_and_restore(session, project):
    docs = DocumentRepository(session)
    doc = docs.create(Document(project_id=project.id, kind=DocumentKind.IELTS_TEST, title="Test 1"))

    v1 = docs.commit(doc.id, {"passages": 1}, changed_by="ai:ielts_generator", generation_model="mock-1",
                     generation_prompt_version="ielts.v1")
    v2 = docs.commit(doc.id, {"passages": 3}, changed_by="user:editor")
    assert (v1.document_version, v2.document_version) == (1, 2)
    assert v2.source_version == 1

    # identical content does not create noise versions
    assert docs.commit(doc.id, {"passages": 3}, changed_by="user:editor").document_version == 2

    v3 = docs.restore(doc.id, 1, changed_by="user:editor")
    assert v3.document_version == 3
    assert v3.snapshot == {"passages": 1}
    assert v3.source_version == 1
    assert v3.generation_model == "mock-1"
    assert [v.document_version for v in docs.history(doc.id)] == [1, 2, 3]
    assert docs.history(doc.id)[1].snapshot == {"passages": 3}  # history untouched
    assert docs.get(doc.id).current_version == 3


def test_validation_status_per_version(session, project):
    docs = DocumentRepository(session)
    doc = docs.create(Document(project_id=project.id, kind=DocumentKind.STUDENT_BOOK, title="B"))
    docs.commit(doc.id, {"a": 1}, changed_by="u")
    docs.set_validation_status(doc.id, 1, ValidationStatus.FAILED)
    assert docs.latest(doc.id).validation_status is ValidationStatus.FAILED
    docs.set_status(doc.id, ReviewStatus.IN_REVIEW.value)
    assert docs.get(doc.id).status is ReviewStatus.IN_REVIEW


def test_unicode_snapshot_hash_stable(session, project):
    docs = DocumentRepository(session)
    doc = docs.create(Document(project_id=project.id, kind=DocumentKind.STUDENT_BOOK, title="B"))
    a = docs.commit(doc.id, {"t": "o'zgaruvchi", "r": "переменная"}, changed_by="u")
    b = docs.commit(doc.id, {"r": "переменная", "t": "o'zgaruvchi"}, changed_by="u")  # key order differs
    assert a.document_version == b.document_version == 1
