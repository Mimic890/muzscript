"""Per-library rules, read from <library>/.muzrules.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_RULES = """\
# muz rules for this music library.
# muz creates this file once and never rewrites it. Edit it freely.

[artists]
# Strings that separate several artists inside one ARTIST tag (case-insensitive).
separators = [", ", "; ", " / ", " & ", " feat. ", " feat ", " ft. ", " ft ", " featuring ", " x ", " vs. "]

# Names that contain a separator but are ONE artist (case-insensitive).
exceptions = [
    "Simon & Garfunkel",
    "Earth, Wind & Fire",
    "Tyler, The Creator",
    "Crosby, Stills, Nash & Young",
    "Florence + The Machine",
    "Hall & Oates",
]

[artists.aliases]
# Merge spellings of the same artist: "Canonical name" = ["variant", "another variant"]
# "Eldzhey" = ["Allj", "Элджей"]

[genres]
separators = [", ", "; ", " / "]

[genres.aliases]
# "Canonical genre" = ["variant", ...]
"Hip-Hop" = ["hip hop", "hiphop"]
"R&B" = ["rnb", "r'n'b"]

[clean]
# Tag values containing any of these strings are removed.
junk = ["SpotiFLAC", "github.com/"]
# Tags checked for junk.
junk_fields = ["DESCRIPTION", "COMMENT", "URL"]
# Remove [ar:], [ti:], [by:] ... header lines from embedded lyrics.
strip_lrc_headers = true

[embed]
# Image names (without extension) used as album cover, in order of preference.
cover_names = ["cover", "folder", "front", "album"]

[paths]
# File path relative to the library root. Fields:
#   {albumartist} {album} {title} {artist} {year} {genre}
#   {track} {disc} {disctotal} {tracktotal}
#   {tracknum}  -> "07", or "2-07" on multi-disc albums
# Python format specs work: {track:02d}
template = "{albumartist}/{album}/{tracknum} - {title}"

[convert]
# MP3 encoding: "V0" (LAME VBR ~245 kbps) or "320" (CBR 320 kbps).
mp3_quality = "V0"
# FLAC compression level, 0-8 (8 = smallest, slowest; quality is identical).
flac_compression = 8

[dupes]
# Two tracks are "the same length" if they differ by at most this many seconds.
duration_tolerance = 3.0

[fetch]
# "auto" uses SpotiFLAC when it is installed and falls back to the built-in
# LRCLIB + Deezer client. "spotiflac" or "builtin" force one of them.
provider = "auto"
"""


@dataclass
class Rules:
    artist_separators: list[str] = field(default_factory=list)
    artist_exceptions: list[str] = field(default_factory=list)
    artist_aliases: dict[str, list[str]] = field(default_factory=dict)
    genre_separators: list[str] = field(default_factory=list)
    genre_aliases: dict[str, list[str]] = field(default_factory=dict)
    junk: list[str] = field(default_factory=list)
    junk_fields: list[str] = field(default_factory=list)
    strip_lrc_headers: bool = True
    cover_names: list[str] = field(default_factory=list)
    path_template: str = ""
    mp3_quality: str = "V0"
    flac_compression: int = 8
    duration_tolerance: float = 3.0
    provider: str = "auto"

    @classmethod
    def from_dict(cls, data: dict) -> Rules:
        artists = data.get("artists", {})
        genres = data.get("genres", {})
        clean = data.get("clean", {})
        embed = data.get("embed", {})
        paths = data.get("paths", {})
        convert = data.get("convert", {})
        dupes = data.get("dupes", {})
        fetch = data.get("fetch", {})
        rules = cls(
            artist_separators=list(artists.get("separators", [])),
            artist_exceptions=list(artists.get("exceptions", [])),
            artist_aliases=_aliases(artists.get("aliases", {})),
            genre_separators=list(genres.get("separators", [])),
            genre_aliases=_aliases(genres.get("aliases", {})),
            junk=list(clean.get("junk", [])),
            junk_fields=[f.upper() for f in clean.get("junk_fields", [])],
            strip_lrc_headers=bool(clean.get("strip_lrc_headers", True)),
            cover_names=[n.lower() for n in embed.get("cover_names", [])],
            path_template=str(paths.get("template", "")),
            mp3_quality=str(convert.get("mp3_quality", "V0")).upper(),
            flac_compression=int(convert.get("flac_compression", 8)),
            duration_tolerance=float(dupes.get("duration_tolerance", 3.0)),
            provider=str(fetch.get("provider", "auto")).lower(),
        )
        rules.validate()
        return rules

    def validate(self) -> None:
        if self.mp3_quality not in {"V0", "320"}:
            raise ValueError(f'convert.mp3_quality must be "V0" or "320", got "{self.mp3_quality}"')
        if not 0 <= self.flac_compression <= 8:
            raise ValueError("convert.flac_compression must be between 0 and 8")
        if self.provider not in {"auto", "spotiflac", "builtin"}:
            raise ValueError('fetch.provider must be "auto", "spotiflac" or "builtin"')
        if not self.path_template:
            raise ValueError("paths.template is empty")


def _aliases(raw: dict) -> dict[str, list[str]]:
    return {str(k): [str(v) for v in vals] for k, vals in raw.items()}


def default_rules() -> Rules:
    return Rules.from_dict(tomllib.loads(DEFAULT_RULES))


def load_rules(path: Path) -> tuple[Rules, bool]:
    """Load rules; create the file with defaults when it is missing.

    Returns the rules and whether the file was just created.
    """
    created = False
    if not path.exists():
        path.write_text(DEFAULT_RULES, encoding="utf-8")
        created = True
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    # Missing sections fall back to the defaults, so an old or trimmed file keeps working.
    merged = tomllib.loads(DEFAULT_RULES)
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return Rules.from_dict(merged), created
