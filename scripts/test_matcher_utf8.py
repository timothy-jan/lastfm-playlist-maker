# -*- coding: utf-8 -*-
import sys

sys.stdout.reconfigure(encoding="utf-8")

from src.models import Track
from src.track_matcher import clean_title, pick_best_match, search_queries, title_variants

cases = [
    "繁華攏是夢 (Live 版)",
    "溫柔 #MaydayBlue20th - feat.孫燕姿",
    "I've Seen Footage",
]

for title in cases:
    print("title:", title)
    print("  clean:", clean_title(title))
    print("  variants:", title_variants(title))

items = [
    {
        "name": "I've Seen Footage",
        "artists": [{"name": "Death Grips"}],
        "uri": "spotify:track:test",
    }
]
track = Track("Death Grips", "I've Seen Footage")
print("death grips:", pick_best_match(track, items))
