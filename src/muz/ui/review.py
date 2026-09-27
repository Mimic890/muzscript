"""Showing proposals and asking the user about each one."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from muz.plan import Op
from muz.ui.console import ask, console, esc


@dataclass
class Proposal:
    """One question for the user; accepting it produces operations.

    Proposals that share the same problem (for example 40 tracks with the same
    "A feat. B" ARTIST value) are one proposal, answered once.
    """

    title: str
    current: list[tuple[str, str]]  # (label, value) rows shown as "now"
    suggested: list[str]  # values shown as "will be"
    files: list[str]
    build: Callable[[list[str]], list[Op]]
    editable: bool = True
    note: str = ""
    extra: dict = field(default_factory=dict)


SEP = " | "


def show_dry_run(proposals: list[Proposal], what: str) -> None:
    table = Table(title=f"{what}: {len(proposals)} proposed fixes", title_style="title", expand=True, show_lines=True)
    table.add_column("#", style="dim", justify="right", no_wrap=True)
    table.add_column("Now", style="old", ratio=3)
    table.add_column("Will be", style="new", ratio=3)
    table.add_column("Files", justify="right", no_wrap=True)
    for i, p in enumerate(proposals, 1):
        now = "\n".join(f"{label}: {value}" for label, value in p.current)
        table.add_row(str(i), esc(now), esc("\n".join(p.suggested)) or "(removed)", str(len(p.files)))
    console.print(table)


def _show(p: Proposal, index: int, total: int) -> None:
    body = Text()
    for label, value in p.current:
        body.append(f"{label:<14}", style="dim")
        body.append(f"{value}\n", style="old")
    body.append("Will be:\n", style="dim")
    for v in p.suggested or ["(removed)"]:
        body.append(f"  • {v}\n", style="new")
    files = p.files[:3]
    body.append(f"\n{len(p.files)} file(s): ", style="dim")
    body.append(", ".join(files) + (" ..." if len(p.files) > 3 else ""), style="dim")
    if p.note:
        body.append(f"\n{p.note}", style="warn")
    console.print(Panel(body, title=f"[title]\\[{index}/{total}] {esc(p.title)}", title_align="left", border_style="cyan"))


def review(proposals: list[Proposal], *, auto: bool = False) -> list[Op]:
    """Ask about each proposal and return the accepted operations.

    Quitting keeps what was accepted before; the final [Y/n] still follows.
    """
    ops: list[Op] = []
    if auto:
        for p in proposals:
            ops.extend(p.build(p.suggested))
        return ops

    keys = "[key]y[/] accept  [key]e[/] edit  [key]s[/] skip  [key]a[/] accept all remaining  [key]q[/] quit"
    total = len(proposals)
    i = 0
    while i < total:
        p = proposals[i]
        _show(p, i + 1, total)
        console.print(keys if p.editable else keys.replace("[key]e[/] edit  ", ""))
        answer = ask("Choice [y/e/s/a/q]: ")
        if answer is None or answer.lower() == "q":
            console.print("[warn]Stopped. Choices made so far are kept.[/]")
            return ops
        answer = answer.lower() or "y"
        if answer == "y":
            ops.extend(p.build(p.suggested))
        elif answer == "s":
            pass
        elif answer == "a":
            for rest in proposals[i:]:
                ops.extend(rest.build(rest.suggested))
            return ops
        elif answer == "e" and p.editable:
            raw = ask(f"Values separated by '{SEP.strip()}' (empty = cancel): ")
            if not raw:
                continue
            values = [v.strip() for v in raw.split(SEP.strip()) if v.strip()]
            ops.extend(p.build(values))
        else:
            console.print("[warn]Unknown choice.[/]")
            continue
        i += 1
    return ops
