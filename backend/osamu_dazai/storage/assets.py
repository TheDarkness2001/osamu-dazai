"""File store for generated assets (figures, images).

Files live under ``root/<project_id>/``; names are given by the caller and
stay stable so documents can reference them by relative path.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

_SAFE = re.compile(r"[^A-Za-z0-9._-]")


class AssetStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def save(self, project_id: str, name: str, data: bytes | str) -> str:
        """Write and return the path relative to ``root``."""
        raw = data.encode("utf-8") if isinstance(data, str) else data
        rel = Path(_SAFE.sub("_", project_id)) / _SAFE.sub("_", name)
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return rel.as_posix()

    def read(self, rel: str) -> bytes:
        return (self.root / rel).read_bytes()

    @staticmethod
    def digest(data: bytes | str) -> str:
        raw = data.encode("utf-8") if isinstance(data, str) else data
        return hashlib.sha256(raw).hexdigest()[:16]
