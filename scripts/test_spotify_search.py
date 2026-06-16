# -*- coding: utf-8 -*-
"""Live Spotify search test for previously failing tracks."""

import sys

sys.stdout.reconfigure(encoding="utf-8")

from src.destinations.spotify import SpotifyDestination
from src.models import Track

FAILING = [
    Track("Death Grips", "I've Seen Footage"),
    Track("Death Grips", "Get Got"),
    Track("Death Grips", "Hacker"),
    Track("No Party For Cao Dong", "但"),
    Track("Enno Cheng", "就算我放棄了世界"),
    Track("Mayday", "溫柔 #MaydayBlue20th - feat.孫燕姿"),
    Track("Crowd Lu", "繁華攏是夢 (Live 版)"),
]

dest = SpotifyDestination(open_browser=False)
if not dest.is_authenticated():
    print("Spotify not authenticated — skipping live search test")
    sys.exit(0)

matched = 0
for track in FAILING:
    uri = dest._search_track(track, relaxed=False)
    if not uri:
        uri = dest._search_track(track, relaxed=True)
    status = uri or "MISS"
    print(f"{track.artist} — {track.title}: {status}")
    if uri:
        matched += 1

print(f"\n{matched}/{len(FAILING)} matched")
