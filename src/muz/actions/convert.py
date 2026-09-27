"""--convert: re-encode audio with ffmpeg, keeping every tag, the lyrics and the cover.

Modes:
  auto  every file that is not MP3/FLAC -> FLAC if its source is lossless, else MP3
  mp3   every file that is not MP3 (FLAC included) -> MP3
  flac  every lossless file that is not FLAC -> FLAC (lossy files are skipped:
        re-encoding them to FLAC only makes them bigger)

ffmpeg only encodes the audio; tags and pictures are copied with mutagen, so
multi-valued tags survive. The original goes to .muztrash/.
"""

from __future__ import annotations

import shutil
import subprocess
from collections import defaultdict
from pathlib import Path, PurePosixPath

from muz import tags as tagmod
from muz.actions import Context
from muz.config import Rules
from muz.plan import Convert
from muz.ui.console import console, esc
from muz.ui.review import Proposal

MODES = ("auto", "mp3", "flac")
# Values describing the old encoding; wrong after re-encoding.
DROP_TAGS = {"ENCODER", "ENCODEDBY", "ENCODING", "ITUNSMPB", "ITUNNORM", "ITUNPGAP", "ENCODER SETTINGS", "ENCODERSETTINGS"}


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def target_format(track, mode: str) -> str | None:
    ext = track.ext
    if mode == "mp3":
        return "mp3" if ext != ".mp3" else None
    if mode == "flac":
        return "flac" if track.info.lossless and ext != ".flac" else None
    if ext in (".mp3", ".flac"):
        return None
    return "flac" if track.info.lossless else "mp3"


def ffmpeg_args(src: Path, dst: Path, fmt: str, rules: Rules, sample_rate: int) -> list[str]:
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(src),
            "-map", "0:a:0", "-map_metadata", "-1", "-vn"]
    if fmt == "mp3":
        args += ["-c:a", "libmp3lame"]
        args += ["-q:a", "0"] if rules.mp3_quality == "V0" else ["-b:a", "320k"]
        if sample_rate > 48000:  # LAME supports at most 48 kHz
            args += ["-ar", "44100" if sample_rate % 44100 == 0 else "48000"]
        args += ["-id3v2_version", "4"]
    else:
        args += ["-c:a", "flac", "-compression_level", str(rules.flac_compression)]
        if src.suffix.lower() in (".dsf", ".dff"):  # DSD: FLAC cannot store MHz rates
            args += ["-ar", "176400", "-sample_fmt", "s32"]
    return args + [str(dst)]


def make_converter(rules: Rules):
    def convert_file(src: Path, dst: Path, fmt: str) -> None:
        if dst.exists():
            raise FileExistsError(f"target already exists: {dst}")
        info, tags, _ = tagmod.read(src)
        cover = tagmod.read_cover(src)
        tmp = dst.with_name(f".{dst.stem}.muztmp{dst.suffix}")
        try:
            proc = subprocess.run(ffmpeg_args(src, tmp, fmt, rules, info.sample_rate), capture_output=True, text=True)
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg failed: {proc.stderr.strip()[-300:]}")
            clean = {k: v for k, v in tags.items() if k not in DROP_TAGS}
            tagmod.write_all(tmp, clean, cover)
            tmp.rename(dst)
        finally:
            if tmp.exists():
                tmp.unlink()

    return convert_file


def plan(ctx: Context, mode: str) -> list[Proposal]:
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg is not installed (apt install ffmpeg), or use the Docker image")
    lib = ctx.lib
    by_folder: dict[tuple[str, str, str], list[Convert]] = defaultdict(list)
    skipped = []
    planned: set[str] = set()
    for t in ctx.scan.tracks:
        if t.error:
            continue
        fmt = target_format(t, mode)
        if fmt is None:
            if mode == "flac" and not t.info.lossless and t.ext != ".flac":
                skipped.append(t.rel)
            continue
        dst = str(PurePosixPath(t.rel).with_suffix(f".{fmt}"))
        if dst in planned or lib.abs(dst).exists():
            console.print(f"[warn]Skipped {esc(t.rel)}: {esc(dst)} already exists.[/]")
            continue
        planned.add(dst)
        folder = str(PurePosixPath(t.rel).parent)
        by_folder[(folder, t.ext, fmt)].append(Convert(t.rel, dst, fmt, "convert"))
    if skipped:
        console.print(f"[dim]{len(skipped)} lossy file(s) not converted to FLAC (it would not improve them).[/]")

    quality = f"MP3 {'V0' if ctx.rules.mp3_quality == 'V0' else '320k'}"
    proposals = []
    for (folder, ext, fmt), ops in sorted(by_folder.items()):
        target = quality if fmt == "mp3" else f"FLAC (level {ctx.rules.flac_compression})"
        proposals.append(
            Proposal(
                title="Convert",
                current=[("Folder", folder), ("Format", f"{len(ops)} × {ext[1:].upper()}")],
                suggested=[target, "original files go to .muztrash/"],
                files=[op.rel for op in ops],
                build=lambda _v, ops=ops: list(ops),
                editable=False,
            )
        )
    return proposals
