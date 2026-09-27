"""Test fixtures: small real audio files generated with ffmpeg."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from muz import tags as tagmod

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

ENCODERS = {
    ".flac": ["-c:a", "flac"],
    ".mp3": ["-c:a", "libmp3lame", "-b:a", "128k"],
    ".m4a": ["-c:a", "aac", "-b:a", "96k"],
    ".alac.m4a": ["-c:a", "alac"],
    ".ogg": ["-c:a", "libvorbis"],
    ".opus": ["-c:a", "libopus"],
}


@pytest.fixture(scope="session")
def audio_bank(tmp_path_factory) -> dict[tuple[str, int], Path]:
    """Pink noise per (format, seed), generated once and copied by make_track.

    Noise instead of sine tones: pure tones all fingerprint alike in Chromaprint.
    """
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    return {"dir": tmp_path_factory.mktemp("bank")}


def _generate(bank: dict, kind: str, seed: int, seconds: int) -> Path:
    key = (kind, seed, seconds)
    if key in bank:
        return bank[key]
    out = bank["dir"] / f"{seed}_{seconds}{kind}"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", f"anoisesrc=duration={seconds}:color=pink:seed={seed}:sample_rate=44100", "-ac", "2",
         *ENCODERS[kind], str(out)],
        check=True,
    )
    bank[key] = out
    return out


@pytest.fixture
def make_track(audio_bank, tmp_path):
    """make_track("Artist/Album/01.flac", seed=1, TITLE=["x"], ...) -> Path in tmp library."""
    lib = tmp_path / "music"
    lib.mkdir(exist_ok=True)

    def make(rel: str, *, seed: int = 440, seconds: int = 12, kind: str | None = None, cover: bytes | None = None, **tags):
        dst = lib / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        kind = kind or dst.suffix.lower()
        shutil.copy(_generate(audio_bank, kind, seed, seconds), dst)
        if dst.suffix.lower() in (".mp3", ".flac") and (tags or cover):
            w = tagmod.TagWriter(dst)
            for k, v in tags.items():
                w.set(k, v if isinstance(v, list) else [v])
            if cover:
                w.set_cover(tagmod.Picture(cover, "image/png"))
            w.save()
        return dst

    make.root = lib
    return make


PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)
