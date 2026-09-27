"""--genres: split "Rock, Pop" into separate GENRE values and merge spellings."""

from __future__ import annotations

from collections import defaultdict

from muz.actions import Context
from muz.actions.split import normalize_list
from muz.plan import TagEdit
from muz.ui.review import Proposal


def plan(ctx: Context) -> list[Proposal]:
    r = ctx.rules
    groups: dict[tuple, list] = defaultdict(list)
    for t in ctx.writable():
        current = t.tags.get("GENRE", [])
        if not current:
            continue
        new = normalize_list(current, r.genre_separators, (), r.genre_aliases)
        if new != current:
            groups[(tuple(current), tuple(new))].append(t)

    proposals = []
    for (current, new), tracks in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        files = [t.rel for t in tracks]

        def build(values, files=files, current=current):
            return [TagEdit(rel, "GENRE", list(current), list(values), "genres") for rel in files]

        proposals.append(
            Proposal(title="GENRE", current=[("GENRE", " | ".join(current))], suggested=list(new), files=files, build=build)
        )
    return proposals
