"""Normalize Last.fm track names and score Spotify search results."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .models import Track

_PARENS = re.compile(r"\s*[\(\[\{][^\)\]\}]*[\)\]\}]\s*")
_FEAT_SUFFIX = re.compile(
    r"\s*[-–—]\s*(?:feat\.?|ft\.?|featuring|with)\.?\s*.+$",
    re.IGNORECASE,
)
_HASHTAG = re.compile(r"\s*#\S+")
_ARTIST_SPLIT = re.compile(
    r"\s+(?:feat\.?|ft\.?|featuring|with)\.?\s+|\s*&\s*|\s*,\s*|\s+/\s+",
    re.IGNORECASE,
)
_TAG_IN_PARENS = re.compile(
    r"\s*[\(\[\{][^\)\]\}]*(?:"
    r"remaster(?:ed)?|radio edit|single|album|deluxe|bonus|live|mix|版"
    r")[^\)\]\}]*[\)\]\}]",
    re.IGNORECASE,
)


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text.casefold()).split())


def simplify(text: str) -> str:
    text = normalize(text)
    return re.sub(r"[^\w\s]", "", text, flags=re.UNICODE)


def clean_title(title: str) -> str:
    t = _FEAT_SUFFIX.sub("", title.strip())
    t = _HASHTAG.sub("", t)
    t = _TAG_IN_PARENS.sub("", t)
    t = _PARENS.sub(" ", t)
    t = " ".join(t.split()).strip().strip("-–—")
    return t or title.strip()


def primary_artist(artist: str) -> str:
    parts = [p.strip() for p in _ARTIST_SPLIT.split(artist.strip()) if p.strip()]
    return parts[0] if parts else artist.strip()


def similarity(a: str, b: str) -> float:
    x, y = simplify(a), simplify(b)
    if not x or not y:
        return 1.0 if x == y else 0.0
    if x == y:
        return 1.0
    if x in y or y in x:
        short, long = (x, y) if len(x) <= len(y) else (y, x)
        return 0.88 + 0.12 * len(short) / max(len(long), 1)
    return SequenceMatcher(None, x, y).ratio()


def title_score(expected: str, candidate: str) -> float:
    raw = expected.strip()
    cleaned = clean_title(raw)
    return max(
        similarity(raw, candidate),
        similarity(cleaned, candidate),
        similarity(re.sub(r"\s*#.+$", "", raw), candidate),
    )


def artist_score(expected: str, candidate: str) -> float:
    best = 0.0
    for variant in {expected.strip(), primary_artist(expected)}:
        best = max(best, similarity(variant, candidate))
    return best


def score_match(track: Track, item: dict) -> tuple[float, float, float]:
    """Return (combined, title, artist) scores."""
    item_title = item.get("name", "")
    item_artists = [a.get("name", "") for a in item.get("artists", [])]
    t = title_score(track.title, item_title)
    a = max((artist_score(track.artist, name) for name in item_artists), default=0.0)
    combined = 0.62 * t + 0.38 * a
    return combined, t, a


def is_good_match(track: Track, item: dict) -> bool:
    combined, t, a = score_match(track, item)
    if a >= 0.50 and t >= 0.52:
        return True
    if a >= 0.68 and t >= 0.45:
        return True
    return combined >= 0.62 and a >= 0.45 and t >= 0.48


def pick_best(track: Track, items: list[dict]) -> str | None:
    """Pick the best Spotify URI from search results, or None."""
    if not items:
        return None

    best_uri: str | None = None
    best_combined = 0.0

    for item in items:
        combined, _, _ = score_match(track, item)
        if combined > best_combined and is_good_match(track, item):
            best_combined = combined
            best_uri = item.get("uri")

    return best_uri


def search_queries(track: Track) -> list[str]:
    """Ordered Spotify search queries — stop at first hit."""
    artist = primary_artist(track.artist)
    cleaned = clean_title(track.title)
    raw = track.title.strip()
    queries = [
        f"track:{cleaned} artist:{artist}",
        f"{cleaned} {artist}",
    ]
    if cleaned != raw:
        queries.append(f'track:"{cleaned}" artist:"{artist}"')
    if len(cleaned) >= 3:
        queries.append(f"{cleaned} artist:{artist}")

    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        key = q.casefold()
        if key not in seen:
            seen.add(key)
            out.append(q)
    return out


# Back-compat aliases used by older scripts
title_variants = lambda title: [title.strip(), clean_title(title)]
pick_best_match = lambda track, items, **_: pick_best(track, items)
match_components = lambda track, item: score_match(track, item)
