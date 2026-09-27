"""Walk the library, read every audio file and cache the result.

The cache (<library>/.muzcache.db) is keyed by relative path and is reused
while size and mtime stay the same, so repeated runs only re-read files
that changed.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from muz import tags as tagmod
from muz.formats import AUDIO_EXTS, WRITABLE_EXTS
from muz.library import Library

CACHE_VERSION = 1


@dataclass
class Track:
    rel: str
    size: int
    mtime: float
    info: tagmod.AudioInfo = field(default_factory=tagmod.AudioInfo)
    tags: tagmod.Tags = field(default_factory=dict)
    has_cover: bool = False
    error: str = ""
    path: Path = field(default=Path(), repr=False)

    @property
    def ext(self) -> str:
        return Path(self.rel).suffix.lower()

    @property
    def writable(self) -> bool:
        return self.ext in WRITABLE_EXTS

    def first(self, key: str) -> str:
        vals = self.tags.get(key, [])
        return vals[0] if vals else ""

    def to_row(self) -> str:
        return json.dumps(
            {"info": asdict(self.info), "tags": self.tags, "has_cover": self.has_cover, "error": self.error}
        )

    @classmethod
    def from_row(cls, rel: str, size: int, mtime: float, row: str, root: Path) -> Track:
        data = json.loads(row)
        return cls(
            rel=rel,
            size=size,
            mtime=mtime,
            info=tagmod.AudioInfo(**data["info"]),
            tags=data["tags"],
            has_cover=data["has_cover"],
            error=data["error"],
            path=root / rel,
        )


@dataclass
class ScanResult:
    tracks: list[Track] = field(default_factory=list)
    other_files: Counter = field(default_factory=Counter)  # extension -> count
    other_size: int = 0
    folders: int = 0
    artist_folders: int = 0
    album_folders: int = 0
    loose_files: int = 0  # audio files not at <artist>/<album>/<file> depth


def walk(lib: Library) -> tuple[list[tuple[str, int, float]], ScanResult]:
    """List audio files and count everything else. Hidden entries are skipped."""
    result = ScanResult()
    audio: list[tuple[str, int, float]] = []
    root = str(lib.root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        rel_dir = os.path.relpath(dirpath, root)
        depth = 0 if rel_dir == "." else rel_dir.count(os.sep) + 1
        if depth:
            result.folders += 1
            if depth == 1:
                result.artist_folders += 1
            elif depth == 2:
                result.album_folders += 1
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext in AUDIO_EXTS:
                rel = os.path.relpath(full, root)
                audio.append((rel, st.st_size, st.st_mtime))
                if depth != 2:
                    result.loose_files += 1
            else:
                result.other_files[ext or "(none)"] += 1
                result.other_size += st.st_size
    return audio, result


class Cache:
    def __init__(self, path: Path | None):
        self.db = None
        if path is None:
            return
        try:
            self.db = sqlite3.connect(path)
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS tracks (rel TEXT PRIMARY KEY, size INTEGER, mtime REAL, version INTEGER, row TEXT)"
            )
        except sqlite3.Error:
            self.db = None

    def load(self) -> dict[str, tuple[int, float, str]]:
        if not self.db:
            return {}
        rows = self.db.execute("SELECT rel, size, mtime, row FROM tracks WHERE version = ?", (CACHE_VERSION,))
        return {rel: (size, mtime, row) for rel, size, mtime, row in rows}

    def store(self, tracks: list[Track], keep: set[str]) -> None:
        if not self.db:
            return
        with self.db:
            self.db.executemany(
                "INSERT OR REPLACE INTO tracks VALUES (?, ?, ?, ?, ?)",
                [(t.rel, t.size, t.mtime, CACHE_VERSION, t.to_row()) for t in tracks],
            )
            existing = {r for (r,) in self.db.execute("SELECT rel FROM tracks")}
            gone = existing - keep
            self.db.executemany("DELETE FROM tracks WHERE rel = ?", [(r,) for r in gone])

    def close(self) -> None:
        if self.db:
            self.db.close()


def read_track(root: Path, rel: str, size: int, mtime: float) -> Track:
    track = Track(rel=rel, size=size, mtime=mtime, path=root / rel)
    try:
        track.info, track.tags, track.has_cover = tagmod.read(track.path)
    except tagmod.TagError as exc:
        track.error = str(exc)
    return track


ProgressFn = Callable[[int, int], None]


def scan(lib: Library, *, use_cache: bool = True, progress: ProgressFn | None = None, workers: int = 8) -> ScanResult:
    files, result = walk(lib)
    cache = Cache(lib.cache_file if use_cache else None)
    cached = cache.load()
    total = len(files)
    tracks: list[Track | None] = [None] * total
    todo: list[int] = []
    for i, (rel, size, mtime) in enumerate(files):
        hit = cached.get(rel)
        if hit and hit[0] == size and hit[1] == mtime:
            try:
                tracks[i] = Track.from_row(rel, size, mtime, hit[2], lib.root)
                continue
            except (KeyError, TypeError, ValueError):
                pass
        todo.append(i)

    done = total - len(todo)
    if progress:
        progress(done, total)
    fresh: list[Track] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {i: pool.submit(read_track, lib.root, *files[i]) for i in todo}
        for i, fut in futures.items():
            track = fut.result()
            tracks[i] = track
            fresh.append(track)
            done += 1
            if progress:
                progress(done, total)

    result.tracks = [t for t in tracks if t is not None]
    cache.store(fresh, {rel for rel, _, _ in files})
    cache.close()
    return result


def refresh(lib: Library, track: Track) -> Track:
    """Re-read one track after it was changed."""
    st = track.path.stat()
    return read_track(lib.root, lib.rel(track.path), st.st_size, st.st_mtime)
