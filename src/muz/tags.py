"""One tag model for every format.

Tags are a dict of upper-case Vorbis-style field names to lists of values
(``{"ARTISTS": ["A", "B"], "TITLE": ["Song"]}``). All formats mutagen knows
can be read; only MP3 and FLAC can be written. MP3 is always saved as
ID3v2.4, the only ID3 version that stores multi-valued frames properly.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from pathlib import Path

import mutagen
from mutagen import id3
from mutagen.apev2 import APEv2File
from mutagen.asf import ASF
from mutagen.flac import FLAC
from mutagen.flac import Picture as FlacPicture
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm

from muz.formats import LOSSLESS_EXTS, WRITABLE_EXTS

Tags = dict[str, list[str]]


class TagError(Exception):
    pass


@dataclass
class Picture:
    data: bytes
    mime: str = "image/jpeg"
    type: int = 3  # front cover


@dataclass
class AudioInfo:
    codec: str = ""
    duration: float = 0.0
    bitrate: int = 0  # bits per second
    sample_rate: int = 0
    bits: int = 0
    channels: int = 0
    lossless: bool = False
    # FLAC stores the MD5 of the decoded audio in STREAMINFO; it survives retagging.
    audio_md5: str = ""


# --------------------------------------------------------------------------
# ID3 <-> generic names
# --------------------------------------------------------------------------

ID3_TEXT = {
    "TITLE": "TIT2",
    "ARTIST": "TPE1",
    "ALBUMARTIST": "TPE2",
    "ALBUM": "TALB",
    "GENRE": "TCON",
    "DATE": "TDRC",
    "ORIGINALDATE": "TDOR",
    "COMPOSER": "TCOM",
    "LYRICIST": "TEXT",
    "CONDUCTOR": "TPE3",
    "REMIXER": "TPE4",
    "BPM": "TBPM",
    "ISRC": "TSRC",
    "COPYRIGHT": "TCOP",
    "ORGANIZATION": "TPUB",
    "ARTISTSORT": "TSOP",
    "ALBUMARTISTSORT": "TSO2",
    "TITLESORT": "TSOT",
    "ALBUMSORT": "TSOA",
    "GROUPING": "TIT1",
    "SUBTITLE": "TIT3",
    "MEDIA": "TMED",
    "MOOD": "TMOO",
    "LANGUAGE": "TLAN",
    "KEY": "TKEY",
    "ENCODEDBY": "TENC",
}
ID3_TEXT_REVERSE = {v: k for k, v in ID3_TEXT.items()}

# TXXX descriptions used by MusicBrainz Picard, which Navidrome also reads.
TXXX_NAMES = {
    "MUSICBRAINZ_ARTISTID": "MusicBrainz Artist Id",
    "MUSICBRAINZ_ALBUMID": "MusicBrainz Album Id",
    "MUSICBRAINZ_ALBUMARTISTID": "MusicBrainz Album Artist Id",
    "MUSICBRAINZ_RELEASEGROUPID": "MusicBrainz Release Group Id",
    "MUSICBRAINZ_RELEASETRACKID": "MusicBrainz Release Track Id",
    "RELEASETYPE": "MusicBrainz Album Type",
    "RELEASESTATUS": "MusicBrainz Album Status",
    "RELEASECOUNTRY": "MusicBrainz Album Release Country",
    "BARCODE": "BARCODE",
    "CATALOGNUMBER": "CATALOGNUMBER",
}
TXXX_REVERSE = {v.upper(): k for k, v in TXXX_NAMES.items()}


def _split_pair(value: str) -> tuple[str, str]:
    """'3/12' -> ('3', '12')."""
    num, _, total = str(value).partition("/")
    return num.strip(), total.strip()


def _id3_read(tags: id3.ID3) -> Tags:
    out: Tags = {}

    def add(key: str, values) -> None:
        vals = [str(v) for v in values if str(v).strip() != ""]
        if vals:
            out.setdefault(key, []).extend(vals)

    for frame in tags.values():
        fid = frame.FrameID
        if fid == "TCON":
            add("GENRE", frame.genres)
        elif fid in ID3_TEXT_REVERSE:
            add(ID3_TEXT_REVERSE[fid], frame.text)
        elif fid == "TRCK":
            num, total = _split_pair(frame.text[0] if frame.text else "")
            add("TRACKNUMBER", [num])
            add("TRACKTOTAL", [total])
        elif fid == "TPOS":
            num, total = _split_pair(frame.text[0] if frame.text else "")
            add("DISCNUMBER", [num])
            add("DISCTOTAL", [total])
        elif fid == "TXXX":
            desc = frame.desc.upper()
            add(TXXX_REVERSE.get(desc, desc), frame.text)
        elif fid == "USLT":
            add("LYRICS", [frame.text])
        elif fid == "COMM":
            if frame.desc == "" or frame.desc.upper() == "DESCRIPTION":
                add("COMMENT" if frame.desc == "" else "DESCRIPTION", frame.text)
        elif fid == "WXXX":
            add("URL", [frame.url])
        elif fid == "UFID" and frame.owner == "http://musicbrainz.org":
            add("MUSICBRAINZ_TRACKID", [frame.data.decode("ascii", "ignore")])
    return out


def _id3_set(tags: id3.ID3, key: str, values: list[str]) -> None:
    enc = id3.Encoding.UTF8
    if key in ("TRACKNUMBER", "TRACKTOTAL", "DISCNUMBER", "DISCTOTAL"):
        fid = "TRCK" if key.startswith("TRACK") else "TPOS"
        current = tags.get(fid)
        num, total = _split_pair(current.text[0] if current and current.text else "")
        if key.endswith("NUMBER"):
            num = values[0] if values else ""
        else:
            total = values[0] if values else ""
        tags.delall(fid)
        if num or total:
            text = f"{num}/{total}" if total else num
            tags.add(getattr(id3, fid)(encoding=enc, text=[text]))
        return

    if key in ID3_TEXT:
        fid = ID3_TEXT[key]
        tags.delall(fid)
        if values:
            tags.add(getattr(id3, fid)(encoding=enc, text=list(values)))
    elif key == "LYRICS":
        tags.delall("USLT")
        if values:
            tags.add(id3.USLT(encoding=enc, lang="XXX", desc="", text=values[0]))
    elif key == "COMMENT":
        for frame in list(tags.getall("COMM")):
            if frame.desc == "":
                tags.delall(frame.HashKey)
        if values:
            tags.add(id3.COMM(encoding=enc, lang="XXX", desc="", text=list(values)))
    elif key == "URL":
        tags.delall("WXXX")
        if values:
            tags.add(id3.WXXX(encoding=enc, desc="", url=values[0]))
    elif key == "MUSICBRAINZ_TRACKID":
        tags.delall("UFID:http://musicbrainz.org")
        if values:
            tags.add(id3.UFID(owner="http://musicbrainz.org", data=values[0].encode("ascii", "ignore")))
    else:
        desc = TXXX_NAMES.get(key, key)
        for frame in list(tags.getall("TXXX")):
            if frame.desc.upper() == desc.upper():
                tags.delall(frame.HashKey)
        if key == "DESCRIPTION":
            for frame in list(tags.getall("COMM")):
                if frame.desc.upper() == "DESCRIPTION":
                    tags.delall(frame.HashKey)
        if values:
            tags.add(id3.TXXX(encoding=enc, desc=desc, text=list(values)))


def _id3_cover(tags: id3.ID3 | None) -> Picture | None:
    if not tags:
        return None
    pics = tags.getall("APIC")
    if not pics:
        return None
    pic = next((p for p in pics if p.type == 3), pics[0])
    return Picture(pic.data, pic.mime or "image/jpeg", int(pic.type))


# --------------------------------------------------------------------------
# MP4 (read only)
# --------------------------------------------------------------------------

MP4_ATOMS = {
    "\xa9nam": "TITLE",
    "\xa9ART": "ARTIST",
    "aART": "ALBUMARTIST",
    "\xa9alb": "ALBUM",
    "\xa9gen": "GENRE",
    "\xa9day": "DATE",
    "\xa9wrt": "COMPOSER",
    "\xa9lyr": "LYRICS",
    "\xa9cmt": "COMMENT",
    "\xa9grp": "GROUPING",
    "cprt": "COPYRIGHT",
    "soar": "ARTISTSORT",
    "soaa": "ALBUMARTISTSORT",
    "sonm": "TITLESORT",
    "soal": "ALBUMSORT",
    "\xa9too": "ENCODEDBY",
}


def _mp4_read(audio: MP4) -> Tags:
    out: Tags = {}
    tags = audio.tags or {}
    for atom, values in tags.items():
        if atom in MP4_ATOMS:
            out[MP4_ATOMS[atom]] = [str(v) for v in values]
        elif atom in ("trkn", "disk") and values:
            num, total = values[0]
            prefix = "TRACK" if atom == "trkn" else "DISC"
            if num:
                out[f"{prefix}NUMBER"] = [str(num)]
            if total:
                out[f"{prefix}TOTAL"] = [str(total)]
        elif atom == "tmpo" and values:
            out["BPM"] = [str(values[0])]
        elif atom.startswith("----:"):
            name = atom.rsplit(":", 1)[-1].upper()
            name = TXXX_REVERSE.get(name, name)
            vals = []
            for v in values:
                raw = bytes(v) if isinstance(v, MP4FreeForm) else v
                vals.append(raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else str(raw))
            out[name] = vals
    return out


def _mp4_cover(audio: MP4) -> Picture | None:
    covers = (audio.tags or {}).get("covr")
    if not covers:
        return None
    cover = covers[0]
    mime = "image/png" if cover.imageformat == MP4Cover.FORMAT_PNG else "image/jpeg"
    return Picture(bytes(cover), mime)


# --------------------------------------------------------------------------
# Vorbis comments (FLAC, Ogg Vorbis, Opus), APEv2, ASF
# --------------------------------------------------------------------------

VORBIS_ALIASES = {"UNSYNCEDLYRICS": "LYRICS", "YEAR": "DATE", "LABEL": "ORGANIZATION", "TOTALTRACKS": "TRACKTOTAL", "TOTALDISCS": "DISCTOTAL"}


def _vorbis_read(comments) -> Tags:
    out: Tags = {}
    if not comments:
        return out
    for key, value in comments:
        key = key.upper()
        if key == "METADATA_BLOCK_PICTURE":
            continue
        key = VORBIS_ALIASES.get(key, key)
        if key in ("TRACKNUMBER", "DISCNUMBER") and "/" in value:
            num, total = _split_pair(value)
            out.setdefault(key, []).append(num)
            if total:
                out.setdefault(key.replace("NUMBER", "TOTAL"), []).append(total)
            continue
        if value.strip():
            out.setdefault(key, []).append(value)
    return out


def _vorbis_cover(audio) -> Picture | None:
    for b64 in (audio.tags or {}).get("metadata_block_picture", []):
        try:
            pic = FlacPicture(base64.b64decode(b64))
            return Picture(pic.data, pic.mime or "image/jpeg", pic.type)
        except Exception:
            continue
    return None


APE_KEYS = {"YEAR": "DATE", "TRACK": "TRACKNUMBER", "DISC": "DISCNUMBER", "ALBUM ARTIST": "ALBUMARTIST"}


def _ape_read(tags) -> Tags:
    out: Tags = {}
    for key, value in (tags or {}).items():
        if getattr(value, "kind", 0) != 0:  # binary or external
            continue
        k = APE_KEYS.get(key.upper(), key.upper())
        vals = list(value)
        if k in ("TRACKNUMBER", "DISCNUMBER") and vals:
            num, total = _split_pair(vals[0])
            out[k] = [num]
            if total:
                out[k.replace("NUMBER", "TOTAL")] = [total]
            continue
        out[k] = [str(v) for v in vals]
    return out


def _ape_cover(tags) -> Picture | None:
    value = (tags or {}).get("Cover Art (Front)")
    if value is None:
        return None
    raw = bytes(value.value)
    _, _, data = raw.partition(b"\x00")
    mime = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
    return Picture(data, mime)


ASF_KEYS = {
    "Title": "TITLE",
    "Author": "ARTIST",
    "WM/AlbumArtist": "ALBUMARTIST",
    "WM/AlbumTitle": "ALBUM",
    "WM/Genre": "GENRE",
    "WM/Year": "DATE",
    "WM/TrackNumber": "TRACKNUMBER",
    "WM/PartOfSet": "DISCNUMBER",
    "WM/Composer": "COMPOSER",
    "WM/Lyrics": "LYRICS",
    "WM/ISRC": "ISRC",
    "WM/Publisher": "ORGANIZATION",
    "Copyright": "COPYRIGHT",
    "Description": "COMMENT",
}


def _asf_read(audio: ASF) -> Tags:
    out: Tags = {}
    for key, values in (audio.tags or {}).items():
        if key in ASF_KEYS:
            out[ASF_KEYS[key]] = [str(v) for v in values]
    return out


# --------------------------------------------------------------------------
# Public reading API
# --------------------------------------------------------------------------


def _open(path: Path):
    try:
        audio = mutagen.File(path)
    except Exception as exc:  # mutagen raises many different types
        raise TagError(f"{type(exc).__name__}: {exc}") from exc
    if audio is None:
        raise TagError("unknown or unsupported file type")
    return audio


def _info(path: Path, audio) -> AudioInfo:
    info = audio.info
    codec = getattr(info, "codec", "") or type(audio).__name__.lower()
    ext = path.suffix.lower()
    lossless = ext in LOSSLESS_EXTS or (isinstance(audio, MP4) and "alac" in codec.lower())
    md5 = ""
    if isinstance(audio, FLAC) and info.md5_signature:
        md5 = f"{info.md5_signature:032x}"
    return AudioInfo(
        codec=codec,
        duration=float(getattr(info, "length", 0.0) or 0.0),
        bitrate=int(getattr(info, "bitrate", 0) or 0),
        sample_rate=int(getattr(info, "sample_rate", 0) or 0),
        bits=int(getattr(info, "bits_per_sample", 0) or 0),
        channels=int(getattr(info, "channels", 0) or 0),
        lossless=lossless,
        audio_md5=md5,
    )


def _generic_tags(audio) -> Tags:
    if isinstance(audio, MP4):
        return _mp4_read(audio)
    if isinstance(audio, ASF):
        return _asf_read(audio)
    if isinstance(audio, APEv2File):
        return _ape_read(audio.tags)
    tags = audio.tags
    if isinstance(tags, id3.ID3):
        return _id3_read(tags)
    if tags is not None and hasattr(tags, "keys") and not isinstance(tags, dict):
        try:
            return _vorbis_read(list(tags))
        except Exception:
            pass
    return {}


def _generic_cover(audio) -> Picture | None:
    if isinstance(audio, FLAC):
        pics = audio.pictures
        if pics:
            pic = next((p for p in pics if p.type == 3), pics[0])
            return Picture(pic.data, pic.mime or "image/jpeg", pic.type)
        return _vorbis_cover(audio)
    if isinstance(audio, MP4):
        return _mp4_cover(audio)
    if isinstance(audio, APEv2File):
        return _ape_cover(audio.tags)
    if isinstance(audio.tags, id3.ID3):
        return _id3_cover(audio.tags)
    if hasattr(audio, "tags") and audio.tags is not None and not isinstance(audio, ASF):
        try:
            return _vorbis_cover(audio)
        except Exception:
            return None
    return None


def read(path: Path) -> tuple[AudioInfo, Tags, bool]:
    """Return audio info, tags and whether an embedded cover exists."""
    audio = _open(path)
    return _info(path, audio), _generic_tags(audio), _generic_cover(audio) is not None


def read_cover(path: Path) -> Picture | None:
    return _generic_cover(_open(path))


def mp3_audio_hash(path: Path) -> str:
    """MD5 of the MPEG frames only, so retagged copies still match."""
    with path.open("rb") as fh:
        data = fh.read()
    start = 0
    if data[:3] == b"ID3" and len(data) >= 10:
        size = (data[6] << 21) | (data[7] << 14) | (data[8] << 7) | data[9]
        start = 10 + size + (10 if data[5] & 0x10 else 0)
    end = len(data)
    if end - start >= 128 and data[end - 128 : end - 125] == b"TAG":
        end -= 128
    if data[end - 32 : end - 24] == b"APETAGEX":
        # APEv2 footer: size field includes the items and footer, not the header.
        size = int.from_bytes(data[end - 20 : end - 16], "little")
        end -= size
        if data[end - 32 : end - 24] == b"APETAGEX":
            end -= 32
    return hashlib.md5(data[start:end]).hexdigest()


# --------------------------------------------------------------------------
# Writing (MP3 and FLAC only)
# --------------------------------------------------------------------------


class TagWriter:
    """Edit tags of one MP3 or FLAC file; nothing is written before save()."""

    def __init__(self, path: Path):
        self.path = path
        ext = path.suffix.lower()
        if ext not in WRITABLE_EXTS:
            raise TagError(f"muz only writes MP3 and FLAC, not {ext}")
        self.kind = ext
        try:
            if ext == ".flac":
                self._audio = FLAC(path)
                if self._audio.tags is None:
                    self._audio.add_tags()
            else:
                self._audio = MP3(path)
                if self._audio.tags is None:
                    self._audio.add_tags()
        except Exception as exc:
            raise TagError(f"{type(exc).__name__}: {exc}") from exc

    def read(self) -> Tags:
        if self.kind == ".flac":
            return _vorbis_read(list(self._audio.tags or []))
        return _id3_read(self._audio.tags)

    def get(self, key: str) -> list[str]:
        return list(self.read().get(key.upper(), []))

    def set(self, key: str, values: list[str]) -> None:
        key = key.upper()
        values = [v for v in values if v != ""]
        if self.kind == ".flac":
            tags = self._audio.tags
            # Drop aliases too (e.g. UNSYNCEDLYRICS for LYRICS), so the value is not shadowed.
            for alias, canonical in VORBIS_ALIASES.items():
                if canonical == key and alias in tags:
                    del tags[alias]
            if key in tags:
                del tags[key]
            if values:
                tags[key] = values
        else:
            _id3_set(self._audio.tags, key, values)

    def cover(self) -> Picture | None:
        if self.kind == ".flac":
            return _generic_cover(self._audio)
        return _id3_cover(self._audio.tags)

    def set_cover(self, pic: Picture | None) -> None:
        """Replace all embedded pictures with `pic` (or remove them for None)."""
        if self.kind == ".flac":
            self._audio.clear_pictures()
            if pic:
                fp = FlacPicture()
                fp.type, fp.mime, fp.data, fp.desc = pic.type, pic.mime, pic.data, ""
                self._audio.add_picture(fp)
        else:
            self._audio.tags.delall("APIC")
            if pic:
                self._audio.tags.add(
                    id3.APIC(encoding=id3.Encoding.UTF8, mime=pic.mime, type=pic.type, desc="", data=pic.data)
                )

    def save(self) -> None:
        try:
            if self.kind == ".flac":
                self._audio.save()
            else:
                self._audio.save(v2_version=4)
        except Exception as exc:
            raise TagError(f"{type(exc).__name__}: {exc}") from exc


def write_all(path: Path, tags: Tags, cover: Picture | None) -> None:
    """Write a full tag set to a fresh MP3/FLAC file (used by conversion)."""
    writer = TagWriter(path)
    for key, values in tags.items():
        writer.set(key, values)
    if cover:
        writer.set_cover(cover)
    writer.save()
