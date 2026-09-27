import asyncio

from textual.widgets import Static

from muz.library import Library
from muz.ui.dashboard import Dashboard
from tests.conftest import needs_ffmpeg

pytestmark = needs_ffmpeg


def run_dashboard(root, size):
    async def go():
        app = Dashboard(Library.open(root))
        async with app.run_test(size=size) as pilot:
            for _ in range(100):
                await pilot.pause(0.05)
                if app.query(".panel"):
                    break
            panels = app.query_one("#panels")
            return len(app.query(".panel")), panels.has_class("wide"), app.query(Static)

    return asyncio.run(go())


def test_dashboard_shows_panels_and_adapts_width(make_track):
    make_track("A/L/01.flac", TITLE="t", ALBUMARTIST="A", ALBUM="L")
    make_track("A/L/02.m4a")
    count, wide, _ = run_dashboard(make_track.root, (140, 50))
    assert count == 5 and wide
    count, wide, _ = run_dashboard(make_track.root, (80, 50))
    assert count == 5 and not wide
