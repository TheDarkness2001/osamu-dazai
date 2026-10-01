"""Line IR: the one representation parser, validators, fixer and renderer share.

One ``Line`` == one logical line == one DOCX paragraph. DOCX-specific facts the
external parser cares about (auto-numbering, soft breaks, tables) ride along.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass
class Line:
    text: str
    para_index: int | None = None  # w:p index in the source DOCX
    auto_label: str | None = None  # Word auto-numbering label (not in the text!)
    soft_breaks: int = 0  # w:br inside the paragraph ("\n" in text)
    in_table: bool = False
    bold: bool = False  # rendering hint only

    @property
    def clean(self) -> str:
        """Text as a paragraph-based parser sees it: soft breaks collapse to spaces."""
        return " ".join(self.text.replace("\n", " ").split())

    @property
    def visible(self) -> str:
        """What a reader sees on the page, including Word's generated label."""
        return f"{self.auto_label} {self.text}" if self.auto_label else self.text

    def with_text(self, text: str) -> Line:
        return replace(self, text=text, soft_breaks=text.count("\n"))


def lines_from_text(text: str) -> list[Line]:
    return [Line(t) for t in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]


def lines_to_text(lines: list[Line]) -> str:
    return "\n".join(ln.visible for ln in lines)
