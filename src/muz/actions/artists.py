"""--artists: move several artists from one ARTIST string into multi-valued ARTISTS.

ARTIST keeps its display text ("A feat. B"); players that understand
multi-valued tags (Navidrome 0.55+) use ARTISTS/ALBUMARTISTS. Aliases from
.muzrules.toml merge different spellings of the same artist.
"""

from __future__ import annotations

from collections import defaultdict

from muz.actions import Context
from muz.actions.split import apply_alias, normalize_list
from muz.plan import TagEdit
from muz.ui.review import Proposal


def _edits_builder(files: list[str], field: str, old_by_file: dict[str, list[str]]):
    def build(values: list[str]):
        return [TagEdit(rel, field, old_by_file[rel], list(values), "artists") for rel in files]

    return build


def _plan_pair(ctx: Context, single: str, multi: str) -> list[Proposal]:
    r = ctx.rules
    groups: dict[tuple, list] = defaultdict(list)
    for t in ctx.writable():
        base = t.tags.get(single, [])
        existing = t.tags.get(multi, [])
        if not base and not existing:
            continue
        source = existing or base
        new = normalize_list(source, r.artist_separators, r.artist_exceptions, r.artist_aliases)
        if existing:
            if new != existing:
                groups[(multi, tuple(base), tuple(existing), tuple(new))].append(t)
        elif len(new) > 1:
            groups[(multi, tuple(base), (), tuple(new))].append(t)
        elif len(base) == 1:
            aliased = apply_alias(base[0], r.artist_aliases)
            if aliased != base[0]:
                groups[(single, tuple(base), (), (aliased,))].append(t)

    proposals = []
    for (field, base, existing, new), tracks in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        files = [t.rel for t in tracks]
        old = {t.rel: list(t.tags.get(field, [])) for t in tracks}
        current = [(single, " | ".join(base) or "—")]
        if field == multi:
            current.append((multi, " | ".join(existing) or "—"))
        note = ""
        if field == "ALBUMARTIST":
            note = "ALBUMARTIST names the artist folder; --rename will move these files."
        proposals.append(
            Proposal(
                title=f"{field}",
                current=current,
                suggested=list(new),
                files=files,
                build=_edits_builder(files, field, old),
                note=note,
            )
        )
    return proposals


def plan(ctx: Context) -> list[Proposal]:
    return _plan_pair(ctx, "ARTIST", "ARTISTS") + _plan_pair(ctx, "ALBUMARTIST", "ALBUMARTISTS")
