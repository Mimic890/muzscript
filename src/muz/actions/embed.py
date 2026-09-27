"""--embed: embed cover images and .lrc/.txt lyrics lying next to the tracks."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from muz.actions import Context
from muz.actions.clean import strip_lrc_headers
from muz.formats import IMAGE_EXTS
from muz.plan import CoverEdit, TagEdit
from muz.tags import Picture
from muz.ui.review import Proposal


def image_mime(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def find_cover(folder: Path, names: list[str]) -> Path | None:
    try:
        images = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS and not p.name.startswith(".")]
    except OSError:
        return None
    for name in names:
        for img in sorted(images):
            if img.stem.lower() == name:
                return img
    return images[0] if len(images) == 1 else None


def find_lyrics(track_path: Path) -> Path | None:
    for ext in (".lrc", ".txt"):
        candidate = track_path.with_suffix(ext)
        if candidate.is_file():
            return candidate
    return None


def plan(ctx: Context) -> list[Proposal]:
    r = ctx.rules
    by_folder: dict[Path, list] = defaultdict(list)
    lyrics_edits: list[TagEdit] = []

    for t in ctx.writable():
        if not t.has_cover:
            by_folder[t.path.parent].append(t)
        if not t.tags.get("LYRICS"):
            lrc = find_lyrics(t.path)
            if lrc:
                text = lrc.read_text(encoding="utf-8", errors="replace")
                if r.strip_lrc_headers:
                    text = strip_lrc_headers(text)
                if text.strip():
                    lyrics_edits.append(TagEdit(t.rel, "LYRICS", [], [text], f"from {lrc.name}"))

    proposals = []
    for folder, tracks in sorted(by_folder.items()):
        cover = find_cover(folder, r.cover_names)
        if not cover:
            continue
        data = cover.read_bytes()
        pic = Picture(data, image_mime(data))
        files = [t.rel for t in tracks]
        rel_cover = ctx.lib.rel(cover)
        proposals.append(
            Proposal(
                title="Embed cover",
                current=[("Image", f"{rel_cover} ({len(data) // 1024} KB)")],
                suggested=[f"embedded into {len(files)} track(s) without a cover"],
                files=files,
                build=lambda _v, files=files, pic=pic: [CoverEdit(rel, pic, "cover file") for rel in files],
                editable=False,
            )
        )
    if lyrics_edits:
        proposals.append(
            Proposal(
                title="Embed lyrics",
                current=[("Source", ".lrc / .txt files with the same name as the track")],
                suggested=[f"embedded into {len(lyrics_edits)} track(s) without lyrics"],
                files=[e.rel for e in lyrics_edits],
                build=lambda _v, edits=lyrics_edits: list(edits),
                editable=False,
            )
        )
    return proposals
