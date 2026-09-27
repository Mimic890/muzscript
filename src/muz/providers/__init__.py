"""Online metadata sources."""

from __future__ import annotations

from muz.providers.base import Found, Provider, Query


def get_provider(name: str) -> Provider:
    """"auto" prefers SpotiFLAC and falls back to the built-in client."""
    if name in ("auto", "spotiflac"):
        try:
            from muz.providers.spotiflac import SpotiflacProvider

            return SpotiflacProvider()
        except ImportError:
            if name == "spotiflac":
                raise RuntimeError(
                    "SpotiFLAC is not installed. Install it with: pip install 'muz[spotiflac]' "
                    "(it is already included in the Docker image)"
                ) from None
    from muz.providers.builtin import BuiltinProvider

    return BuiltinProvider()


__all__ = ["Found", "Provider", "Query", "get_provider"]
