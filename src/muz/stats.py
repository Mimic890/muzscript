"""Library statistics, rendered as Rich tables (used by --stats and the TUI)."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from muz.scanner import ScanResult
from muz.ui.console import human_duration, human_size

WIDE = 110  # columns at which panels are placed side by side


@dataclass
class FormatStat:
    count: int = 0
    size: int = 0
    duration: float = 0.0


@dataclass
class Stats:
    tracks: int = 0
    size: int = 0
    duration: float = 0.0
    formats: dict[str, FormatStat] = field(default_factory=dict)
    writable: int = 0
    folders: int = 0
    artist_folders: int = 0
    album_folders: int = 0
    loose_files: int = 0
    other_files: Counter = field(default_factory=Counter)
    other_size: int = 0
    artists: int = 0
    albums: int = 0
    issues: dict[str, int] = field(default_factory=dict)


ISSUES = {
    "unreadable": "Unreadable files",
    "no_albumartist": "No ALBUMARTIST",
    "no_album": "No ALBUM",
    "no_title": "No TITLE",
    "no_track": "No TRACKNUMBER",
    "no_cover": "No embedded cover",
    "no_lyrics": "No lyrics",
    "no_genre": "No GENRE",
    "no_date": "No DATE",
}


def issue_checks(track) -> list[str]:
    if track.error:
        return ["unreadable"]
    out = []
    if not track.first("ALBUMARTIST"):
        out.append("no_albumartist")
    if not track.first("ALBUM"):
        out.append("no_album")
    if not track.first("TITLE"):
        out.append("no_title")
    if not track.first("TRACKNUMBER"):
        out.append("no_track")
    if not track.has_cover:
        out.append("no_cover")
    if not track.tags.get("LYRICS"):
        out.append("no_lyrics")
    if not track.tags.get("GENRE"):
        out.append("no_genre")
    if not track.first("DATE"):
        out.append("no_date")
    return out


def compute(scan: ScanResult) -> Stats:
    s = Stats(
        folders=scan.folders,
        artist_folders=scan.artist_folders,
        album_folders=scan.album_folders,
        loose_files=scan.loose_files,
        other_files=scan.other_files,
        other_size=scan.other_size,
    )
    formats: dict[str, FormatStat] = defaultdict(FormatStat)
    issues: Counter = Counter()
    artists, albums = set(), set()
    for t in scan.tracks:
        f = formats[t.ext]
        f.count += 1
        f.size += t.size
        f.duration += t.info.duration
        s.tracks += 1
        s.size += t.size
        s.duration += t.info.duration
        s.writable += t.writable
        issues.update(issue_checks(t))
        aa = t.first("ALBUMARTIST")
        if aa:
            artists.add(aa.casefold())
            if t.first("ALBUM"):
                albums.add((aa.casefold(), t.first("ALBUM").casefold()))
    s.formats = dict(sorted(formats.items(), key=lambda kv: -kv[1].count))
    s.issues = {k: issues[k] for k in ISSUES if issues[k]}
    s.artists, s.albums = len(artists), len(albums)
    return s


def _kv_table(title: str) -> Table:
    t = Table(title=title, title_style="bold magenta", title_justify="left", expand=True, show_header=False, box=None)
    t.add_column(style="grey58", ratio=1)
    t.add_column(justify="right", style="bold", ratio=1)
    return t


def overview_table(s: Stats) -> Table:
    t = _kv_table("Overview")
    t.add_row("Tracks", f"{s.tracks:,}")
    t.add_row("Total size", human_size(s.size))
    t.add_row("Total length", human_duration(s.duration))
    t.add_row("Artists (ALBUMARTIST)", f"{s.artists:,}")
    t.add_row("Albums", f"{s.albums:,}")
    t.add_row("Folders", f"{s.folders:,}")
    t.add_row("  artist folders", f"{s.artist_folders:,}")
    t.add_row("  album folders", f"{s.album_folders:,}")
    if s.loose_files:
        t.add_row("Tracks outside Artist/Album/", Text(f"{s.loose_files:,}", style="yellow"))
    return t


def formats_table(s: Stats) -> Table:
    t = Table(title="Audio formats", title_style="bold magenta", title_justify="left", expand=True)
    t.add_column("Format")
    t.add_column("Tracks", justify="right")
    t.add_column("Size", justify="right")
    t.add_column("Length", justify="right")
    t.add_column("muz", justify="center")
    for ext, f in s.formats.items():
        editable = ext in (".mp3", ".flac")
        t.add_row(
            ext[1:].upper(),
            f"{f.count:,}",
            human_size(f.size),
            human_duration(f.duration),
            Text("edit", style="green") if editable else Text("read-only", style="grey58"),
        )
    if not s.formats:
        t.add_row("—", "0", "0 B", "0:00", "")
    return t


def others_table(s: Stats, limit: int = 12) -> Table:
    t = Table(title="Other files", title_style="bold magenta", title_justify="left", expand=True)
    t.add_column("Extension")
    t.add_column("Files", justify="right")
    for ext, n in s.other_files.most_common(limit):
        t.add_row(ext, f"{n:,}")
    rest = sum(n for _, n in s.other_files.most_common()[limit:])
    if rest:
        t.add_row("other", f"{rest:,}")
    t.caption = f"{sum(s.other_files.values()):,} files, {human_size(s.other_size)}"
    return t


def issues_table(s: Stats) -> Table:
    t = _kv_table("Things to check")
    if not s.issues:
        t.add_row("Everything looks fine", Text("✔", style="green"))
    for key, n in s.issues.items():
        style = "red" if key in ("unreadable", "no_albumartist") else "yellow"
        t.add_row(ISSUES[key], Text(f"{n:,}", style=style))
    return t


def commands_table() -> Table:
    t = Table(title="Commands", title_style="bold magenta", title_justify="left", expand=True, show_header=False, box=None)
    t.add_column(style="bold cyan", no_wrap=True)
    t.add_column(style="grey70")
    for flag, text in COMMANDS:
        t.add_row(flag, text)
    t.caption = "Nothing is written without --apply. Undo any run with --undo N."
    return t


COMMANDS = [
    ("--dupes", "find duplicates (--acoustic to verify by sound)"),
    ("--artists", "split several artists into ARTISTS"),
    ("--genres", "split and merge genres"),
    ("--clean", "remove junk tags, LRC headers, spaces"),
    ("--embed", "embed cover and .lrc files lying next to tracks"),
    ("--fetch KINDS", "fill tags,lyrics,covers from the internet"),
    ("--rename", "move files to match the path template"),
    ("--convert MODE", "auto | mp3 | flac, keeps tags and cover"),
    ("--report WHAT", "artists | genres | missing"),
    ("--search TEXT", "find tracks by artist, album or title"),
    ("--history", "list past runs"),
    ("--undo N", "revert run number N"),
]


def layout(s: Stats, width: int, *, with_commands: bool = False):
    """All panels; side by side in two columns when the terminal is wide enough."""
    tables = [overview_table(s), formats_table(s), issues_table(s), others_table(s)]
    if with_commands:
        tables.append(commands_table())
    panels = [Panel(t, border_style="cyan") for t in tables]
    if width < WIDE:
        return Group(*panels)
    grid = Table.grid(expand=True, padding=(0, 1))
    grid.add_column(ratio=1)
    grid.add_column(ratio=1)
    for i in range(0, len(panels), 2):
        grid.add_row(*panels[i : i + 2])
    return grid
