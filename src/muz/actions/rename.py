"""--rename: move and rename files to match the path template in .muzrules.toml.

Lyrics files with the same name travel with their track. When every audio
file of a folder moves to one new folder, the rest of it (cover.jpg etc.)
moves too, and the emptied folder is removed.
"""

from __future__ import annotations

import re
import string
from collections import defaultdict
from pathlib import PurePosixPath

from muz.actions import Context
from muz.formats import AUDIO_EXTS, LYRICS_EXTS
from muz.plan import Move
from muz.scanner import Track
from muz.ui.console import console, esc
from muz.ui.review import Proposal

MAX_NAME_BYTES = 255  # Linux limit for one path component
TEMPLATE_FIELDS = {"albumartist", "album", "title", "artist", "year", "genre", "track", "disc", "disctotal", "tracktotal", "tracknum"}


def _int(value: str) -> int:
    m = re.match(r"\s*(\d+)", value or "")
    return int(m.group(1)) if m else 0


def clean_value(value: str) -> str:
    """Make a tag value safe inside one path component."""
    value = value.replace("/", "_").replace("\x00", "")
    value = re.sub(r"[\x01-\x1f\x7f]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def truncate_bytes(name: str, limit: int) -> str:
    raw = name.encode("utf-8")
    if len(raw) <= limit:
        return name
    return raw[:limit].decode("utf-8", "ignore").rstrip()


def clean_component(part: str, suffix: str = "") -> str:
    part = part.strip().lstrip(".").strip()  # a leading dot would hide the entry from Navidrome
    if not part:
        part = "_"
    return truncate_bytes(part, MAX_NAME_BYTES - len(suffix.encode("utf-8"))) + suffix


def check_template(template: str) -> None:
    for _, name, _, _ in string.Formatter().parse(template):
        if name is not None and name not in TEMPLATE_FIELDS:
            raise ValueError(f"Unknown field {{{name}}} in paths.template. Known: {', '.join(sorted(TEMPLATE_FIELDS))}")


def target_path(track: Track, template: str) -> str | None:
    """Relative target path, or None when required tags are missing."""
    albumartist = track.first("ALBUMARTIST")
    album = track.first("ALBUM")
    if not albumartist or not album:
        return None
    track_no = _int(track.first("TRACKNUMBER"))
    disc = _int(track.first("DISCNUMBER")) or 1
    disctotal = _int(track.first("DISCTOTAL"))
    tracknum = f"{disc}-{track_no:02d}" if disctotal > 1 or disc > 1 else f"{track_no:02d}"
    fields = {
        "albumartist": clean_value(albumartist),
        "album": clean_value(album),
        "title": clean_value(track.first("TITLE") or PurePosixPath(track.rel).stem),
        "artist": clean_value(track.first("ARTIST")),
        "year": track.first("DATE")[:4],
        "genre": clean_value(track.first("GENRE")),
        "track": track_no,
        "disc": disc,
        "disctotal": disctotal,
        "tracktotal": _int(track.first("TRACKTOTAL")),
        "tracknum": tracknum,
    }
    rendered = template.format(**fields)
    parts = [p for p in rendered.split("/") if p.strip()]
    if not parts:
        return None
    dirs = [clean_component(p) for p in parts[:-1]]
    name = clean_component(parts[-1], track.ext)
    return "/".join([*dirs, name])


def plan(ctx: Context) -> list[Proposal]:
    template = ctx.rules.path_template
    check_template(template)
    lib = ctx.lib
    all_audio_by_dir: dict[str, list[str]] = defaultdict(list)
    for t in ctx.scan.tracks:
        all_audio_by_dir[str(PurePosixPath(t.rel).parent)].append(t.rel)

    moves: dict[str, str] = {}  # src -> dst for audio
    taken: dict[str, str] = {}  # dst -> src
    skipped_tags: list[str] = []
    conflicts: list[str] = []

    for t in ctx.writable():
        dst = target_path(t, template)
        if dst is None:
            skipped_tags.append(t.rel)
            continue
        if dst == t.rel:
            taken[dst] = t.rel
            continue
        if dst in taken or (lib.abs(dst).exists() and lib.abs(dst).resolve() != t.path.resolve()):
            conflicts.append(f"{t.rel}  ->  {dst}")
            continue
        moves[t.rel] = dst
        taken[dst] = t.rel

    if skipped_tags:
        console.print(f"[warn]{len(skipped_tags)} track(s) skipped: ALBUMARTIST or ALBUM tag is empty.[/] "
                      "[dim]Fix the tags first (see --report missing).[/]")
    if conflicts:
        console.print(f"[warn]{len(conflicts)} track(s) skipped: target file already exists (possible duplicates, try --dupes):[/]")
        for c in conflicts[:10]:
            console.print(f"  [dim]{esc(c)}[/]")
        if len(conflicts) > 10:
            console.print(f"  [dim]... and {len(conflicts) - 10} more[/]")

    # Group per source folder -> target folder.
    groups: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for src, dst in moves.items():
        groups[(str(PurePosixPath(src).parent), str(PurePosixPath(dst).parent))].append((src, dst))

    proposals = []
    for (src_dir, dst_dir), pairs in sorted(groups.items()):
        ops: list[Move] = []
        for src, dst in sorted(pairs):
            ops.append(Move(src, dst, "rename"))
            src_path = lib.abs(src)
            for ext in LYRICS_EXTS:
                side = src_path.with_suffix(ext)
                if side.is_file():
                    side_dst = str(PurePosixPath(dst).with_suffix(ext))
                    if side_dst not in taken and not lib.abs(side_dst).exists():
                        ops.append(Move(lib.rel(side), side_dst, "lyrics file"))
                        taken[side_dst] = lib.rel(side)

        # Whole folder moves to one place: bring the other files (covers, etc.).
        audio_in_dir = all_audio_by_dir.get(src_dir, [])
        whole = src_dir not in (".", dst_dir) and all(moves.get(a, "").rsplit("/", 1)[0] == dst_dir for a in audio_in_dir)
        if whole:
            moving = {op.src for op in ops}
            try:
                for entry in sorted(lib.abs(src_dir).iterdir()):
                    rel = lib.rel(entry)
                    if entry.name.startswith(".") or not entry.is_file() or rel in moving:
                        continue
                    if entry.suffix.lower() in AUDIO_EXTS:
                        continue
                    side_dst = f"{dst_dir}/{entry.name}"
                    if side_dst not in taken and not lib.abs(side_dst).exists():
                        ops.append(Move(rel, side_dst, "folder file"))
                        taken[side_dst] = rel
            except OSError:
                pass

        examples = [f"{PurePosixPath(s).name}  ->  {PurePosixPath(d).name}" for s, d in sorted(pairs)[:3]]
        label = "Move folder" if src_dir != dst_dir else "Rename files"
        proposals.append(
            Proposal(
                title=label,
                current=[("From", src_dir), *(("File", e) for e in examples)],
                suggested=[dst_dir] + ([f"... {len(pairs) - 3} more file(s)"] if len(pairs) > 3 else []),
                files=[op.src for op in ops],
                build=lambda _v, ops=ops: list(ops),
                editable=False,
            )
        )
    return proposals
