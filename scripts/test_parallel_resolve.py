# -*- coding: utf-8 -*-
"""Verify the threaded resolve pipeline returns matches without a request context.

Reproduces the conditions of the live bug (searches running in worker threads)
using mocked Spotify responses, so no network or auth is required.
"""

import sys
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")

from src.destinations.spotify import SpotifyDestination
from src.models import Track
from src.track_cache import TrackCache


class _NoopCache:
    def get_search(self, artist, title):
        return False, None

    def set_search(self, artist, title, uri):
        pass

    def get_search_many(self, pairs):
        return {pair: (False, None) for pair in pairs}

    def set_search_many(self, entries):
        pass

    def get_lastfm_many(self, urls):
        return {url: (False, None) for url in urls}

    def set_lastfm_many(self, successes):
        pass


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

TRACKS = [Track(artist, title) for (artist, title) in CATALOG]


def fake_search(self, query):
    q = query.casefold()
    for (artist, title), item in CATALOG.items():
        if title.casefold() in q and artist.casefold() in q:
            return [item]
    for (artist, title), item in CATALOG.items():
        if title.casefold() in q:
            return [item]
    return []


def main():
    cache = _NoopCache()
    dest = SpotifyDestination(open_browser=False, track_cache=cache)
    # Pretend we already have a usable token (captured in the request thread).
    dest._worker_token = "fake-token"

    with patch.object(SpotifyDestination, "_spotify_search", fake_search), patch.object(
        SpotifyDestination, "_spotify_track_items", lambda self, uris: {}
    ), patch.object(
        dest._lastfm_resolver,
        "resolve_many",
        lambda items: {},
    ):
        uris, not_found = dest._resolve_all_tracks(TRACKS)

    print(f"matched {len(uris)}/{len(TRACKS)}")
    for track in not_found:
        print(f"  MISS: {track.artist} — {track.title}")

    if len(uris) != len(TRACKS):
        print("FAIL: threaded resolve did not match every track")
        sys.exit(1)

    print("OK: threaded resolve matched all tracks")


if __name__ == "__main__":
    main()
