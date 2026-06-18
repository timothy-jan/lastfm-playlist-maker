# -*- coding: utf-8 -*-
"""Offline matcher regression checks."""

import sys

sys.stdout.reconfigure(encoding="utf-8")

from src.models import Track
from src.track_matcher import clean_title, pick_best, search_queries

CASES = [
    (
        Track("Death Grips", "I've Seen Footage"),
        {"name": "I've Seen Footage", "artists": [{"name": "Death Grips"}], "uri": "spotify:track:1"},
        True,
    ),
    (
        Track("Death Grips", "I've Seen Footage"),
        {"name": "Get Got", "artists": [{"name": "Death Grips"}], "uri": "spotify:track:2"},
        False,
    ),
    (
        Track("Mayday", "溫柔 #MaydayBlue20th - feat.孫燕姿"),
        {"name": "溫柔", "artists": [{"name": "Mayday"}, {"name": "孫燕姿"}], "uri": "spotify:track:3"},
        True,
    ),
    (
        Track("Crowd Lu", "繁華攏是夢 (Live 版)"),
        {"name": "繁華攏是夢", "artists": [{"name": "Crowd Lu"}], "uri": "spotify:track:4"},
        True,
    ),
    (
        Track("Radiohead", "Creep"),
        {"name": "Creep", "artists": [{"name": "Another Artist"}], "uri": "spotify:track:7"},
        False,
    ),
]

print("Title cleanup")
for title in ["繁華攏是夢 (Live 版)", "溫柔 #MaydayBlue20th - feat.孫燕姿", "I've Seen Footage"]:
    print(f"  {title!r} -> {clean_title(title)!r}")

print("\nQueries for Eminem feat track:")
t = Track("Eminem", "Love The Way You Lie (feat. Rihanna)")
print(" ", search_queries(t))

print("\nAcceptance checks")
failed = 0
for track, item, expected in CASES:
    picked = pick_best(track, [item]) is not None
    status = "OK" if picked == expected else "FAIL"
    if picked != expected:
        failed += 1
    print(f"  [{status}] {track.artist} — {track.title} vs {item['name']}")

if failed:
    sys.exit(1)
print("\nAll offline matcher checks passed")
