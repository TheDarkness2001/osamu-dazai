"""PDF output.

* DOCX → PDF with LibreOffice (``soffice``) when installed — page-faithful to the DOCX.
* HTML → PDF with a headless Chromium browser (Edge or Chrome) otherwise.

Both are external programs run as subprocesses on local files; nothing is uploaded.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


class PdfConverterUnavailable(RuntimeError):
    pass


_CHROMIUM_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]


def find_chromium() -> str | None:
    if env := os.environ.get("DAZAI_CHROMIUM"):
        return env
    for name in ("chromium", "chromium-browser", "google-chrome", "chrome", "msedge"):
        if p := shutil.which(name):
            return p
    return next((c for c in _CHROMIUM_CANDIDATES if Path(c).exists()), None)


def find_soffice() -> str | None:
    for name in ("soffice", "libreoffice"):
        if p := shutil.which(name):
            return p
    for c in (r"C:\Program Files\LibreOffice\program\soffice.exe", "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        if Path(c).exists():
            return c
    return None


def html_to_pdf(html: str, dest: str | Path, *, timeout: int = 120) -> Path:
    browser = find_chromium()
    if browser is None:
        raise PdfConverterUnavailable("no Chromium-based browser found (install Chrome/Edge or set DAZAI_CHROMIUM)")
    dest = Path(dest).resolve()
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "document.html"
        src.write_text(html, encoding="utf-8")
        cmd = [browser, "--headless", "--disable-gpu", "--no-pdf-header-footer", "--no-first-run",
               f"--user-data-dir={Path(d) / 'profile'}", f"--print-to-pdf={dest}", src.as_uri()]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if not dest.exists() or dest.stat().st_size == 0:
        raise RuntimeError(f"PDF conversion failed: {r.stderr.strip()[-300:]}")
    return dest


def docx_to_pdf(docx_path: str | Path, out_dir: str | Path, *, timeout: int = 180) -> Path:
    soffice = find_soffice()
    if soffice is None:
        raise PdfConverterUnavailable("LibreOffice not found")
    out_dir = Path(out_dir)
    subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(docx_path)],
                   capture_output=True, timeout=timeout, check=True)
    pdf = out_dir / (Path(docx_path).stem + ".pdf")
    if not pdf.exists():
        raise RuntimeError("LibreOffice did not produce a PDF")
    return pdf
