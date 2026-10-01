"""Website API (FastAPI TestClient — no network)."""

import base64
from io import BytesIO
from pathlib import Path

import docx
import pytest
from fastapi.testclient import TestClient

from osamu_dazai.web import app as web
from tests.ielts_helpers import sample_text

STATIC = Path(web.__file__).parent / "static"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("DAZAI_SITE_PASSWORD", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    web.app.user_middleware.clear()  # fresh rate-limit state per test
    web.app.middleware_stack = None
    web.app.add_middleware(web.Guard)
    return TestClient(web.app)


def upload(name: str, data: bytes, mime: str = DOCX) -> dict:
    return {"file": (name, data, mime)}


def broken() -> bytes:
    return (STATIC / "samples" / "broken_reading.docx").read_bytes()


def test_frontend_and_health(client):
    r = client.get("/")
    assert r.status_code == 200 and "<title>Osamu Dazai" in r.text
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/api/health").json()["status"] == "ok"
    cfg = client.get("/api/config").json()
    assert cfg["ai_enabled"] is False and cfg["password_required"] is False and cfg["product"] == "Osamu Dazai"


def test_validate_broken_and_clean(client):
    r = client.post("/api/ielts/validate", files=upload("broken.docx", broken()), data={"kind": "reading"})
    body = r.json()
    assert r.status_code == 200 and body["passed"] is False
    glued = [i for i in body["issues"] if i["code"] == "ielts.question.glued"]
    assert len(glued) == 3 and glued[0]["location"].startswith("Passage 1, Group Questions 8-13, Question 13")
    clean = (STATIC / "samples" / "clean_reading.docx").read_bytes()
    assert client.post("/api/ielts/validate", files=upload("ok.docx", clean)).json()["passed"] is True


def test_validate_plain_text(client):
    r = client.post("/api/ielts/validate", files=upload("t.txt", sample_text().encode(), "text/plain"))
    assert r.json()["passed"] is True and r.json()["lines"] > 100


def test_repair_returns_fixed_docx(client):
    r = client.post("/api/ielts/repair", files=upload("broken.docx", broken()), data={"threshold": "0.8"})
    body = r.json()
    assert body["preserved"] and body["exported"] and body["validation"]["passed"]
    assert body["download_name"] == "broken_fixed.docx" and len(body["ops"]) == 4 and body["flags"] == []
    fixed = docx.Document(BytesIO(base64.b64decode(body["docx_base64"])))
    assert "13 The Haarlem auction was attended mainly by foreign buyers." in [p.text for p in fixed.paragraphs]


def test_repair_not_exported_when_unsure(client):
    text = sample_text().replace("dug up.\n13. The Haarlem auction was attended mainly by foreign buyers.",
                                 "dug up and 13 more were sold.")
    body = client.post("/api/ielts/repair", files=upload("x.txt", text.encode(), "text/plain")).json()
    assert body["exported"] is False and body["docx_base64"] is None and body["flags"]


@pytest.mark.parametrize(("name", "data", "status"), [
    ("evil.exe", b"MZ", 415),
    ("empty.docx", b"", 400),
    ("fake.docx", b"not a zip", 422),
    ("latin1.txt", "café".encode("latin-1"), 422),
])
def test_bad_uploads(client, name, data, status):
    assert client.post("/api/ielts/validate", files=upload(name, data)).status_code == status


def test_upload_size_limit(client, monkeypatch):
    monkeypatch.setattr(web, "MAX_BYTES", 1000)
    assert client.post("/api/ielts/validate", files=upload("big.txt", b"x" * 2000, "text/plain")).status_code == 413


def test_bad_kind_and_threshold(client):
    assert client.post("/api/ielts/validate", files=upload("a.docx", broken()), data={"kind": "writing"}).status_code == 422
    assert client.post("/api/ielts/repair", files=upload("a.docx", broken()), data={"threshold": "5"}).status_code == 422


def test_optional_password(client, monkeypatch):
    monkeypatch.setenv("DAZAI_SITE_PASSWORD", "s3cret")
    assert client.post("/api/ielts/validate", files=upload("a.docx", broken())).status_code == 401
    ok = client.post("/api/ielts/validate", files=upload("a.docx", broken()), headers={"X-Dazai-Password": "s3cret"})
    assert ok.status_code == 200
    assert client.get("/api/config").json()["password_required"] is True  # config stays public


def test_rate_limit(client):
    statuses = [client.post("/api/ielts/validate", files=upload("t.txt", b"PASSAGE 1", "text/plain")).status_code
                for _ in range(32)]
    assert statuses.count(429) == 2


def test_samples(client):
    r = client.get("/api/samples/broken_reading.docx")
    assert r.status_code == 200 and r.content.startswith(b"PK")
    assert client.get("/api/samples/..%2F..%2Fapp.py").status_code in (404, 422)
