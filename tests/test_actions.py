from pathlib import Path

from muz import plan as planmod
from muz import tags as tagmod
from muz.actions import Context, artists, clean, convert, dupes, embed, genres, rename
from muz.actions.clean import strip_lrc_headers
from muz.config import load_rules
from muz.history import list_sessions
from muz.library import Library
from muz.scanner import scan
from tests.conftest import PNG, needs_ffmpeg

pytestmark = needs_ffmpeg


def ctx_for(root: Path) -> Context:
    lib = Library.open(root)
    rules, _ = load_rules(lib.rules_file)
    return Context(lib, rules, scan(lib))


def accept_all(proposals):
    ops = []
    for p in proposals:
        ops.extend(p.build(p.suggested))
    return ops


def test_artists_split_and_undo(make_track):
    a = make_track("X/Al/01.flac", TITLE="t1", ARTIST="X feat. Y", ALBUMARTIST="X")
    b = make_track("X/Al/02.mp3", TITLE="t2", ARTIST="X feat. Y", ALBUMARTIST="X")
    make_track("X/Al/03.mp3", TITLE="t3", ARTIST="Simon & Garfunkel", ALBUMARTIST="X")
    ctx = ctx_for(make_track.root)
    proposals = artists.plan(ctx)
    assert len(proposals) == 1  # same problem in two files -> one question
    assert proposals[0].suggested == ["X", "Y"]
    result = planmod.apply(ctx.lib, accept_all(proposals), "split-artists")
    assert not result.errors and result.applied == 2
    for path in (a, b):
        tags = tagmod.read(path)[1]
        assert tags["ARTISTS"] == ["X", "Y"]
        assert tags["ARTIST"] == ["X feat. Y"]  # display value is kept
    assert result.session.path.name.startswith("001_") and result.session.path.name.endswith("_split-artists_2-changes")

    undo = planmod.undo(ctx.lib, result.session)
    assert not undo.errors
    assert "ARTISTS" not in tagmod.read(a)[1]
    assert [s.action for s in list_sessions(ctx.lib)] == ["split-artists", "undo-001"]


def test_existing_artists_left_alone(make_track):
    make_track("a.flac", TITLE="t", ARTIST="X, Y", ARTISTS=["X", "Y"])
    assert artists.plan(ctx_for(make_track.root)) == []


def test_genres(make_track):
    p = make_track("a.flac", TITLE="t", GENRE="Rock, hip hop")
    proposals = genres.plan(ctx_for(make_track.root))
    assert proposals[0].suggested == ["Rock", "Hip-Hop"]
    planmod.apply(Library.open(make_track.root), accept_all(proposals), "g")
    assert tagmod.read(p)[1]["GENRE"] == ["Rock", "Hip-Hop"]


def test_clean(make_track):
    p = make_track(
        "a.mp3",
        TITLE="  Song  ",
        DESCRIPTION="https://github.com/x/SpotiFLAC",
        LYRICS="[ar:Someone]\n[ti:Song]\n[offset:+100]\n[00:01.00]hello",
    )
    ctx = ctx_for(make_track.root)
    result = planmod.apply(ctx.lib, accept_all(clean.plan(ctx)), "clean")
    assert not result.errors
    tags = tagmod.read(p)[1]
    assert "DESCRIPTION" not in tags
    assert tags["TITLE"] == ["Song"]
    assert tags["LYRICS"] == ["[offset:+100]\n[00:01.00]hello"]


def test_strip_lrc_headers():
    assert strip_lrc_headers("[ar:a]\n\n[by:b]\n[00:00.10]x\n[ar:not header]") == "[00:00.10]x\n[ar:not header]"


def test_embed_cover_and_lyrics(make_track):
    p = make_track("A/B/01 - x.flac", TITLE="x")
    (p.parent / "cover.png").write_bytes(PNG)
    p.with_suffix(".lrc").write_text("[ti:x]\n[00:01.00]la", encoding="utf-8")
    ctx = ctx_for(make_track.root)
    result = planmod.apply(ctx.lib, accept_all(embed.plan(ctx)), "embed")
    assert not result.errors
    info, tags, has_cover = tagmod.read(p)
    assert has_cover and tags["LYRICS"] == ["[00:01.00]la"]
    planmod.undo(ctx.lib, result.session)
    assert not tagmod.read(p)[2]


def test_rename_moves_folder_with_cover_and_lrc(make_track):
    p = make_track("incoming/stuff/track.flac", TITLE="Song/Name", ALBUMARTIST="Band", ALBUM="LP", TRACKNUMBER="3")
    (p.parent / "cover.jpg").write_bytes(b"\xff\xd8\xff")
    p.with_suffix(".lrc").write_text("x")
    ctx = ctx_for(make_track.root)
    proposals = rename.plan(ctx)
    result = planmod.apply(ctx.lib, accept_all(proposals), "rename")
    assert not result.errors
    root = make_track.root
    assert (root / "Band/LP/03 - Song_Name.flac").is_file()
    assert (root / "Band/LP/03 - Song_Name.lrc").is_file()
    assert (root / "Band/LP/cover.jpg").is_file()
    assert not (root / "incoming").exists()  # emptied folders are removed
    planmod.undo(ctx.lib, result.session)
    assert p.is_file() and (p.parent / "cover.jpg").is_file()


def test_rename_skips_missing_albumartist_and_multidisc(make_track):
    make_track("a.flac", TITLE="t", ALBUM="LP")
    make_track("b.flac", TITLE="t2", ALBUMARTIST="Band", ALBUM="LP", TRACKNUMBER="1", DISCNUMBER="2", DISCTOTAL="2")
    ctx = ctx_for(make_track.root)
    ops = accept_all(rename.plan(ctx))
    assert [(o.src, o.dst) for o in ops] == [("b.flac", "Band/LP/2-01 - t2.flac")]


def test_rename_component_rules():
    assert rename.clean_component("...hidden") == "hidden"
    long = "я" * 200  # 400 bytes
    assert len(rename.clean_component(long, ".flac").encode()) <= 255


def test_dupes_exact_tags_and_trash(make_track):
    make_track("A/L/01.flac", seed=440, TITLE="Song", ARTIST="A")
    make_track("A/L2/01.flac", seed=440, TITLE="Other title", ARTIST="Z", cover=PNG)  # same audio
    make_track("A/L3/01.mp3", seed=440, TITLE="Song (Remastered 2011)", ARTIST="A feat. B")  # same by tags
    make_track("A/L4/01.mp3", seed=880, seconds=40, TITLE="Song", ARTIST="A")  # different length
    ctx = ctx_for(make_track.root)
    groups = dupes.find(ctx)
    assert len(groups) == 1
    group = groups[0]
    assert {t.rel for t in group.tracks} == {"A/L/01.flac", "A/L2/01.flac", "A/L3/01.mp3"}
    assert {"exact", "tags"} <= group.reasons
    best = group.tracks[dupes.best_index(group)]
    assert best.rel == "A/L2/01.flac"  # lossless and has a cover
    ops = dupes.review(groups, auto=True)
    result = planmod.apply(ctx.lib, ops, "remove-duplicates")
    assert not result.errors
    trash = list((make_track.root / ".muztrash").rglob("*.*"))
    assert len(trash) == 2
    planmod.undo(ctx.lib, result.session)
    assert (make_track.root / "A/L/01.flac").is_file()


def test_dupes_acoustic_split(make_track):
    make_track("a.flac", seed=440, TITLE="Song", ARTIST="A")
    make_track("b.mp3", seed=440, TITLE="Song", ARTIST="A")
    make_track("c.mp3", seed=3000, TITLE="Song", ARTIST="A")  # same tags, other sound
    groups = dupes.find(ctx_for(make_track.root), acoustic=True)
    assert [sorted(t.rel for t in g.tracks) for g in groups] == [["a.flac", "b.mp3"]]


def test_convert_keeps_tags_and_cover(make_track):
    src = make_track("A/L/01.m4a", kind=".alac.m4a")
    # m4a is read-only for muz, so tag it with mutagen directly
    from mutagen.mp4 import MP4, MP4Cover

    m = MP4(src)
    m["\xa9nam"] = ["Title"]
    m["\xa9ART"] = ["A feat. B"]
    m["trkn"] = [(2, 10)]
    m["covr"] = [MP4Cover(PNG, MP4Cover.FORMAT_PNG)]
    m.save()
    lossy = make_track("A/L/02.ogg")
    ctx = ctx_for(make_track.root)
    proposals = convert.plan(ctx, "auto")
    ops = accept_all(proposals)
    assert sorted((o.rel, o.dst) for o in ops) == [("A/L/01.m4a", "A/L/01.flac"), ("A/L/02.ogg", "A/L/02.mp3")]
    result = planmod.apply(ctx.lib, ops, "convert-auto", converter=convert.make_converter(ctx.rules))
    assert not result.errors, result.errors
    info, tags, has_cover = tagmod.read(make_track.root / "A/L/01.flac")
    assert info.lossless and tags["TITLE"] == ["Title"] and tags["TRACKNUMBER"] == ["2"] and tags["TRACKTOTAL"] == ["10"]
    assert has_cover
    assert (make_track.root / "A/L/02.mp3").is_file()
    assert not src.exists() and not lossy.exists()
    planmod.undo(ctx.lib, result.session)
    assert src.exists() and lossy.exists() and not (make_track.root / "A/L/01.flac").exists()


def test_convert_flac_mode_skips_lossy(make_track):
    make_track("a.ogg")
    make_track("b.m4a", kind=".alac.m4a")
    ops = accept_all(convert.plan(ctx_for(make_track.root), "flac"))
    assert [(o.rel, o.fmt) for o in ops] == [("b.m4a", "flac")]


def test_interactive_review(make_track, monkeypatch):
    from muz.ui import review as reviewmod

    make_track("a.flac", TITLE="t", ARTIST="A feat. B")
    make_track("b.flac", TITLE="t", ARTIST="C & D")
    make_track("c.flac", TITLE="t", ARTIST="E x F")
    proposals = artists.plan(ctx_for(make_track.root))
    answers = iter(["e", "A | B | Z", "s", "y"])
    monkeypatch.setattr(reviewmod, "ask", lambda prompt: next(answers))
    ops = reviewmod.review(proposals)
    assert [(o.rel, o.new) for o in ops] == [
        (proposals[0].files[0], ["A", "B", "Z"]),
        (proposals[2].files[0], proposals[2].suggested),
    ]


def test_interactive_dupes_choice(make_track, monkeypatch):
    make_track("a.flac", TITLE="Song", ARTIST="A")
    make_track("b.mp3", TITLE="Song", ARTIST="A")
    groups = dupes.find(ctx_for(make_track.root))
    answers = iter(["9", "2"])  # 9 is out of range and asked again
    monkeypatch.setattr(dupes, "ask", lambda prompt: next(answers))
    ops = dupes.review(groups, auto=False)
    kept = groups[0].tracks[1].rel
    assert [o.rel for o in ops] == [t.rel for t in groups[0].tracks if t.rel != kept]


def test_fetch_fills_only_missing(make_track, monkeypatch):
    from muz.actions import fetch
    from muz.providers.base import Found

    p = make_track("a.flac", TITLE="Song", ARTIST="A feat. B", GENRE="Rock")

    class Fake:
        name = "fake"

        def lookup(self, query, want):
            assert query.artist == "A" and query.title == "Song"
            return Found(tags={"GENRE": ["Pop"], "DATE": ["2020-01-01"]}, lyrics="[00:01.00]hi", source="fake")

    ctx = ctx_for(make_track.root)
    proposals = fetch.plan(ctx, Fake(), {"tags", "lyrics"})
    result = planmod.apply(ctx.lib, accept_all(proposals), "fetch")
    assert not result.errors
    tags = tagmod.read(p)[1]
    assert tags["GENRE"] == ["Rock"]  # not overwritten
    assert tags["DATE"] == ["2020-01-01"] and tags["LYRICS"] == ["[00:01.00]hi"]
