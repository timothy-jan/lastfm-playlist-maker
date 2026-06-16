# -*- coding: utf-8 -*-
"""Offline matcher regression checks."""

import sys

sys.stdout.reconfigure(encoding="utf-8")

from src.models import Track
from src.track_matcher import clean_title, is_acceptable_match, pick_best_match, title_variants

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
        False,
    ),
    (
        Track("Crowd Lu", "繁華攏是夢 (Live 版)"),
        {"name": "繁華攏是夢 (Live)", "artists": [{"name": "Crowd Lu"}], "uri": "spotify:track:5"},
        True,
    ),
    (
        Track("Radiohead", "Creep"),
        {"name": "Creep", "artists": [{"name": "Radiohead"}], "uri": "spotify:track:6"},
        True,
    ),
    (
        Track("Radiohead", "Creep"),
        {"name": "Creep", "artists": [{"name": "Another Artist"}], "uri": "spotify:track:7"},
        False,
    ),
]

print("Title cleanup")
for title in [
    "繁華攏是夢 (Live 版)",
    "溫柔 #MaydayBlue20th - feat.孫燕姿",
    "I've Seen Footage",
]:
    print(f"  {title!r} -> {clean_title(title)!r} ({title_variants(title)})")

print("\nAcceptance checks")
failed = 0
for track, item, expected in CASES:
    strict = is_acceptable_match(track, item, relaxed=False)
    relaxed = is_acceptable_match(track, item, relaxed=True)
    picked = pick_best_match(track, [item], relaxed=False) is not None
    ok = (strict == expected) or (expected and relaxed and not strict and picked)
    if expected:
        ok = relaxed or strict or pick_best_match(track, [item], relaxed=True)
    else:
        ok = not strict and not relaxed
    status = "OK" if ok else "FAIL"
    if not ok:
        failed += 1
    print(f"  {status}: {track.artist} — {track.title} vs {item['name']}")

if failed:
    sys.exit(1)

print("\nAll offline matcher checks passed")
