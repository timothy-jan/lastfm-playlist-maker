"""Match Last.fm tracks to Spotify — one search per track, sequential, no magic."""

from __future__ import annotations

import re
import time
import unicodedata
from difflib import SequenceMatcher

from .models import Track

_FEAT = re.compile(r"\s*[-–—]\s*(?:feat\.?|ft\.?|featuring|with).*$", re.IGNORECASE)
_PARENS = re.compile(r"\s*[\(\[\{][^\)\]\}]*[\)\]\}]\s*")
_HASH = re.compile(r"\s*#\S+")


def _norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text.casefold()).split())


def _simple(text: str) -> str:
    return re.sub(r"[^\w\s]", "", _norm(text), flags=re.UNICODE)


def clean_title(title: str) -> str:
    t = _FEAT.sub("", title.strip())
    t = _HASH.sub("", t)
    t = _PARENS.sub(" ", t)
    t = " ".join(t.split()).strip()
    return t or title.strip()


def primary_artist(artist: str) -> str:
    return re.split(
        r"\s+(?:feat\.?|ft\.?|featuring|with)\s+|\s*&\s*|\s*,\s*|\s+/\s+",
        artist.strip(),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()


def _similar(a: str, b: str) -> float:
    x, y = _simple(a), _simple(b)
    if not x or not y:
        return 1.0 if x == y else 0.0
    if x == y or x in y or y in x:
        return 0.95
    return SequenceMatcher(None, x, y).ratio()


def accepts(track: Track, item: dict) -> bool:
    """True if this Spotify result is plausibly the same track."""
    spotify_title = item.get("name", "")
    spotify_artists = [a.get("name", "") for a in item.get("artists", [])]

    title_score = _similar(clean_title(track.title), spotify_title)
    artist_score = max(
        (_similar(primary_artist(track.artist), name) for name in spotify_artists),
        default=0.0,
    )

    if artist_score >= 0.5 and title_score >= 0.55:
        return True
    if artist_score >= 0.7 and title_score >= 0.45:
        return True
    return title_score >= 0.85 and artist_score >= 0.35


def _search(client, query: str) -> list[dict]:
    for attempt in range(3):
        try:
            result = client.search(q=query, type="track", limit=5)
            return result.get("tracks", {}).get("items", [])
        except Exception as exc:
            status = getattr(exc, "http_status", None)
            if status == 429 and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            return []
    return []


def find_uri(client, track: Track) -> str | None:
    """Search Spotify and return a track URI, or None."""
    artist = primary_artist(track.artist)
    title = clean_title(track.title)
    for query in (f"track:{title} artist:{artist}", f"{title} {artist}"):
        for item in _search(client, query):
            if accepts(track, item) and item.get("uri"):
                return item["uri"]
    return None


def resolve_tracks(client, tracks: list[Track]) -> tuple[list[str], list[Track]]:
    """Resolve tracks in order. Dedupes identical artist/title within the batch."""
    seen: dict[tuple[str, str], str | None] = {}
    uris: list[str] = []
    not_found: list[Track] = []

    for track in tracks:
        key = (_norm(track.artist), _norm(track.title))
        if key not in seen:
            seen[key] = find_uri(client, track)
            time.sleep(0.08)

        uri = seen[key]
        if uri:
            uris.append(uri)
        else:
            not_found.append(track)

    return uris, not_found
