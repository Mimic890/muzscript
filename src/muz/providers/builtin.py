"""Built-in fallback: Deezer public API (tags, cover) + LRCLIB (lyrics). No account needed."""

from __future__ import annotations

from muz.providers.base import Found, Query, http_json

DEEZER = "https://api.deezer.com"
LRCLIB = "https://lrclib.net/api"


def _close(a: float, b: float, tolerance: float = 3.0) -> bool:
    return not a or not b or abs(a - b) <= tolerance


class BuiltinProvider:
    name = "builtin (Deezer + LRCLIB)"

    def _deezer_track(self, q: Query) -> dict | None:
        if q.isrc:
            data = http_json(f"{DEEZER}/track/isrc:{q.isrc}")
            if data and not data.get("error"):
                return data
        data = http_json(f"{DEEZER}/search", {"q": f'artist:"{q.artist}" track:"{q.title}"', "limit": 10})
        for item in (data or {}).get("data", []):
            if _close(item.get("duration", 0), q.duration):
                full = http_json(f"{DEEZER}/track/{item['id']}")
                return full if full and not full.get("error") else item
        return None

    def _tags(self, q: Query) -> tuple[dict[str, list[str]], str]:
        track = self._deezer_track(q)
        if not track:
            return {}, ""
        tags: dict[str, list[str]] = {}
        album = track.get("album") or {}
        if track.get("isrc"):
            tags["ISRC"] = [track["isrc"]]
        if track.get("bpm"):
            tags["BPM"] = [str(round(track["bpm"]))]
        if track.get("release_date"):
            tags["DATE"] = [track["release_date"]]
        cover = album.get("cover_xl") or album.get("cover_big") or ""
        if album.get("id"):
            full = http_json(f"{DEEZER}/album/{album['id']}") or {}
            genres = [g["name"] for g in (full.get("genres") or {}).get("data", []) if g.get("name")]
            if genres:
                tags["GENRE"] = genres
            if full.get("label"):
                tags["ORGANIZATION"] = [full["label"]]
            if full.get("upc"):
                tags["BARCODE"] = [full["upc"]]
            if full.get("nb_tracks"):
                tags["TRACKTOTAL"] = [str(full["nb_tracks"])]
            if full.get("release_date"):
                tags["DATE"] = [full["release_date"]]
            cover = full.get("cover_xl") or cover
        return tags, cover

    def _lyrics(self, q: Query) -> str:
        params = {"artist_name": q.artist, "track_name": q.title}
        if q.album:
            params["album_name"] = q.album
        if q.duration:
            params["duration"] = round(q.duration)
        data = http_json(f"{LRCLIB}/get", params)
        if not data or data.get("statusCode"):
            results = http_json(f"{LRCLIB}/search", {"artist_name": q.artist, "track_name": q.title}) or []
            data = next((r for r in results if _close(r.get("duration", 0), q.duration)), None)
        if not data:
            return ""
        return data.get("syncedLyrics") or data.get("plainLyrics") or ""

    def lookup(self, query: Query, want: set[str]) -> Found:
        found = Found(source="builtin")
        if want & {"tags", "cover"}:
            found.tags, found.cover_url = self._tags(query)
        if "lyrics" in want:
            found.lyrics = self._lyrics(query)
        return found
