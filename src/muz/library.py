"""Library root and the service files muz keeps inside it.

Every service entry starts with a dot, so Navidrome skips it
(Scanner.IgnoreDotFolders is on by default) and it does not show up in players.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

RULES_FILE = ".muzrules.toml"
HISTORY_DIR = ".muzhistory"
TRASH_DIR = ".muztrash"
CACHE_FILE = ".muzcache.db"


@dataclass(frozen=True)
class Library:
    root: Path

    @classmethod
    def open(cls, path: str | Path) -> Library:
        root = Path(path).expanduser().resolve()
        if not root.is_dir():
            raise NotADirectoryError(f"Library folder not found: {root}")
        return cls(root)

    @property
    def rules_file(self) -> Path:
        return self.root / RULES_FILE

    @property
    def history_dir(self) -> Path:
        return self.root / HISTORY_DIR

    @property
    def trash_dir(self) -> Path:
        return self.root / TRASH_DIR

    @property
    def cache_file(self) -> Path:
        return self.root / CACHE_FILE

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def abs(self, rel: str) -> Path:
        return self.root / rel
