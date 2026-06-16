import requests
import re

SPOTIFY_TRACK_RE = re.compile(
    r"(?:open\.spotify\.com/track/|spotify:track:)([a-zA-Z0-9]{22})"
)

cases = [
    ("Death Grips", "I've Seen Footage", "https://www.last.fm/music/Death+Grips/_/I%27ve+Seen+Footage"),
    ("No Party For Cao Dong", "但", None),
    ("Mayday", "溫柔 #MaydayBlue20th - feat.孫燕姿", None),
]

for artist, title, url in cases:
    if not url:
        from urllib.parse import quote
        url = f"https://www.last.fm/music/{quote(artist)}/_/{quote(title)}"
    r = requests.get(url, headers={"User-Agent": "test"}, timeout=15)
    ids = SPOTIFY_TRACK_RE.findall(r.text)
    print(repr(title), "status", r.status_code, "ids", len(ids))
