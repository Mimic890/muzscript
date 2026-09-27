"""--dupes: find the same recording stored more than once.

Evidence, strongest first:
  exact     identical audio data (FLAC STREAMINFO MD5, MP3 frames without tags)
  isrc      same ISRC and length
  tags      same main artist + title (ignoring "feat.", "Remastered" ...) and length
  acoustic  with --acoustic, tag/ISRC groups are checked with Chromaprint (fpcalc)
            and split where the audio differs

Nothing is deleted: extra copies go to .muztrash/ and --undo brings them back.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field

from rich.table import Table

from muz import tags as tagmod
from muz.actions import Context
from muz.actions.split import split_value
from muz.plan import Op, Trash
from muz.scanner import Track
from muz.ui.console import ask, console, esc, human_duration, human_size

NOISE_RE = re.compile(
    r"[\(\[][^\)\]]*\b(feat|ft|featuring|with|remaster(ed)?|explicit|clean|album version|original mix|radio edit|single version)\b[^\)\]]*[\)\]]",
    re.IGNORECASE,
)
DASH_NOISE_RE = re.compile(r"\s+-\s+.*\b(remaster(ed)?|single version|album version)\b.*$", re.IGNORECASE)
FEAT_RE = re.compile(r"\s+(feat\.?|ft\.?|featuring)\s+.*$", re.IGNORECASE)


def normalize_title(title: str) -> str:
    t = NOISE_RE.sub(" ", title)
    t = DASH_NOISE_RE.sub("", t)
    t = FEAT_RE.sub("", t)
    return re.sub(r"[\W_]+", " ", t.casefold()).strip()


def main_artist(track: Track, separators: list[str], exceptions: list[str]) -> str:
    values = track.tags.get("ARTISTS") or track.tags.get("ARTIST") or track.tags.get("ALBUMARTIST") or [""]
    parts = split_value(values[0], separators, exceptions)
    return re.sub(r"[\W_]+", " ", (parts[0] if parts else "").casefold()).strip()


@dataclass
class Group:
    tracks: list[Track]
    reasons: set[str] = field(default_factory=set)


class _UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _by_duration(tracks: list[Track], tolerance: float) -> list[list[Track]]:
    """Split tracks into clusters whose lengths are within tolerance of each other."""
    tracks = sorted(tracks, key=lambda t: t.info.duration)
    clusters: list[list[Track]] = []
    for t in tracks:
        if clusters and t.info.duration - clusters[-1][0].info.duration <= tolerance:
            clusters[-1].append(t)
        else:
            clusters.append([t])
    return [c for c in clusters if len(c) > 1]


def _file_md5(track: Track) -> str:
    h = hashlib.md5()
    with track.path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def exact_groups(tracks: list[Track]) -> list[list[Track]]:
    groups: dict[str, list[Track]] = defaultdict(list)
    for t in tracks:
        if t.info.audio_md5 and t.ext == ".flac":
            groups[f"flac:{t.info.audio_md5}"].append(t)
    # MP3 and other formats: hash only files that could match (same length / size).
    mp3_by_len: dict[int, list[Track]] = defaultdict(list)
    other_by_size: dict[int, list[Track]] = defaultdict(list)
    for t in tracks:
        if t.ext == ".mp3":
            mp3_by_len[round(t.info.duration * 10)].append(t)
        elif t.ext != ".flac" or not t.info.audio_md5:
            other_by_size[t.size].append(t)
    for bucket in mp3_by_len.values():
        if len(bucket) > 1:
            for t in bucket:
                try:
                    groups[f"mp3:{tagmod.mp3_audio_hash(t.path)}"].append(t)
                except OSError:
                    pass
    for bucket in other_by_size.values():
        if len(bucket) > 1:
            for t in bucket:
                try:
                    groups[f"file:{_file_md5(t)}"].append(t)
                except OSError:
                    pass
    return [g for g in groups.values() if len(g) > 1]


# ---------------------------------------------------------------- acoustic


def fpcalc_available() -> bool:
    return shutil.which("fpcalc") is not None


def fingerprint(track: Track) -> list[int] | None:
    try:
        out = subprocess.run(
            ["fpcalc", "-raw", "-json", "-length", "120", str(track.path)],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        return [v & 0xFFFFFFFF for v in json.loads(out.stdout)["fingerprint"]]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        return None


def similarity(a: list[int], b: list[int], max_offset: int = 20) -> float:
    """Fraction of matching fingerprint bits at the best alignment (1.0 = identical)."""
    best = 0.0
    for offset in range(-max_offset, max_offset + 1):
        if offset >= 0:
            pairs = zip(a[offset:], b, strict=False)
        else:
            pairs = zip(a, b[-offset:], strict=False)
        diff = total = 0
        for x, y in pairs:
            diff += (x ^ y).bit_count()
            total += 32
        if total >= 32 * 50:
            best = max(best, 1 - diff / total)
    return best


def split_acoustic(group: list[Track], threshold: float = 0.85) -> list[list[Track]]:
    prints = {t.rel: fingerprint(t) for t in group}
    clusters: list[list[Track]] = []
    for t in group:
        fp = prints[t.rel]
        for cluster in clusters:
            ref = prints[cluster[0].rel]
            if fp is None or ref is None or similarity(fp, ref) >= threshold:
                cluster.append(t)
                break
        else:
            clusters.append([t])
    return [c for c in clusters if len(c) > 1]


# ---------------------------------------------------------------- finding


def find(ctx: Context, *, acoustic: bool = False, progress=None) -> list[Group]:
    r = ctx.rules
    tracks = [t for t in ctx.scan.tracks if not t.error]
    uf = _UnionFind()
    reasons: dict[str, set[str]] = defaultdict(set)

    def link(group: list[Track], reason: str) -> None:
        for t in group[1:]:
            uf.union(group[0].rel, t.rel)
        for t in group:
            reasons[t.rel].add(reason)

    for g in exact_groups(tracks):
        link(g, "exact")

    soft: list[tuple[list[Track], str]] = []
    by_isrc: dict[str, list[Track]] = defaultdict(list)
    by_tags: dict[tuple[str, str], list[Track]] = defaultdict(list)
    for t in tracks:
        isrc = re.sub(r"[^A-Z0-9]", "", t.first("ISRC").upper())
        if isrc:
            by_isrc[isrc].append(t)
        title = normalize_title(t.first("TITLE"))
        artist = main_artist(t, r.artist_separators, r.artist_exceptions)
        if title and artist:
            by_tags[(artist, title)].append(t)
    for bucket in by_isrc.values():
        for c in _by_duration(bucket, r.duration_tolerance):
            soft.append((c, "isrc"))
    for bucket in by_tags.values():
        for c in _by_duration(bucket, r.duration_tolerance):
            soft.append((c, "tags"))

    if acoustic:
        verified = []
        for i, (c, reason) in enumerate(soft, 1):
            for part in split_acoustic(c):
                verified.append((part, reason + "+acoustic"))
            if progress:
                progress(i, len(soft))
        soft = verified
    for c, reason in soft:
        link(c, reason)

    by_root: dict[str, list[Track]] = defaultdict(list)
    for t in tracks:
        if t.rel in uf.parent:
            by_root[uf.find(t.rel)].append(t)
    groups = []
    for members in by_root.values():
        if len(members) > 1:
            groups.append(Group(members, set().union(*(reasons[t.rel] for t in members))))
    groups.sort(key=lambda g: (g.tracks[0].first("ALBUMARTIST").casefold(), g.tracks[0].first("TITLE").casefold()))
    return groups


def rank_key(t: Track) -> tuple:
    """Higher is better: lossless, bit depth, sample rate, bitrate, tag completeness."""
    return (
        t.info.lossless,
        t.info.bits,
        t.info.sample_rate,
        t.info.bitrate,
        t.has_cover,
        bool(t.tags.get("LYRICS")),
        len(t.tags),
        t.writable,
    )


def best_index(group: Group) -> int:
    return max(range(len(group.tracks)), key=lambda i: rank_key(group.tracks[i]))


def quality(t: Track) -> str:
    i = t.info
    if i.lossless:
        bits = f"{i.bits}/" if i.bits else ""
        return f"{t.ext[1:].upper()} {bits}{i.sample_rate / 1000:g}kHz"
    return f"{t.ext[1:].upper()} {round(i.bitrate / 1000)}k"


def show_group(group: Group, index: int, total: int) -> int:
    best = best_index(group)
    title = group.tracks[0].first("TITLE") or group.tracks[0].rel
    artist = group.tracks[0].first("ARTIST")
    table = Table(
        title=f"\\[{index}/{total}] {esc(artist)} - {esc(title)}   [dim]({', '.join(sorted(group.reasons))})[/]",
        title_style="title",
        title_justify="left",
        expand=True,
    )
    table.add_column("#", justify="right", no_wrap=True)
    table.add_column("Quality", no_wrap=True)
    table.add_column("Length", justify="right", no_wrap=True)
    table.add_column("Size", justify="right", no_wrap=True)
    table.add_column("Cover", justify="center", no_wrap=True)
    table.add_column("Lyrics", justify="center", no_wrap=True)
    table.add_column("Tags", justify="right", no_wrap=True)
    table.add_column("Path", ratio=1, overflow="fold")
    for i, t in enumerate(group.tracks):
        mark = "[ok]★[/]" if i == best else " "
        table.add_row(
            f"{mark}{i + 1}",
            quality(t),
            human_duration(t.info.duration),
            human_size(t.size),
            "✔" if t.has_cover else "[dim]–[/]",
            "✔" if t.tags.get("LYRICS") else "[dim]–[/]",
            str(len(t.tags)),
            esc(t.rel),
            style="new" if i == best else None,
        )
    console.print(table)
    return best


def _parse_keep(answer: str, count: int) -> set[int] | None:
    try:
        picked = {int(x) - 1 for x in re.split(r"[,\s]+", answer) if x}
    except ValueError:
        return None
    if not picked or any(i < 0 or i >= count for i in picked):
        return None
    return picked


def review(groups: list[Group], *, auto: bool) -> list[Op]:
    ops: list[Op] = []

    def trash_all_but(group: Group, keep: set[int]) -> None:
        for i, t in enumerate(group.tracks):
            if i not in keep:
                ops.append(Trash(t.rel, f"duplicate of {group.tracks[min(keep)].rel}"))

    total = len(groups)
    i = 0
    while i < total:
        group = groups[i]
        if auto:
            trash_all_but(group, {best_index(group)})
            i += 1
            continue
        best = show_group(group, i + 1, total)
        console.print(
            "[key]Enter[/] keep ★   [key]1[/] / [key]1,3[/] keep those   [key]s[/] skip   "
            "[key]a[/] keep ★ in all remaining   [key]q[/] quit"
        )
        answer = ask("Keep: ")
        if answer is None or answer.lower() == "q":
            console.print("[warn]Stopped. Choices made so far are kept.[/]")
            break
        answer = answer.lower()
        if answer == "":
            trash_all_but(group, {best})
        elif answer == "s":
            pass
        elif answer == "a":
            for g in groups[i:]:
                trash_all_but(g, {best_index(g)})
            break
        else:
            keep = _parse_keep(answer, len(group.tracks))
            if keep is None:
                console.print("[warn]Type track numbers from the # column, for example 1 or 1,3.[/]")
                continue
            trash_all_but(group, keep)
        i += 1
    return ops


def show_all(groups: list[Group]) -> None:
    for i, g in enumerate(groups, 1):
        show_group(g, i, len(groups))
    extra = sum(len(g.tracks) - 1 for g in groups)
    wasted = sum(sum(t.size for t in g.tracks) - g.tracks[best_index(g)].size for g in groups)
    console.print(
        f"[accent]{len(groups)}[/] duplicate groups, [accent]{extra}[/] extra copies, "
        f"[accent]{human_size(wasted)}[/] would be freed by keeping ★."
    )
