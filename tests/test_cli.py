from muz import tags as tagmod
from muz.cli import main
from muz.library import Library
from muz.scanner import scan
from tests.conftest import needs_ffmpeg

pytestmark = needs_ffmpeg


def test_dry_run_changes_nothing(make_track, capsys):
    p = make_track("A/L/01.flac", TITLE="t", ARTIST="A feat. B")
    before = p.read_bytes()
    assert main([str(make_track.root), "--artists"]) == 0
    assert p.read_bytes() == before
    out = capsys.readouterr().out
    assert "Dry run" in out
    assert (make_track.root / ".muzrules.toml").is_file()
    assert not (make_track.root / ".muzhistory").exists()


def test_apply_history_undo(make_track, capsys):
    p = make_track("A/L/01.flac", TITLE="t", ARTIST="A feat. B")
    root = str(make_track.root)
    assert main([root, "--artists", "--apply", "--auto", "--yes"]) == 0
    assert tagmod.read(p)[1]["ARTISTS"] == ["A", "B"]
    assert main([root, "--history"]) == 0
    assert "split-artists" in capsys.readouterr().out
    assert main([root, "--undo", "1", "--yes"]) == 0
    assert "ARTISTS" not in tagmod.read(p)[1]


def test_apply_without_terminal_needs_auto(make_track):
    make_track("A/L/01.flac", TITLE="t", ARTIST="A feat. B")
    assert main([str(make_track.root), "--artists", "--apply"]) == 2


def test_stats_and_reports(make_track, capsys):
    make_track("A/L/01.flac", TITLE="t", ARTIST="Элджей", ALBUMARTIST="Элджей", ALBUM="L")
    make_track("B/L/01.mp3", TITLE="u", ARTIST="Eldzhey")
    make_track("B/L/02.m4a")
    (make_track.root / "A/L/cover.jpg").write_bytes(b"x")
    root = str(make_track.root)
    assert main([root, "--stats"]) == 0
    out = capsys.readouterr().out
    assert "FLAC" in out and "read-only" in out and ".jpg" in out
    assert main([root, "--report", "artists"]) == 0
    assert "Possibly the same artist" in capsys.readouterr().out
    assert main([root, "--search", "eldz"]) == 0


def test_hidden_service_folders_are_not_scanned(make_track):
    make_track("A/L/01.flac", TITLE="t")
    make_track(".muztrash/001/A/L/01.flac", TITLE="t")
    result = scan(Library.open(make_track.root))
    assert [t.rel for t in result.tracks] == ["A/L/01.flac"]


def test_cache_is_reused(make_track):
    make_track("A/L/01.flac", TITLE="t")
    lib = Library.open(make_track.root)
    scan(lib)
    calls = []
    scan(lib, progress=lambda d, t: calls.append((d, t)))
    assert calls[0] == (1, 1)  # everything came from the cache
