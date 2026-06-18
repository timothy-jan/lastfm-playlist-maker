# -*- coding: utf-8 -*-
"""Quick offline checks for title cleanup and match acceptance."""

import sys

sys.stdout.reconfigure(encoding="utf-8")

from src.models import Track
from src.spotify_match import accepts, clean_title, primary_artist

assert clean_title("Love The Way You Lie (feat. Rihanna)") == "Love The Way You Lie"
assert clean_title("溫柔 #MaydayBlue20th - feat.孫燕姿") == "溫柔"
assert primary_artist("Eminem feat. Rihanna") == "Eminem"

track = Track("Radiohead", "Creep")
good = {"name": "Creep", "artists": [{"name": "Radiohead"}], "uri": "spotify:track:1"}
bad = {"name": "Get Got", "artists": [{"name": "Death Grips"}], "uri": "spotify:track:2"}

assert accepts(track, good)
assert not accepts(track, bad)
print("OK")
