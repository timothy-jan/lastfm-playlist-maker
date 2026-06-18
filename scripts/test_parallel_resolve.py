# -*- coding: utf-8 -*-
"""Verify the resolve pipeline matches tracks via mocked Spotify search."""

import sys
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")

from src.models import Track
from src.track_cache import TrackCache
from src.track_resolver import TrackResolver

CATALOG = {
    ("Radiohead", "Creep"): {
        "name": "Creep",
        "artists": [{"name": "Radiohead"}],
        "uri": "spotify:track:radiohead_creep",
    },
    ("Daft Punk", "One More Time"): {
        "name": "One More Time",
        "artists": [{"name": "Daft Punk"}],
        "uri": "spotify:track:daftpunk_omt",
    },
    ("Kendrick Lamar", "HUMBLE."): {
        "name": "HUMBLE.",
        "artists": [{"name": "Kendrick Lamar"}],
        "uri": "spotify:track:kendrick_humble",
    },
}


class _NoopCache:
    def get_search_many(self, pairs):
        return {pair: (False, None) for pair in pairs}

    def set_search_many(self, entries):
        pass


def fake_search(query: str) -> list[dict]:
    q = query.casefold()
    for (artist, title), item in CATALOG.items():
        if title.casefold() in q and artist.casefold() in q:
            return [item]
    return []


def main():
    resolver = TrackResolver(
        cache=_NoopCache(),  # type: ignore[arg-type]
        search=fake_search,
    )
    tracks = [Track(a, t) for a, t in CATALOG]
    with patch.object(resolver._lastfm, "resolve_urls", return_value={}):
        uris, not_found = resolver.resolve(tracks)

    print(f"matched {len(uris)}/{len(tracks)}")
    for track in not_found:
        print(f"  MISS: {track.artist} — {track.title}")

    if len(uris) != len(tracks):
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
