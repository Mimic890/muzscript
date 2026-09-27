"""--fetch tags,lyrics,covers: fill in what is missing from online sources.

Only empty fields are filled; existing values are never overwritten.
"""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from muz.actions import Context
from muz.actions.embed import image_mime
from muz.actions.split import split_value
from muz.plan import CoverEdit, TagEdit
from muz.providers import Provider, Query
from muz.providers.base import download_image
from muz.scanner import Track
from muz.tags import Picture
from muz.ui.review import Proposal

KINDS = ("tags", "lyrics", "covers")
FETCH_FIELDS = (
    "GENRE", "DATE", "ISRC", "ORGANIZATION", "COMPOSER", "LYRICIST", "COPYRIGHT",
    "BPM", "TRACKTOTAL", "DISCTOTAL", "BARCODE", "RELEASETYPE",
)


def parse_kinds(raw: str) -> set[str]:
    kinds = {k.strip().lower() for k in raw.split(",") if k.strip()}
    if "all" in kinds:
        return set(KINDS)
    unknown = kinds - set(KINDS)
    if unknown or not kinds:
        raise ValueError(f"--fetch takes a comma-separated list of: {', '.join(KINDS)} (or all)")
    return kinds


def _query(t: Track, ctx: Context) -> Query:
    artists = t.tags.get("ARTISTS") or t.tags.get("ARTIST") or t.tags.get("ALBUMARTIST") or [""]
    parts = split_value(artists[0], ctx.rules.artist_separators, ctx.rules.artist_exceptions)
    return Query(
        title=t.first("TITLE"),
        artist=parts[0] if parts else artists[0],
        album=t.first("ALBUM"),
        duration=t.info.duration,
        isrc=t.first("ISRC"),
    )


def plan(ctx: Context, provider: Provider, kinds: set[str], progress=None) -> list[Proposal]:
    jobs: list[tuple[Track, Query, set[str]]] = []
    for t in ctx.writable():
        query = _query(t, ctx)
        if not query.title or not query.artist:
            continue
        want = set()
        if "tags" in kinds and any(not t.tags.get(f) for f in FETCH_FIELDS):
            want.add("tags")
        if "lyrics" in kinds and not t.tags.get("LYRICS"):
            want.add("lyrics")
        if "covers" in kinds and not t.has_cover:
            want.add("cover")
        if want:
            jobs.append((t, query, want))

    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [(t, want, pool.submit(provider.lookup, q, want)) for t, q, want in jobs]
        for i, (t, want, fut) in enumerate(futures, 1):
            try:
                results.append((t, want, fut.result()))
            except Exception:
                pass
            if progress:
                progress(i, len(futures))

    tag_groups: dict[tuple[str, tuple], list[str]] = defaultdict(list)
    lyrics_edits: list[TagEdit] = []
    cover_groups: dict[str, list[str]] = defaultdict(list)
    for t, want, found in results:
        if "tags" in want:
            for field in FETCH_FIELDS:
                if not t.tags.get(field) and found.tags.get(field):
                    tag_groups[(field, tuple(found.tags[field]))].append(t.rel)
        if "lyrics" in want and found.lyrics.strip():
            lyrics_edits.append(TagEdit(t.rel, "LYRICS", [], [found.lyrics.strip()], found.source))
        if "cover" in want and found.cover_url:
            cover_groups[found.cover_url].append(t.rel)

    proposals = []
    for (field, values), files in sorted(tag_groups.items(), key=lambda kv: (kv[0][0], -len(kv[1]))):

        def build(vals, files=files, field=field):
            return [TagEdit(rel, field, [], list(vals), f"fetched ({provider.name})") for rel in files]

        proposals.append(
            Proposal(
                title=f"Fill {field}",
                current=[(field, "(empty)"), ("Example", files[0])],
                suggested=list(values),
                files=files,
                build=build,
            )
        )
    if lyrics_edits:
        proposals.append(
            Proposal(
                title="Add lyrics",
                current=[("LYRICS", "(empty)")],
                suggested=[f"found for {len(lyrics_edits)} track(s)"],
                files=[e.rel for e in lyrics_edits],
                build=lambda _v, edits=lyrics_edits: list(edits),
                editable=False,
            )
        )
    for url, files in cover_groups.items():
        data = download_image(url)
        if not data:
            continue
        pic = Picture(data, image_mime(data))
        proposals.append(
            Proposal(
                title="Add cover",
                current=[("Cover", "(none)"), ("Example", files[0])],
                suggested=[f"{url} ({len(data) // 1024} KB)"],
                files=files,
                build=lambda _v, files=files, pic=pic: [CoverEdit(rel, pic, "fetched") for rel in files],
                editable=False,
            )
        )
    return proposals
