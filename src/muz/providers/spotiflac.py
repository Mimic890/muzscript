"""Adapter to SpotiFLAC (https://github.com/BartolomeoRusso9/SpotiFLAC-Module-Version).

SpotiFLAC's metadata and lyrics functions live in its internal ``core``
package, which changes between major versions. This file is the only place
muz touches it; the version is pinned in pyproject.toml.
"""

from __future__ import annotations

import asyncio

from SpotiFLAC.core.lyrics import fetch_lyrics_async
from SpotiFLAC.core.metadata_enrichment import enrich_metadata_async

from muz.providers.base import Found, Query

# SpotiFLAC tag name -> muz tag name (the rest already match).
RENAME = {"UPC": "BARCODE", "ITUNESADVISORY": None}


class SpotiflacProvider:
    name = "SpotiFLAC"

    async def _lookup(self, q: Query, want: set[str]) -> Found:
        found = Found(source="spotiflac")
        if want & {"tags", "cover"}:
            try:
                meta = await enrich_metadata_async(
                    q.title,
                    q.artist,
                    isrc=q.isrc,
                    album_name=q.album,
                    duration_ms=int(q.duration * 1000),
                )
                for key, value in meta.as_tags().items():
                    key = RENAME.get(key, key)
                    if key and value:
                        found.tags[key] = [str(value)]
                found.cover_url = meta.cover_url_hd or ""
            except Exception:
                pass
        if "lyrics" in want:
            try:
                lyrics, _source = await fetch_lyrics_async(
                    q.title, q.artist, q.album, int(q.duration), isrc=q.isrc
                )
                found.lyrics = lyrics or ""
            except Exception:
                pass
        return found

    def lookup(self, query: Query, want: set[str]) -> Found:
        return asyncio.run(self._lookup(query, want))
