# -*- coding: utf-8 -*-
"""Live Spotify search test (requires `python -m src.web.app` login / .cache token)."""

import sys

sys.stdout.reconfigure(encoding="utf-8")

from src.destinations.spotify import SpotifyDestination
from src.models import Track
from src.spotify_match import find_uri

CASES = [
    Track("Death Grips", "I've Seen Footage"),
    Track("Radiohead", "Creep"),
    Track("Mayday", "溫柔 #MaydayBlue20th - feat.孫燕姿"),
    Track("Crowd Lu", "繁華攏是夢 (Live 版)"),
]

dest = SpotifyDestination(open_browser=False)
if not dest.is_authenticated():
    print("Spotify not authenticated — skipping")
    sys.exit(0)

matched = 0
for track in CASES:
    uri = find_uri(dest.client, track)
    print(f"{track.artist} — {track.title}: {uri or 'MISS'}")
    if uri:
        matched += 1

print(f"\n{matched}/{len(CASES)} matched")
