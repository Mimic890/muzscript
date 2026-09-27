"""Command line entry point: `muz [LIBRARY] [--action] [--apply]`."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from rich.table import Table

from muz import __version__, reports, stats
from muz import history as histmod
from muz import plan as planmod
from muz.actions import Context, artists, clean, convert, dupes, embed, fetch, genres, rename
from muz.config import load_rules
from muz.library import Library
from muz.scanner import scan
from muz.ui.console import confirm, console, esc, is_interactive, progress_bar
from muz.ui.review import Proposal, review, show_dry_run

EPILOG = """\
Without an action, muz scans the library and opens the statistics dashboard.
Nothing is changed unless --apply is given; every applied run can be undone
with --undo N (see --history).

Library-specific settings live in LIBRARY/.muzrules.toml (created on first run).
"""


def default_library() -> str:
    env = os.environ.get("MUZ_LIBRARY")
    if env:
        return env
    return "/music" if Path("/music").is_dir() else "."


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="muz",
        description="Music library maintenance: duplicates, tags, file names, covers, lyrics, conversion.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("library", nargs="?", default=None, help="music folder (default: $MUZ_LIBRARY, /music or .)")

    a = p.add_argument_group("actions (pick one)").add_mutually_exclusive_group()
    a.add_argument("--stats", action="store_true", help="print statistics without the TUI")
    a.add_argument("--dupes", action="store_true", help="find duplicate tracks and move extra copies to .muztrash")
    a.add_argument("--artists", action="store_true", help="split several artists into multi-valued ARTISTS")
    a.add_argument("--genres", action="store_true", help="split and merge genres")
    a.add_argument("--clean", action="store_true", help="remove junk tags, LRC headers and stray whitespace")
    a.add_argument("--embed", action="store_true", help="embed cover images and .lrc files lying next to tracks")
    a.add_argument("--fetch", metavar="KINDS", help="fill missing tags,lyrics,covers from the internet (or: all)")
    a.add_argument("--rename", action="store_true", help="move/rename files to match paths.template")
    a.add_argument("--convert", metavar="MODE", choices=convert.MODES, help="auto | mp3 | flac (see README)")
    a.add_argument("--report", metavar="WHAT", choices=reports.REPORTS, help="artists | genres | missing")
    a.add_argument("--search", metavar="TEXT", help="find tracks by artist, album, title or path")
    a.add_argument("--history", action="store_true", help="list previous runs")
    a.add_argument("--undo", metavar="N", type=int, help="revert run number N")

    o = p.add_argument_group("options")
    o.add_argument("--apply", action="store_true", help="really write the changes (asks [Y/n] first)")
    o.add_argument("--auto", action="store_true", help="accept every suggestion without asking one by one")
    o.add_argument("-y", "--yes", action="store_true", help="answer yes to the final [Y/n] confirmation")
    o.add_argument("--acoustic", action="store_true", help="with --dupes: verify by sound using fpcalc")
    o.add_argument("--no-cache", action="store_true", help="re-read every file instead of using .muzcache.db")
    o.add_argument("--version", action="version", version=f"muz {__version__}")
    return p


def do_scan(lib: Library, use_cache: bool):
    with progress_bar("Reading library") as update:
        result = scan(lib, use_cache=use_cache, progress=update)
    errors = [t for t in result.tracks if t.error]
    console.print(f"[dim]Scanned {len(result.tracks):,} audio files in {esc(str(lib.root))}[/]")
    if errors:
        console.print(f"[warn]{len(errors)} file(s) could not be read[/] [dim](see --report missing)[/]")
    return result


def apply_ops(lib: Library, ops: list, action: str, args, converter=None) -> int:
    if not ops:
        console.print("[dim]Nothing selected, nothing changed.[/]")
        return 0
    console.print(f"\n[accent]Ready:[/] {planmod.summarize(ops)}")
    if not confirm("Apply these changes?", assume_yes=args.yes):
        console.print("[warn]Cancelled, nothing changed.[/]")
        return 1
    with progress_bar("Applying") as update:
        result = planmod.apply(lib, ops, action, progress=update, converter=converter)
    report_result(lib, result)
    return 1 if result.errors else 0


def report_result(lib: Library, result: planmod.Result) -> None:
    if result.session:
        s = result.session
        console.print(f"[ok]Done:[/] {result.applied} change(s) applied.")
        console.print(f"[dim]History:[/] {esc(str(s.path.relative_to(lib.root)))}/summary.txt")
        console.print(f"[dim]Undo with:[/] muz {esc(str(lib.root))} --undo {s.number}")
    else:
        console.print("[warn]No changes were applied.[/]")
    for err in result.errors:
        console.print(f"[err]✗[/] {esc(err)}")


def run_proposals(ctx: Context, proposals: list[Proposal], what: str, action: str, args, converter=None) -> int:
    if not proposals:
        console.print(f"[ok]{what}: nothing to fix.[/]")
        return 0
    if not args.apply:
        show_dry_run(proposals, what)
        console.print("[warn]Dry run: nothing was changed.[/] Add [key]--apply[/] to choose and write changes.")
        return 0
    if not args.auto and not is_interactive():
        console.print("[err]Choosing changes needs a terminal. Use --auto to accept all suggestions.[/]")
        return 2
    ops = review(proposals, auto=args.auto)
    return apply_ops(ctx.lib, ops, action, args, converter)


def cmd_dupes(ctx: Context, args) -> int:
    if args.acoustic and not dupes.fpcalc_available():
        console.print("[err]--acoustic needs fpcalc (apt install libchromaprint-tools), or use the Docker image.[/]")
        return 2
    with progress_bar("Comparing") as update:
        groups = dupes.find(ctx, acoustic=args.acoustic, progress=update)
    if not groups:
        console.print("[ok]No duplicates found.[/]")
        return 0
    if not args.apply:
        dupes.show_all(groups)
        console.print("[warn]Dry run: nothing was changed.[/] Add [key]--apply[/] to choose which copies to keep.")
        return 0
    if not args.auto and not is_interactive():
        console.print("[err]Choosing copies needs a terminal. Use --auto to keep the ★ copy everywhere.[/]")
        return 2
    return apply_ops(ctx.lib, dupes.review(groups, auto=args.auto), "remove-duplicates", args)


def cmd_history(lib: Library) -> int:
    sessions = histmod.list_sessions(lib)
    if not sessions:
        console.print("[dim]No history yet.[/]")
        return 0
    table = Table(title="History", title_style="title", expand=True)
    table.add_column("N", justify="right", style="accent")
    table.add_column("Date")
    table.add_column("Time")
    table.add_column("Action", ratio=1)
    table.add_column("Changes", justify="right")
    for s in sessions:
        table.add_row(str(s.number), s.date, s.time, esc(s.action), "?" if s.changes is None else str(s.changes))
    console.print(table)
    console.print(f"[dim]Details: {esc(str(lib.history_dir))}/<run>/summary.txt   Undo: muz {esc(str(lib.root))} --undo N[/]")
    return 0


def cmd_undo(lib: Library, number: int, args) -> int:
    target = histmod.find_session(lib, number)
    if not target:
        console.print(f"[err]No run number {number}. See --history.[/]")
        return 2
    records = histmod.read_records(target)
    console.print(f"Run [accent]{target.number}[/]: {target.action}, {target.date} {target.time}, {len(records)} change(s).")
    for rec in records[:10]:
        console.print(f"  [dim]{esc(histmod.describe(rec))}[/]")
    if len(records) > 10:
        console.print(f"  [dim]... and {len(records) - 10} more[/]")
    if not confirm("Revert this run?", assume_yes=args.yes):
        console.print("[warn]Cancelled.[/]")
        return 1
    with progress_bar("Reverting") as update:
        result = planmod.undo(lib, target, progress=update)
    report_result(lib, result)
    return 1 if result.errors else 0


def main(argv: list[str] | None = None) -> int:
    if sys.platform != "linux":
        print("muz supports Linux only.", file=sys.stderr)
        return 2
    args = build_parser().parse_args(argv)
    try:
        lib = Library.open(args.library or default_library())
    except NotADirectoryError as exc:
        console.print(f"[err]{esc(str(exc))}[/]")
        return 2

    try:
        if args.history:
            return cmd_history(lib)
        if args.undo is not None:
            return cmd_undo(lib, args.undo, args)

        rules, created = load_rules(lib.rules_file)
        if created:
            console.print(f"[accent]Created {esc(str(lib.rules_file))}[/] [dim]- exceptions, aliases and templates live there.[/]")

        if not any([args.stats, args.dupes, args.artists, args.genres, args.clean, args.embed, args.fetch,
                    args.rename, args.convert, args.report, args.search]):
            if is_interactive():
                from muz.ui.dashboard import run

                run(lib, use_cache=not args.no_cache)
                return 0
            args.stats = True

        ctx = Context(lib, rules, do_scan(lib, not args.no_cache))

        if args.stats:
            s = stats.compute(ctx.scan)
            console.print(stats.layout(s, console.width))
            return 0
        if args.report:
            {"artists": reports.report_artists, "genres": reports.report_genres, "missing": reports.report_missing}[args.report](ctx)
            return 0
        if args.search:
            reports.search(ctx, args.search)
            return 0
        if args.dupes:
            return cmd_dupes(ctx, args)
        if args.artists:
            return run_proposals(ctx, artists.plan(ctx), "Artists", "split-artists", args)
        if args.genres:
            return run_proposals(ctx, genres.plan(ctx), "Genres", "fix-genres", args)
        if args.clean:
            return run_proposals(ctx, clean.plan(ctx), "Clean", "clean-tags", args)
        if args.embed:
            return run_proposals(ctx, embed.plan(ctx), "Embed", "embed-covers-lyrics", args)
        if args.rename:
            return run_proposals(ctx, rename.plan(ctx), "Rename", "rename-files", args)
        if args.convert:
            proposals = convert.plan(ctx, args.convert)
            return run_proposals(ctx, proposals, "Convert", f"convert-{args.convert}", args, convert.make_converter(rules))
        if args.fetch:
            from muz.providers import get_provider

            kinds = fetch.parse_kinds(args.fetch)
            provider = get_provider(rules.provider)
            console.print(f"[dim]Source: {provider.name}[/]")
            with progress_bar("Looking up") as update:
                proposals = fetch.plan(ctx, provider, kinds, progress=update)
            return run_proposals(ctx, proposals, "Fetch", f"fetch-{'-'.join(sorted(kinds))}", args)
    except (ValueError, RuntimeError) as exc:
        console.print(f"[err]{esc(str(exc))}[/]")
        return 2
    except KeyboardInterrupt:
        console.print("\n[warn]Interrupted.[/]")
        return 130
    return 0
