"""--report and --search: read-only views of the library."""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from rich.table import Table

from muz.actions import Context
from muz.actions.split import split_value
from muz.stats import ISSUES, issue_checks
from muz.ui.console import console, esc

REPORTS = ("artists", "genres", "missing")

_TRANSLIT = str.maketrans(
    {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
        "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
        "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh",
        "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
)


def fold(name: str) -> str:
    """Key under which spellings of one name collide: case, punctuation, Cyrillic."""
    key = name.casefold().translate(_TRANSLIT)
    key = re.sub(r"^the\s+", "", key)
    return re.sub(r"[\W_]+", "", key)


def artist_counts(ctx: Context) -> Counter:
    counts: Counter = Counter()
    for t in ctx.scan.tracks:
        names = t.tags.get("ARTISTS")
        if not names:
            names = []
            for v in t.tags.get("ARTIST", []):
                names += split_value(v, ctx.rules.artist_separators, ctx.rules.artist_exceptions)
        for aa in t.tags.get("ALBUMARTISTS") or t.tags.get("ALBUMARTIST", []):
            if aa not in names:
                names.append(aa)
        counts.update(set(names))
    return counts


def similar_groups(names: list[str]) -> list[list[str]]:
    by_key: dict[str, list[str]] = defaultdict(list)
    for n in names:
        key = fold(n)
        if key:
            by_key[key].append(n)
    return [sorted(v) for v in by_key.values() if len(v) > 1]


def report_artists(ctx: Context) -> None:
    counts = artist_counts(ctx)
    table = Table(title=f"Artists: {len(counts)}", title_style="title", expand=True)
    table.add_column("Artist", ratio=1)
    table.add_column("Tracks", justify="right")
    for name, n in sorted(counts.items(), key=lambda kv: kv[0].casefold()):
        table.add_row(esc(name), str(n))
    console.print(table)
    groups = similar_groups(list(counts))
    if groups:
        sim = Table(title="Possibly the same artist", title_style="warn", expand=True)
        sim.add_column("Spellings", ratio=1)
        for g in groups:
            sim.add_row(esc(" · ".join(f"{n} ({counts[n]})" for n in g)))
        console.print(sim)
        console.print("[dim]Merge them with \\[artists.aliases] in .muzrules.toml, then run --artists.[/]")


def report_genres(ctx: Context) -> None:
    counts: Counter = Counter()
    for t in ctx.scan.tracks:
        counts.update(set(t.tags.get("GENRE", [])))
    table = Table(title=f"Genres: {len(counts)}", title_style="title", expand=True)
    table.add_column("Genre", ratio=1)
    table.add_column("Tracks", justify="right")
    for name, n in counts.most_common():
        table.add_row(esc(name), str(n))
    console.print(table)
    groups = similar_groups(list(counts))
    if groups:
        console.print("[warn]Possibly the same genre:[/] " + esc("; ".join(" · ".join(g) for g in groups)))


def report_missing(ctx: Context, limit: int = 15) -> None:
    by_issue: dict[str, list[str]] = defaultdict(list)
    for t in ctx.scan.tracks:
        for issue in issue_checks(t):
            by_issue[issue].append(t.rel)
    if not by_issue:
        console.print("[ok]Nothing is missing.[/]")
        return
    for key, label in ISSUES.items():
        files = by_issue.get(key)
        if not files:
            continue
        table = Table(title=f"{label}: {len(files)}", title_style="warn", title_justify="left", expand=True, show_header=False)
        table.add_column(ratio=1, overflow="fold")
        for rel in files[:limit]:
            table.add_row(esc(rel))
        if len(files) > limit:
            table.add_row(f"[dim]... and {len(files) - limit} more[/]")
        console.print(table)


def search(ctx: Context, text: str) -> None:
    q = text.casefold()
    fields = ("TITLE", "ARTIST", "ARTISTS", "ALBUMARTIST", "ALBUM")
    hits = [t for t in ctx.scan.tracks if any(q in v.casefold() for f in fields for v in t.tags.get(f, [])) or q in t.rel.casefold()]
    table = Table(title=f'"{esc(text)}": {len(hits)} tracks', title_style="title", expand=True)
    table.add_column("Artist", ratio=2)
    table.add_column("Title", ratio=2)
    table.add_column("Album artist", ratio=2)
    table.add_column("Album", ratio=2)
    table.add_column("Path", ratio=3, overflow="fold", style="dim")
    for t in hits:
        table.add_row(
            esc(" | ".join(t.tags.get("ARTISTS") or t.tags.get("ARTIST", []))),
            esc(t.first("TITLE")),
            esc(t.first("ALBUMARTIST")),
            esc(t.first("ALBUM")),
            esc(t.rel),
        )
    console.print(table)
