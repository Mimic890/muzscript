"""The TUI shown by a plain `muz /music`: scans the library and shows statistics."""

from __future__ import annotations

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.widgets import Footer, Header, ProgressBar, Static

from muz import stats as statmod
from muz.library import Library
from muz.scanner import scan
from muz.stats import WIDE


class Dashboard(App):
    TITLE = "muz"
    CSS = """
    Screen { background: $surface; }
    #loading { height: auto; padding: 1 2; }
    #loading Static { margin-bottom: 1; }
    #panels { height: auto; layout: grid; grid-size: 1; grid-gutter: 1 2; padding: 1 2; }
    #panels.wide { grid-size: 2; }
    .panel { height: auto; border: round $primary; padding: 0 1; }
    .error { color: $error; padding: 1 2; }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "rescan", "Rescan"),
    ]

    def __init__(self, lib: Library, use_cache: bool = True):
        super().__init__()
        self.lib = lib
        self.use_cache = use_cache
        self.sub_title = str(lib.root)

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            with Container(id="loading"):
                yield Static("Scanning library...", id="status")
                yield ProgressBar(id="progress", show_eta=True)
            yield Container(id="panels")
        yield Footer()

    def on_mount(self) -> None:
        self.action_rescan()

    def on_resize(self, event) -> None:
        self.query_one("#panels").set_class(event.size.width >= WIDE, "wide")

    def action_rescan(self) -> None:
        self.query_one("#loading").display = True
        self.query_one("#panels").remove_children()
        self.query_one("#progress", ProgressBar).update(total=None, progress=0)
        self.run_scan()

    @work(thread=True, exclusive=True)
    def run_scan(self) -> None:
        bar = self.query_one("#progress", ProgressBar)

        def progress(done: int, total: int) -> None:
            self.call_from_thread(bar.update, total=total, progress=done)

        try:
            result = scan(self.lib, use_cache=self.use_cache, progress=progress)
        except Exception as exc:  # show it instead of crashing the TUI
            self.call_from_thread(self.show_error, f"Scan failed: {exc}")
            return
        self.call_from_thread(self.show_stats, statmod.compute(result))

    def show_error(self, message: str) -> None:
        self.query_one("#loading").display = False
        self.query_one("#panels").mount(Static(message, classes="error"))

    def show_stats(self, s: statmod.Stats) -> None:
        self.query_one("#loading").display = False
        panels = self.query_one("#panels")
        panels.set_class(self.size.width >= WIDE, "wide")
        panels.mount_all(
            Static(renderable, classes="panel")
            for renderable in (
                statmod.overview_table(s),
                statmod.formats_table(s),
                statmod.issues_table(s),
                statmod.others_table(s),
                statmod.commands_table(),
            )
        )


def run(lib: Library, use_cache: bool = True) -> None:
    Dashboard(lib, use_cache).run()
