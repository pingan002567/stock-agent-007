from __future__ import annotations

from pathlib import Path


class FileStore:
    def __init__(self, root: str | Path = "data/files") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def write_text(self, namespace: str, name: str, content: str) -> Path:
        directory = self.root / namespace
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_text(content, encoding="utf-8")
        return path

    def read_text(self, namespace: str, name: str) -> str:
        return (self.root / namespace / name).read_text(encoding="utf-8")
