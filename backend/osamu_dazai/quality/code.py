"""Programming checks for code in generated material (spec §14 'Programming').

Syntax checks never execute code: Python is parsed with ``ast``; JavaScript is
checked with ``node --check`` (parse only). Running code to compare expected
output is a separate, explicit opt-in (``run_python`` / ``run_javascript``):
it executes model-written code locally with a timeout and no stdin, so it is
off unless the caller enables it.
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass

PY = {"python", "py", "python3"}
JS = {"javascript", "js", "node"}


@dataclass(frozen=True)
class CodeCheck:
    ok: bool
    message: str = ""
    skipped: bool = False


def check_syntax(language: str, code: str) -> CodeCheck:
    lang = language.strip().lower()
    if lang in PY:
        try:
            ast.parse(code)
        except SyntaxError as e:
            return CodeCheck(False, f"Python syntax error, line {e.lineno}: {e.msg}")
        return CodeCheck(True)
    if lang in JS:
        node = shutil.which("node")
        if node is None:
            return CodeCheck(True, "node not installed; JavaScript syntax not checked", skipped=True)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "snippet.js")
            with open(path, "w", encoding="utf-8") as f:
                f.write(code)
            r = subprocess.run([node, "--check", path], capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            err = next((ln for ln in r.stderr.splitlines() if "Error" in ln), r.stderr.strip()[:200])
            return CodeCheck(False, f"JavaScript syntax error: {err}")
        return CodeCheck(True)
    return CodeCheck(True, f"no syntax checker for '{language}'", skipped=True)


def _run(cmd: list[str], code: str, suffix: str, timeout: float) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, f"snippet{suffix}")
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
        try:
            env = {"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"}
            if "SYSTEMROOT" in os.environ:  # Windows processes cannot start without it
                env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
            r = subprocess.run([*cmd, path], capture_output=True, text=True, timeout=timeout, cwd=d,
                               stdin=subprocess.DEVNULL, env=env, encoding="utf-8")
        except subprocess.TimeoutExpired:
            return False, f"timed out after {timeout}s"
    return r.returncode == 0, (r.stdout if r.returncode == 0 else r.stderr.strip()[-300:])


def run_and_compare(language: str, code: str, expected: str, *, timeout: float = 5.0) -> CodeCheck:
    """Execute (opt-in!) and compare stdout with ``expected`` (whitespace-trimmed per line)."""
    lang = language.strip().lower()
    if "input(" in code or "prompt(" in code:
        return CodeCheck(True, "reads user input; not executed", skipped=True)
    if lang in PY:
        ok, out = _run([sys.executable, "-I"], code, ".py", timeout)
    elif lang in JS and shutil.which("node"):
        ok, out = _run([shutil.which("node")], code, ".js", timeout)  # type: ignore[list-item]
    else:
        return CodeCheck(True, f"cannot execute '{language}'", skipped=True)
    if not ok:
        return CodeCheck(False, f"program failed: {out}")

    def norm(s: str) -> list[str]:
        return [ln.rstrip() for ln in s.strip().splitlines()]

    if norm(out) != norm(expected):
        return CodeCheck(False, f"expected output {expected.strip()!r} but the program prints {out.strip()!r}")
    return CodeCheck(True)
