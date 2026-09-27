"""Actions: each one looks at the scanned library and proposes changes."""

from __future__ import annotations

from dataclasses import dataclass

from muz.config import Rules
from muz.library import Library
from muz.scanner import ScanResult, Track


@dataclass
class Context:
    lib: Library
    rules: Rules
    scan: ScanResult

    def writable(self) -> list[Track]:
        return [t for t in self.scan.tracks if t.writable and not t.error]
