from __future__ import annotations

from pathlib import Path
from typing import Any

from pyxaseco.core.config import load_toml_file


class StorageDriver:
    """Infrastructure boundary for local file and manifest access."""

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)

    def resolve(self, path: str | Path) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return self.base_dir / candidate

    def exists(self, path: str | Path) -> bool:
        return self.resolve(path).exists()

    def read_text(self, path: str | Path, *, encoding: str = "utf-8") -> str:
        return self.resolve(path).read_text(encoding=encoding)

    def read_toml(self, path: str | Path) -> dict[str, Any]:
        return load_toml_file(self.resolve(path))
