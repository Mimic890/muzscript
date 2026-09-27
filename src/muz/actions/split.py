"""Splitting "A feat. B" style values into lists, honouring exceptions and aliases."""

from __future__ import annotations

import re


def _separator_re(separators: list[str]) -> re.Pattern | None:
    seps = sorted({s for s in separators if s}, key=len, reverse=True)
    if not seps:
        return None
    return re.compile("|".join(re.escape(s) for s in seps), re.IGNORECASE)


def _alias_map(aliases: dict[str, list[str]]) -> dict[str, str]:
    out = {}
    for canonical, variants in aliases.items():
        out[canonical.casefold()] = canonical
        for v in variants:
            out[v.casefold()] = canonical
    return out


def split_value(value: str, separators: list[str], exceptions: list[str] = ()) -> list[str]:
    """Split one tag value. Exception names are never split."""
    pattern = _separator_re(separators)
    if pattern is None:
        return [value.strip()] if value.strip() else []
    protected: list[str] = []
    text = value
    for exc in sorted(exceptions, key=len, reverse=True):
        rx = re.compile(re.escape(exc), re.IGNORECASE)

        def keep(m: re.Match) -> str:
            protected.append(m.group(0))
            return f"\x00{len(protected) - 1}\x00"

        text = rx.sub(keep, text)
    parts = pattern.split(text)
    out = []
    for part in parts:
        restored = re.sub(r"\x00(\d+)\x00", lambda m: protected[int(m.group(1))], part).strip()
        if restored:
            out.append(restored)
    return out


def normalize_list(
    values: list[str],
    separators: list[str],
    exceptions: list[str] = (),
    aliases: dict[str, list[str]] | None = None,
) -> list[str]:
    """Split every value, map aliases to their canonical name, drop duplicates."""
    amap = _alias_map(aliases or {})
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        for part in split_value(value, separators, exceptions):
            part = amap.get(part.casefold(), part)
            if part.casefold() not in seen:
                seen.add(part.casefold())
                out.append(part)
    return out


def apply_alias(value: str, aliases: dict[str, list[str]]) -> str:
    return _alias_map(aliases).get(value.casefold(), value)
