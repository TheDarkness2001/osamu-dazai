"""Osamu Dazai website: JSON API + static frontend (FastAPI).

Run locally:  uv run uvicorn osamu_dazai.web.app:app --reload
On Render:    uvicorn osamu_dazai.web.app:app --host 0.0.0.0 --port $PORT

Stateless on purpose (free hosting has an ephemeral disk): uploads are
processed in memory and results returned in the response; nothing is stored.

Environment:
  DAZAI_SITE_PASSWORD   optional; when set, every /api call needs header X-Dazai-Password
  ANTHROPIC_API_KEY      optional; enables AI generators (not exposed in this version)
  DAZAI_MAX_UPLOAD_MB   upload limit, default 5
"""

from __future__ import annotations

import base64
import hmac
import os
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from osamu_dazai import __version__
from osamu_dazai.branding import CREATOR_NAME, CREATOR_URL, PRODUCT_NAME, PRODUCT_TAGLINE
from osamu_dazai.domain.validation import ValidationIssue, ValidationResult
from osamu_dazai.ielts import contract as C
from osamu_dazai.ielts.docx_io import read_docx
from osamu_dazai.ielts.exporter import build_docx, with_header_bold
from osamu_dazai.ielts.fixer import IELTSFormatRepair
from osamu_dazai.ielts.lines import Line, lines_from_text
from osamu_dazai.ielts.validators import IELTSDocumentValidator

STATIC = Path(__file__).parent / "static"
MAX_BYTES = int(float(os.environ.get("DAZAI_MAX_UPLOAD_MB", "5")) * 1024 * 1024)
ALLOWED = {".docx", ".txt", ".md"}
Kind = Literal["reading", "listening"]

app = FastAPI(title=f"{PRODUCT_NAME} API", version=__version__, docs_url="/api/docs", redoc_url=None,
              openapi_url="/api/openapi.json")


# ---------------------------------------------------------------------------
# Middleware: security headers, optional password, simple per-IP rate limit
# ---------------------------------------------------------------------------
class Guard(BaseHTTPMiddleware):
    def __init__(self, app, per_minute: int = 30) -> None:  # noqa: ANN001
        super().__init__(app)
        self.per_minute = per_minute
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):  # noqa: ANN201, ANN001
        path = request.url.path
        if path.startswith("/api/") and path not in ("/api/health", "/api/config"):
            password = os.environ.get("DAZAI_SITE_PASSWORD", "")
            given = request.headers.get("x-dazai-password", "")
            if password and not hmac.compare_digest(password.encode(), given.encode()):
                return JSONResponse({"detail": "Password required"}, status_code=401)
            if request.method == "POST":
                ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?")
                ip = ip.split(",")[0].strip()
                q, now = self.hits[ip], time.monotonic()
                while q and now - q[0] > 60:
                    q.popleft()
                if len(q) >= self.per_minute:
                    return JSONResponse({"detail": "Too many requests — please wait a minute."}, status_code=429)
                q.append(now)
        response = await call_next(request)
        if path.startswith("/static/fonts/") or path == "/static/icons.svg":
            response.headers["Cache-Control"] = "public, max-age=604800"
        elif path.startswith("/static/") or path == "/":
            response.headers["Cache-Control"] = "no-cache"  # revalidate (ETag) so deploys show up immediately
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        if not path.startswith("/api/docs"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        return response


app.add_middleware(Guard)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _style(kind: Kind) -> C.SectionStyle:
    return C.LISTENING if kind == "listening" else C.READING


async def _read_upload(file: UploadFile) -> tuple[list[Line], str]:
    name = file.filename or "document"
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(415, f"Unsupported file type '{ext}'. Upload .docx, .txt or .md.")
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"File is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    if not data:
        raise HTTPException(400, "The file is empty.")
    if ext == ".docx":
        try:
            return read_docx(data).lines, name
        except Exception as e:  # corrupt or non-Word zip
            raise HTTPException(422, "This does not look like a valid Word (.docx) file.") from e
    try:
        return lines_from_text(data.decode("utf-8-sig")), name
    except UnicodeDecodeError as e:
        raise HTTPException(422, "Text files must be UTF-8 encoded.") from e


def _issue(i: ValidationIssue) -> dict:
    return {"code": i.code, "severity": i.severity.value, "location": i.location.describe(),
            "excerpt": i.location.excerpt, "problem": i.problem, "expected": i.expected,
            "suggestion": i.suggestion}


def _result(r: ValidationResult) -> dict:
    return {"passed": r.passed, "errors": len(r.errors), "warnings": len(r.issues) - len(r.errors),
            "issues": [_issue(i) for i in r.issues]}


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/api/config")
def config() -> dict:
    return {"product": PRODUCT_NAME, "tagline": PRODUCT_TAGLINE, "version": __version__,
            "creator": {"name": CREATOR_NAME, "url": CREATOR_URL},
            "ai_enabled": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "password_required": bool(os.environ.get("DAZAI_SITE_PASSWORD")),
            "max_upload_mb": MAX_BYTES // (1024 * 1024)}


@app.post("/api/ielts/validate")
async def validate(file: UploadFile = File(...), kind: Kind = Form("reading")) -> dict:
    lines, name = await _read_upload(file)
    result = IELTSDocumentValidator(_style(kind)).validate_lines(lines, target_id=name)
    return {"file": name, "kind": kind, "lines": len(lines), **_result(result)}


@app.post("/api/ielts/repair")
async def repair(file: UploadFile = File(...), kind: Kind = Form("reading"),
                 threshold: float = Form(0.8)) -> dict:
    if not 0.5 <= threshold <= 0.99:
        raise HTTPException(422, "threshold must be between 0.5 and 0.99")
    lines, name = await _read_upload(file)
    style = _style(kind)
    report = IELTSFormatRepair(threshold=threshold, style=style).repair(lines)
    payload: dict = {
        "file": name, "kind": kind, "preserved": report.preserved,
        "ops": [{"kind": o.kind, "line": o.line, "confidence": round(o.confidence, 2), "reason": o.reason,
                 "before": o.before[:200], "after": [a[:200] for a in o.after]} for o in report.ops],
        "flags": [{"line": f.line, "problem": f.problem, "proposal": f.proposal,
                   "confidence": round(f.confidence, 2), "excerpt": f.excerpt} for f in report.flags],
        "groups": report.group_summary(), "exported": False, "docx_base64": None,
    }
    if report.preserved:
        data, result = build_docx(with_header_bold(report.repaired, style), style)
        payload["validation"] = _result(result)
        if result.passed:
            stem = Path(name).stem
            payload.update(exported=True, docx_base64=base64.b64encode(data).decode(),
                           download_name=f"{stem}_fixed.docx")
    return payload


@app.get("/api/samples/{name}")
def sample(name: Literal["broken_reading.docx", "clean_reading.docx"]) -> FileResponse:
    return FileResponse(STATIC / "samples" / name, filename=name,
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
