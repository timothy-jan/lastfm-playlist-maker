# -*- coding: utf-8 -*-
"""Live Spotify matching test using the Client Credentials flow (no user login).

Runs the real search + matching pipeline against the live Spotify API across a
diverse set of tracks to measure the true success rate and catch regressions.

Usage:
    .venv\\Scripts\\python.exe scripts\\test_live_matching.py
"""

import sys

sys.stdout.reconfigure(encoding="utf-8")

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

from src.config import spotify_client_id, spotify_client_secret
from src.models import Track
from src.track_matcher import match_components, pick_best_match
from src.destinations.spotify import SpotifyDestination

# (artist, title, should_match) — diverse real-world cases.
CASES: list[tuple[str, str, bool]] = [
    # Mainstream English
    ("Radiohead", "Creep", True),
    ("The Beatles", "Hey Jude", True),
    ("Daft Punk", "One More Time", True),
    ("Fleetwood Mac", "The Chain", True),
    ("Tame Impala", "The Less I Know the Better", True),
    # Punctuation / stylized
    ("Kendrick Lamar", "HUMBLE.", True),
    ("Panic! at the Disco", "I Write Sins Not Tragedies", True),
    ("will.i.am", "Scream & Shout", True),
    ("Ke$ha", "TiK ToK", True),
    # Featured artists
    ("Calvin Harris", "Feel So Close", True),
    ("Eminem", "Love The Way You Lie (feat. Rihanna)", True),
    ("Mark Ronson", "Uptown Funk (feat. Bruno Mars)", True),
    # Remaster / live / version tags
    ("Queen", "Bohemian Rhapsody - Remastered 2011", True),
    ("Nirvana", "Smells Like Teen Spirit - Remastered", True),
    ("Pink Floyd", "Wish You Were Here (Live)", True),
    # Electronic / remix
    ("Avicii", "Levels - Radio Edit", True),
    ("ODESZA", "Say My Name", True),
    # Non-Latin scripts
    ("BTS", "Dynamite", True),
    ("YOASOBI", "夜に駆ける", True),
    ("Mayday", "溫柔", True),
    ("Crowd Lu", "繁華攏是夢", True),
    ("IU", "좋은 날", True),
    # Tricky / underground
    ("Death Grips", "I've Seen Footage", True),
    ("Death Grips", "Get Got", True),
    ("Aphex Twin", "Windowlicker", True),
    # Should NOT match (nonsense)
    ("Zzzqqq Nonexistent Artist 9000", "Totally Fake Song Title Xyzzy", False),
]


def build_cc_destination() -> SpotifyDestination:
    manager = SpotifyClientCredentials(
        client_id=spotify_client_id(),
        client_secret=spotify_client_secret(),
    )
    cc_client = spotipy.Spotify(client_credentials_manager=manager)

    dest = SpotifyDestination(open_browser=False)
    dest._worker_token = "client-credentials"
    # Route all Spotify access through the client-credentials client.
    dest._thread_local.client = cc_client
    dest._client = cc_client

    def _thread_client():
        return cc_client

    dest._thread_client = _thread_client  # type: ignore[method-assign]
    return dest


def main() -> None:
    dest = build_cc_destination()

    matched = 0
    expected_matches = sum(1 for *_, ok in CASES if ok)
    false_positives = 0
    misses: list[str] = []

    print(f"Running {len(CASES)} live matching cases...\n")
    for artist, title, should_match in CASES:
        track = Track(artist, title)
        # Mirror the production fast then relaxed search behavior.
        uri = dest._search_track(track, relaxed=False)
        if not uri:
            uri = dest._search_track(track, relaxed=True)

        label = ""
        if uri:
            items = dest._spotify_track_items([uri])
            item = items.get(uri)
            if item:
                got_artist = ", ".join(a["name"] for a in item.get("artists", []))
                got_title = item.get("name", "")
                combined, t_s, a_s = match_components(track, item)
                label = f"-> {got_artist} — {got_title} (c={combined:.2f} t={t_s:.2f} a={a_s:.2f})"

        if should_match:
            if uri:
                matched += 1
                status = "OK  "
            else:
                status = "MISS"
                misses.append(f"{artist} — {title}")
        else:
            if uri:
                status = "FALSE+"
                false_positives += 1
            else:
                status = "OK  "

        print(f"  [{status}] {artist} — {title} {label}")

    print(
        f"\nMatched {matched}/{expected_matches} expected; "
        f"{false_positives} false positive(s)."
    )
    if misses:
        print("\nMissed expected matches:")
        for miss in misses:
            print(f"  - {miss}")

    rate = matched / expected_matches if expected_matches else 0
    print(f"\nSuccess rate on expected matches: {rate:.0%}")


if __name__ == "__main__":
    main()
