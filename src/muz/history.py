"""Change history kept in <library>/.muzhistory/.

Each run that changes files is a session folder named
``NNN_YYYY-MM-DD_HH-MM_<action>_<count>-changes`` containing:

  changes.jsonl  one JSON record per applied change, written as it happens
  summary.txt    the same, readable by humans
  covers/        embedded pictures that were replaced (needed for undo)

Files moved out of the library by that session live in
``.muztrash/NNN_YYYY-MM-DD_HH-MM_<action>/`` with their original relative paths.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from muz.library import Library

SESSION_RE = re.compile(r"^(\d{3,})_(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2})_(.+?)(?:_(\d+)-changes)?$")


@dataclass
class SessionInfo:
    number: int
    date: str
    time: str
    action: str
    changes: int | None
    path: Path


def list_sessions(lib: Library) -> list[SessionInfo]:
    out = []
    if not lib.history_dir.is_dir():
        return out
    for entry in lib.history_dir.iterdir():
        m = SESSION_RE.match(entry.name)
        if entry.is_dir() and m:
            out.append(
                SessionInfo(
                    number=int(m.group(1)),
                    date=m.group(2),
                    time=m.group(3).replace("-", ":"),
                    action=m.group(4),
                    changes=int(m.group(5)) if m.group(5) else None,
                    path=entry,
                )
            )
    return sorted(out, key=lambda s: s.number)


def find_session(lib: Library, number: int) -> SessionInfo | None:
    return next((s for s in list_sessions(lib) if s.number == number), None)


def read_records(session: SessionInfo) -> list[dict]:
    path = session.path / "changes.jsonl"
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def describe(record: dict) -> str:
    op = record["op"]
    if op == "tag":
        old = " | ".join(record["old"]) or "(empty)"
        new = " | ".join(record["new"]) or "(removed)"
        return f"TAG    {record['file']}  {record['field']}: {old!r} -> {new!r}"
    if op == "cover":
        return f"COVER  {record['file']}  {'replaced' if record.get('old') else 'added'}"
    if op == "move":
        return f"MOVE   {record['src']}  ->  {record['dst']}"
    if op == "trash":
        return f"TRASH  {record['src']}  ->  {record['dst']}"
    if op == "create":
        return f"CREATE {record['file']}"
    return json.dumps(record, ensure_ascii=False)


class Session:
    """A history session; the folder is created on the first recorded change."""

    def __init__(self, lib: Library, action: str):
        self.lib = lib
        self.action = re.sub(r"[^a-z0-9-]+", "-", action.lower()).strip("-")
        existing = list_sessions(lib)
        self.number = (existing[-1].number + 1) if existing else 1
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        self.base_name = f"{self.number:03d}_{stamp}_{self.action}"
        self.dir = lib.history_dir / self.base_name
        self.trash_root = lib.trash_dir / self.base_name
        self.count = 0
        self._fh = None
        self._summary = None

    def _open(self) -> None:
        if self._fh is None:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._fh = (self.dir / "changes.jsonl").open("a", encoding="utf-8")
            self._summary = (self.dir / "summary.txt").open("a", encoding="utf-8")
            self._summary.write(
                f"muz session {self.number:03d}: {self.action}\n"
                f"started {datetime.now():%Y-%m-%d %H:%M:%S}\n"
                f"library {self.lib.root}\n"
                f"undo with: muz {self.lib.root} --undo {self.number}\n\n"
            )

    def record(self, record: dict) -> None:
        self._open()
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._fh.flush()
        self._summary.write(describe(record) + "\n")
        self._summary.flush()
        self.count += 1

    def save_blob(self, name: str, data: bytes) -> str:
        self._open()
        blobs = self.dir / "covers"
        blobs.mkdir(exist_ok=True)
        (blobs / name).write_bytes(data)
        return f"covers/{name}"

    def trash_path(self, rel: str) -> Path:
        dst = self.trash_root / rel
        n = 1
        while dst.exists():
            dst = self.trash_root / f"{rel}.{n}"
            n += 1
        return dst

    def close(self) -> SessionInfo | None:
        """Finish the session; returns its info, or None if nothing changed."""
        if self._fh is None:
            return None
        self._summary.write(f"\nfinished {datetime.now():%Y-%m-%d %H:%M:%S}, {self.count} changes\n")
        self._fh.close()
        self._summary.close()
        final = self.dir.with_name(f"{self.base_name}_{self.count}-changes")
        shutil.move(self.dir, final)
        self.dir = final
        return find_session(self.lib, self.number)
