"""--clean: remove junk values (SpotiFLAC links etc.), LRC headers and stray whitespace."""

from __future__ import annotations

import re
from collections import defaultdict

from muz.actions import Context
from muz.plan import TagEdit
from muz.ui.review import Proposal

# [ar:Artist], [ti:Title], [by:someone] ... but not [offset:], which shifts timing.
LRC_HEADER_RE = re.compile(r"^\[(?!offset\s*:)[a-zA-Z#][a-zA-Z0-9_#]*\s*:.*\]$", re.IGNORECASE)
MULTILINE_FIELDS = {"LYRICS", "COMMENT", "DESCRIPTION"}


def strip_lrc_headers(text: str) -> str:
    lines = text.splitlines()
    i = 0
    while i < len(lines) and (not lines[i].strip() or LRC_HEADER_RE.match(lines[i].strip())):
        i += 1
    return "\n".join(lines[i:]).strip()


def remove_junk(values: list[str], junk: list[str]) -> list[str]:
    low = [j.lower() for j in junk if j]
    return [v for v in values if not any(j in v.lower() for j in low)]


def tidy(values: list[str]) -> list[str]:
    out, seen = [], set()
    for v in values:
        v = re.sub(r"\s+", " ", v).strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def plan(ctx: Context) -> list[Proposal]:
    r = ctx.rules
    junk_groups: dict[tuple, list[str]] = defaultdict(list)
    lyrics_edits: list[TagEdit] = []
    tidy_edits: list[TagEdit] = []

    for t in ctx.writable():
        for field in r.junk_fields:
            values = t.tags.get(field, [])
            cleaned = remove_junk(values, r.junk)
            if cleaned != values:
                junk_groups[(field, tuple(values), tuple(cleaned))].append(t.rel)
        if r.strip_lrc_headers:
            lyrics = t.tags.get("LYRICS", [])
            if lyrics:
                cleaned = strip_lrc_headers(lyrics[0])
                if cleaned != lyrics[0].strip() or len(lyrics) > 1:
                    lyrics_edits.append(TagEdit(t.rel, "LYRICS", lyrics, [cleaned] if cleaned else [], "lrc headers"))
        for field, values in t.tags.items():
            if field in MULTILINE_FIELDS or field in r.junk_fields:
                continue
            cleaned = tidy(values)
            if cleaned != values:
                tidy_edits.append(TagEdit(t.rel, field, values, cleaned, "whitespace"))

    proposals = []
    for (field, old, new), files in sorted(junk_groups.items(), key=lambda kv: -len(kv[1])):

        def build(values, files=files, field=field, old=old):
            return [TagEdit(rel, field, list(old), list(values), "junk") for rel in files]

        proposals.append(
            Proposal(title=f"Junk in {field}", current=[(field, " | ".join(old))], suggested=list(new), files=files, build=build)
        )
    if lyrics_edits:
        proposals.append(
            Proposal(
                title="LRC headers in embedded lyrics",
                current=[("LYRICS", "[ar:...] [ti:...] [by:...] header lines at the top")],
                suggested=["lyrics without the header lines"],
                files=[e.rel for e in lyrics_edits],
                build=lambda _values, edits=lyrics_edits: list(edits),
                editable=False,
            )
        )
    if tidy_edits:
        fields = sorted({e.field for e in tidy_edits})
        proposals.append(
            Proposal(
                title="Extra spaces, empty or repeated values",
                current=[("Fields", ", ".join(fields))],
                suggested=["trimmed values, duplicates removed"],
                files=sorted({e.rel for e in tidy_edits}),
                build=lambda _values, edits=tidy_edits: list(edits),
                editable=False,
            )
        )
    return proposals
