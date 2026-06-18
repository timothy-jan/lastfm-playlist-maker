# -*- coding: utf-8 -*-
"""Live Spotify matching test (Client Credentials — no user login)."""

import sys

sys.stdout.reconfigure(encoding="utf-8")

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

from src.config import spotify_client_id, spotify_client_secret
from src.models import Track
from src.track_matcher import score_match
from src.track_resolver import TrackResolver

CASES: list[tuple[str, str, bool]] = [
    ("Radiohead", "Creep", True),
    ("The Beatles", "Hey Jude", True),
    ("Daft Punk", "One More Time", True),
    ("Kendrick Lamar", "HUMBLE.", True),
    ("Panic! at the Disco", "I Write Sins Not Tragedies", True),
    ("Eminem", "Love The Way You Lie (feat. Rihanna)", True),
    ("Queen", "Bohemian Rhapsody - Remastered 2011", True),
    ("Death Grips", "I've Seen Footage", True),
    ("BTS", "Dynamite", True),
    ("Mayday", "溫柔", True),
    ("Zzzqqq Fake Artist", "Totally Fake Song Xyzzy", False),
]


def main() -> None:
    manager = SpotifyClientCredentials(
        client_id=spotify_client_id(),
        client_secret=spotify_client_secret(),
    )
    client = spotipy.Spotify(client_credentials_manager=manager)

    def search(q: str) -> list[dict]:
        return client.search(q=q, type="track", limit=10).get("tracks", {}).get("items", [])

    resolver = TrackResolver(search=search, search_workers=2)
    tracks = [Track(a, t) for a, t, _ in CASES]
    expected = {Track(a, t): ok for a, t, ok in CASES}

    uris, not_found = resolver.resolve(tracks)
    found_set = {(t.artist, t.title) for t in tracks if t not in not_found}

    matched = sum(1 for a, t, ok in CASES if ok and (a, t) in found_set)
    expected_count = sum(1 for *_, ok in CASES if ok)
    false_pos = sum(1 for a, t, ok in CASES if not ok and (a, t) in found_set)

    print(f"Live results: {matched}/{expected_count} matched, {false_pos} false positive(s)\n")
    for artist, title, should in CASES:
        hit = (artist, title) in found_set
        mark = "OK" if hit == should else "FAIL"
        detail = ""
        if hit:
            # re-search for display
            items = search(f"track:{title} artist:{artist}")
            if items:
                c, ts, a_s = score_match(Track(artist, title), items[0])
                detail = f" (top score c={c:.2f} t={ts:.2f} a={a_s:.2f})"
        print(f"  [{mark}] {artist} — {title}{detail}")

    if matched < expected_count * 0.8:
        sys.exit(1)


if __name__ == "__main__":
    main()
