"""Planned changes, applying them, and undoing a session.

Actions never touch files directly: they build a list of operations, the
user reviews it, and only apply() writes, recording every step in history.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from muz import tags as tagmod
from muz.history import Session, SessionInfo, read_records
from muz.library import Library


@dataclass
class TagEdit:
    rel: str
    field: str
    old: list[str]
    new: list[str]
    reason: str = ""


@dataclass
class CoverEdit:
    rel: str
    picture: tagmod.Picture
    reason: str = ""


@dataclass
class Move:
    src: str
    dst: str
    reason: str = ""


@dataclass
class Trash:
    rel: str
    reason: str = ""


@dataclass
class Convert:
    rel: str
    dst: str
    fmt: str  # "mp3" or "flac"
    reason: str = ""


Op = TagEdit | CoverEdit | Move | Trash | Convert


@dataclass
class Result:
    applied: int = 0
    errors: list[str] = field(default_factory=list)
    session: SessionInfo | None = None


ProgressFn = Callable[[int, int, str], None]


def _files_touched(ops: list[Op]) -> int:
    names = set()
    for op in ops:
        names.add(getattr(op, "rel", None) or getattr(op, "src", None))
    return len(names)


def summarize(ops: list[Op]) -> str:
    kinds: dict[str, int] = {}
    for op in ops:
        kinds[type(op).__name__] = kinds.get(type(op).__name__, 0) + 1
    labels = {"TagEdit": "tag edits", "CoverEdit": "covers", "Move": "moves", "Trash": "to trash", "Convert": "conversions"}
    parts = [f"{n} {labels[k]}" for k, n in kinds.items()]
    return f"{', '.join(parts)} in {_files_touched(ops)} files"


def _move(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        raise FileExistsError(f"target already exists: {dst}")
    shutil.move(src, dst)


def _prune_empty_dirs(lib: Library, start: Path) -> None:
    d = start
    while d != lib.root and lib.root in d.parents:
        try:
            d.rmdir()
        except OSError:
            return
        d = d.parent


def apply(lib: Library, ops: list[Op], action: str, *, progress: ProgressFn | None = None, converter=None) -> Result:
    session = Session(lib, action)
    result = Result()

    # Group tag and cover edits per file: one open + one save per file.
    per_file: dict[str, list[Op]] = {}
    others: list[Op] = []
    for op in ops:
        if isinstance(op, (TagEdit, CoverEdit)):
            per_file.setdefault(op.rel, []).append(op)
        else:
            others.append(op)

    total = len(per_file) + len(others)
    step = 0

    def tick(label: str) -> None:
        nonlocal step
        step += 1
        if progress:
            progress(step, total, label)

    for rel, file_ops in per_file.items():
        try:
            writer = tagmod.TagWriter(lib.abs(rel))
            records = []
            for op in file_ops:
                if isinstance(op, TagEdit):
                    old = writer.get(op.field)
                    writer.set(op.field, op.new)
                    records.append({"op": "tag", "file": rel, "field": op.field, "old": old, "new": op.new})
                else:
                    old_pic = writer.cover()
                    old_ref = None
                    if old_pic:
                        name = hashlib.md5(rel.encode()).hexdigest() + _pic_ext(old_pic.mime)
                        old_ref = session.save_blob(name, old_pic.data)
                    writer.set_cover(op.picture)
                    records.append(
                        {"op": "cover", "file": rel, "old": old_ref, "old_mime": old_pic.mime if old_pic else None}
                    )
            writer.save()
            for rec in records:
                session.record(rec)
                result.applied += 1
        except (tagmod.TagError, OSError) as exc:
            result.errors.append(f"{rel}: {exc}")
        tick(rel)

    for op in others:
        try:
            if isinstance(op, Move):
                src = lib.abs(op.src)
                _move(src, lib.abs(op.dst))
                session.record({"op": "move", "src": op.src, "dst": op.dst})
                _prune_empty_dirs(lib, src.parent)
            elif isinstance(op, Trash):
                src = lib.abs(op.rel)
                dst = session.trash_path(op.rel)
                _move(src, dst)
                session.record({"op": "trash", "src": op.rel, "dst": lib.rel(dst)})
                _prune_empty_dirs(lib, src.parent)
            elif isinstance(op, Convert):
                converter(lib.abs(op.rel), lib.abs(op.dst), op.fmt)
                session.record({"op": "create", "file": op.dst})
                src = lib.abs(op.rel)
                dst = session.trash_path(op.rel)
                _move(src, dst)
                session.record({"op": "trash", "src": op.rel, "dst": lib.rel(dst)})
            result.applied += 1
        except Exception as exc:  # keep going; every failure is reported
            label = getattr(op, "rel", None) or getattr(op, "src", "")
            result.errors.append(f"{label}: {exc}")
        tick(getattr(op, "rel", None) or getattr(op, "src", ""))

    result.session = session.close()
    return result


def _pic_ext(mime: str) -> str:
    return ".png" if "png" in (mime or "") else ".jpg"


def undo(lib: Library, target: SessionInfo, *, progress: ProgressFn | None = None) -> Result:
    """Reverse a session's records, newest first, as a new session."""
    records = list(reversed(read_records(target)))
    session = Session(lib, f"undo-{target.number:03d}")
    result = Result()
    for i, rec in enumerate(records, 1):
        try:
            op = rec["op"]
            if op == "tag":
                writer = tagmod.TagWriter(lib.abs(rec["file"]))
                current = writer.get(rec["field"])
                writer.set(rec["field"], rec["old"])
                writer.save()
                session.record({"op": "tag", "file": rec["file"], "field": rec["field"], "old": current, "new": rec["old"]})
            elif op == "cover":
                writer = tagmod.TagWriter(lib.abs(rec["file"]))
                current = writer.cover()
                restore = None
                if rec.get("old"):
                    data = (target.path / rec["old"]).read_bytes()
                    restore = tagmod.Picture(data, rec.get("old_mime") or "image/jpeg")
                cur_ref = None
                if current:
                    name = hashlib.md5(rec["file"].encode()).hexdigest() + _pic_ext(current.mime)
                    cur_ref = session.save_blob(name, current.data)
                writer.set_cover(restore)
                writer.save()
                session.record({"op": "cover", "file": rec["file"], "old": cur_ref, "old_mime": current.mime if current else None})
            elif op == "move":
                src = lib.abs(rec["dst"])
                _move(src, lib.abs(rec["src"]))
                session.record({"op": "move", "src": rec["dst"], "dst": rec["src"]})
                _prune_empty_dirs(lib, src.parent)
            elif op == "trash":
                src = lib.abs(rec["dst"])
                _move(src, lib.abs(rec["src"]))
                session.record({"op": "move", "src": rec["dst"], "dst": rec["src"]})
                _prune_empty_dirs(lib, src.parent)
            elif op == "create":
                path = lib.abs(rec["file"])
                dst = session.trash_path(rec["file"])
                _move(path, dst)
                session.record({"op": "trash", "src": rec["file"], "dst": lib.rel(dst)})
            result.applied += 1
        except Exception as exc:
            result.errors.append(f"{rec.get('file') or rec.get('src')}: {exc}")
        if progress:
            progress(i, len(records), rec.get("file") or rec.get("src", ""))
    result.session = session.close()
    return result


def unique_path(lib: Library, rel: str, taken: set[str]) -> str:
    """Return rel, or rel with ' (2)', ' (3)'... when it exists or is already planned."""
    base, ext = os.path.splitext(rel)
    candidate = rel
    n = 2
    while candidate in taken or lib.abs(candidate).exists():
        candidate = f"{base} ({n}){ext}"
        n += 1
    return candidate
