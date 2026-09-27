"""Shared console output. Rich adapts every panel and table to the terminal width."""

from __future__ import annotations

import sys
from contextlib import contextmanager

from rich.console import Console
from rich.markup import escape as esc  # noqa: F401  (re-exported)
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeRemainingColumn
from rich.theme import Theme

THEME = Theme(
    {
        "title": "bold magenta",
        "accent": "bold cyan",
        "ok": "bold green",
        "warn": "bold yellow",
        "err": "bold red",
        "dim": "grey58",
        "old": "yellow",
        "new": "green",
        "key": "bold white",
    }
)

console = Console(theme=THEME, highlight=False)


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} TB"


def human_duration(seconds: float) -> str:
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}:{secs:02d}"


def is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def confirm(question: str, *, assume_yes: bool = False) -> bool:
    """Ask "[Y/n]"; Enter means yes."""
    if assume_yes:
        console.print(f"{question} [key]\\[Y/n][/] [ok]yes (--yes)[/]")
        return True
    if not sys.stdin.isatty():
        console.print(f"[err]{question} needs an answer, but input is not a terminal. Add --yes.[/]")
        return False
    while True:
        try:
            answer = console.input(f"{question} [key]\\[Y/n][/] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return False
        if answer in ("", "y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        console.print("[warn]Type y or n.[/]")


def ask(prompt: str) -> str | None:
    """Read a line; None on Ctrl+C / Ctrl+D."""
    try:
        return console.input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        console.print()
        return None


@contextmanager
def progress_bar(label: str):
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[accent]{task.description}"),
        BarColumn(bar_width=None),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=True,
    )
    with progress:
        task = progress.add_task(label, total=None)

        def update(done: int, total: int, *_):
            progress.update(task, completed=done, total=total)

        yield update
