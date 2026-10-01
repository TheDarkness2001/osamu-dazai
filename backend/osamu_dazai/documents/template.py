"""Document templates (spec §35): page geometry, typography and page furniture."""

from __future__ import annotations

from typing import Literal

from osamu_dazai.domain.common import Model

PAGE_SIZES_MM = {"A4": (210.0, 297.0), "Letter": (215.9, 279.4), "A5": (148.0, 210.0)}


class DocTemplate(Model):
    name: str
    page_size: Literal["A4", "Letter", "A5"] = "A4"
    margins_mm: tuple[float, float, float, float] = (20, 20, 22, 22)  # top, right, bottom, left
    body_font: str = "Calibri"
    heading_font: str = "Calibri"
    code_font: str = "Consolas"
    base_pt: float = 11
    line_spacing: float = 1.15
    heading_color: str = "1F3A5F"
    header_text: str = ""  # e.g. book title; "{title}" is substituted
    page_numbers: bool = True
    table_of_contents: bool = True
    chapter_page_breaks: bool = True

    @property
    def text_width_cm(self) -> float:
        w, _ = PAGE_SIZES_MM[self.page_size]
        return (w - self.margins_mm[1] - self.margins_mm[3]) / 10


TEXTBOOK = DocTemplate(name="textbook", header_text="{title}")
TEACHER_GUIDE = DocTemplate(name="teacher_guide", header_text="{title}", base_pt=10.5, heading_color="2E4A3B")
EXAM = DocTemplate(name="exam", base_pt=11.5, table_of_contents=False, chapter_page_breaks=False,
                   margins_mm=(18, 18, 18, 18))
TEMPLATES = {t.name: t for t in (TEXTBOOK, TEACHER_GUIDE, EXAM)}
