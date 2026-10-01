"""Figures for documents: SVG → PNG (for DOCX) and a resolver from visual ids to files."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

PX_PER_CM = 96 / 2.54


def svg_to_png(svg: str, *, scale: float = 2.0) -> bytes:
    """Rasterise with resvg (pure wheel, no system libraries). ``scale`` 2 ≈ 192 dpi for print."""
    import resvg_py

    return bytes(resvg_py.svg_to_bytes(svg_string=svg, zoom=scale, background="#ffffff"))


@dataclass(frozen=True)
class Figure:
    visual_id: str
    path: Path  # .svg or raster image
    width_px: int | None = None

    @property
    def is_svg(self) -> bool:
        return self.path.suffix.lower() == ".svg"

    def svg_text(self) -> str:
        return self.path.read_text(encoding="utf-8")

    def png_bytes(self) -> bytes:
        return svg_to_png(self.svg_text()) if self.is_svg else self.path.read_bytes()

    def width_cm(self, max_cm: float) -> float:
        if self.width_px is None and self.is_svg:
            import re

            m = re.search(r'width="(\d+)', self.svg_text()[:400])
            px = int(m.group(1)) if m else 600
        else:
            px = self.width_px or 600
        return min(max_cm, px / PX_PER_CM)


def load_figures(course_dir: Path) -> dict[str, Figure]:
    """visual_id → Figure from the ``figures.json`` map written by the visuals step."""
    p = course_dir / "figures.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {vid: Figure(vid, course_dir / rel) for vid, rel in data.items()}
