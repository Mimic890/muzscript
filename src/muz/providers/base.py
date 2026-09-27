"""Interface every metadata source implements."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

from muz import __version__

USER_AGENT = f"muz/{__version__} (https://github.com/mimic890/muzscript)"
MAX_IMAGE_BYTES = 20 * 1024 * 1024


@dataclass
class Query:
    title: str
    artist: str  # main artist
    album: str = ""
    duration: float = 0.0  # seconds
    isrc: str = ""


@dataclass
class Found:
    tags: dict[str, list[str]] = field(default_factory=dict)
    lyrics: str = ""
    cover_url: str = ""
    source: str = ""


class Provider(Protocol):
    name: str

    def lookup(self, query: Query, want: set[str]) -> Found:
        """want is a subset of {"tags", "lyrics", "cover"}."""
        ...


def http_get(url: str, params: dict | None = None, timeout: float = 15) -> bytes | None:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(MAX_IMAGE_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def http_json(url: str, params: dict | None = None, timeout: float = 15):
    raw = http_get(url, params, timeout)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def download_image(url: str) -> bytes | None:
    data = http_get(url, timeout=30)
    if not data or len(data) > MAX_IMAGE_BYTES:
        return None
    if data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n":
        return data
    return None
