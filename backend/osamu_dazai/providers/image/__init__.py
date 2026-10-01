"""Image provider interface and a mock that renders placeholder PNGs."""

from __future__ import annotations

import hashlib
import struct
import zlib
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class ImageRequest(BaseModel):
    prompt: str = Field(min_length=1)
    width: int = Field(default=1024, gt=0, le=4096)
    height: int = Field(default=768, gt=0, le=4096)
    style: str = ""  # e.g. "flat educational illustration"
    negative_prompt: str = ""
    model: str | None = None


class ImageResult(BaseModel):
    data: bytes
    mime_type: str = "image/png"
    width: int
    height: int
    provider: str
    model: str
    revised_prompt: str | None = None


class ImageProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    async def generate(self, req: ImageRequest) -> ImageResult: ...


def solid_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """Minimal valid PNG of one colour (no imaging library needed)."""
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


class MockImageProvider(ImageProvider):
    """Deterministic placeholder: colour derived from the prompt, so tests are stable."""

    name = "mock"

    def __init__(self) -> None:
        self.requests: list[ImageRequest] = []

    async def generate(self, req: ImageRequest) -> ImageResult:
        self.requests.append(req)
        d = hashlib.sha256(req.prompt.encode("utf-8")).digest()
        return ImageResult(
            data=solid_png(req.width, req.height, (d[0], d[1], d[2])),
            width=req.width,
            height=req.height,
            provider=self.name,
            model=req.model or "mock-image-1",
        )


__all__ = ["ImageProvider", "ImageRequest", "ImageResult", "MockImageProvider", "solid_png"]
