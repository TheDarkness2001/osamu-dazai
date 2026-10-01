"""The inline markup subset used in content blocks: **bold**, *italic*, `code`."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape

_TOKEN = re.compile(r"(\*\*(?=\S)(.+?)(?<=\S)\*\*|`([^`]+)`|(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*]))")


@dataclass(frozen=True)
class Run:
    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False


def parse_inline(text: str) -> list[Run]:
    runs: list[Run] = []
    pos = 0
    for m in _TOKEN.finditer(text):
        if m.start() > pos:
            runs.append(Run(text[pos:m.start()]))
        if m.group(2) is not None:
            runs.append(Run(m.group(2), bold=True))
        elif m.group(3) is not None:
            runs.append(Run(m.group(3), code=True))
        else:
            runs.append(Run(m.group(4), italic=True))
        pos = m.end()
    if pos < len(text):
        runs.append(Run(text[pos:]))
    return runs


def to_html(text: str) -> str:
    out = []
    for r in parse_inline(text):
        t = escape(r.text)
        if r.code:
            t = f"<code>{t}</code>"
        if r.bold:
            t = f"<strong>{t}</strong>"
        if r.italic:
            t = f"<em>{t}</em>"
        out.append(t)
    return "".join(out)


def unbalanced(text: str) -> bool:
    """Markup markers left over after parsing (e.g. a lone ** or `)."""
    rest = "".join(r.text for r in parse_inline(text) if not (r.bold or r.italic or r.code))
    return "**" in rest or rest.count("`") % 2 == 1
