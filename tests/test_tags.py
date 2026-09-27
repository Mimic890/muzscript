import pytest
from mutagen.id3 import ID3

from muz import tags as tagmod
from tests.conftest import PNG, needs_ffmpeg

pytestmark = needs_ffmpeg


@pytest.mark.parametrize("ext", [".mp3", ".flac"])
def test_roundtrip_multivalue(make_track, ext):
    path = make_track(
        f"A/B/01{ext}",
        TITLE="Song",
        ARTIST="A feat. B",
        ARTISTS=["A", "B"],
        GENRE=["Rock", "Pop"],
        TRACKNUMBER="3",
        TRACKTOTAL="12",
        DISCNUMBER="1",
        LYRICS="line1\nline2",
        ISRC="USRC17607839",
        MUSICBRAINZ_ALBUMID="abc",
        cover=PNG,
    )
    info, tags, has_cover = tagmod.read(path)
    assert tags["ARTISTS"] == ["A", "B"]
    assert tags["GENRE"] == ["Rock", "Pop"]
    assert tags["TRACKNUMBER"] == ["3"] and tags["TRACKTOTAL"] == ["12"]
    assert tags["LYRICS"] == ["line1\nline2"]
    assert tags["MUSICBRAINZ_ALBUMID"] == ["abc"]
    assert has_cover
    assert tagmod.read_cover(path).data == PNG
    assert info.duration > 10


def test_mp3_is_saved_as_id3v24(make_track):
    path = make_track("a.mp3", TITLE="x")
    assert ID3(path).version[:2] == (2, 4)


def test_changing_track_total_keeps_number(make_track):
    path = make_track("a.mp3", TRACKNUMBER="5")
    w = tagmod.TagWriter(path)
    w.set("TRACKTOTAL", ["9"])
    w.save()
    _, tags, _ = tagmod.read(path)
    assert tags["TRACKNUMBER"] == ["5"] and tags["TRACKTOTAL"] == ["9"]


def test_delete_field(make_track):
    path = make_track("a.flac", COMMENT="junk", TITLE="t")
    w = tagmod.TagWriter(path)
    w.set("COMMENT", [])
    w.save()
    assert "COMMENT" not in tagmod.read(path)[1]


def test_other_formats_are_read_only(make_track):
    path = make_track("a.m4a")
    info, _, _ = tagmod.read(path)
    assert info.duration > 10 and not info.lossless
    with pytest.raises(tagmod.TagError):
        tagmod.TagWriter(path)


def test_alac_is_lossless(make_track):
    path = make_track("a.m4a", kind=".alac.m4a")
    assert tagmod.read(path)[0].lossless


def test_mp3_audio_hash_ignores_tags(make_track):
    a = make_track("a.mp3", TITLE="one")
    b = make_track("b.mp3", TITLE="two, with a much longer title", cover=PNG)
    assert a.read_bytes() != b.read_bytes()
    assert tagmod.mp3_audio_hash(a) == tagmod.mp3_audio_hash(b)


def test_flac_md5_survives_retag(make_track):
    a = make_track("a.flac", TITLE="one")
    b = make_track("b.flac", TITLE="two", cover=PNG)
    assert tagmod.read(a)[0].audio_md5 == tagmod.read(b)[0].audio_md5 != ""
