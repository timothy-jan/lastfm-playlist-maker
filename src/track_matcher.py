"""Match Last.fm tracks to Spotify URIs."""

from __future__ import annotations

import re
import unicodedata

from .models import Track

# Strip featured artists, live/remaster tags, etc.
_TITLE_CLEANUP = re.compile(
    r"\s*[\(\[\{][^\)\]\}]*(?:"
    r"remaster(?:ed)?|radio edit|single version|album version|deluxe|bonus track|"
    r"live\s*版|live版|live"
    r")[^\)\]\}]*[\)\]\}]",
    re.IGNORECASE,
)
_PARENS = re.compile(r"\s*[\(\[\{][^\)\]\}]*[\)\]\}]\s*")


def normalize_compare(text: str) -> str:
    """Unicode-aware lowercase compare key (keeps CJK and other scripts)."""
    return " ".join(unicodedata.normalize("NFKC", text.casefold()).split())


def simplify(text: str) -> str:
    """Looser compare key ignoring punctuation."""
    text = normalize_compare(text)
    return re.sub(r"[^\w\s]", "", text, flags=re.UNICODE)


_FEAT_SUFFIX = re.compile(
    r"\s*[-–—]\s*(?:feat\.?|ft\.?|featuring|with)\.?\s*.+$",
    re.IGNORECASE,
)
_HASHTAG = re.compile(r"\s*#\S+")


def clean_title(title: str) -> str:
    cleaned = _FEAT_SUFFIX.sub("", title)
    cleaned = _HASHTAG.sub("", cleaned)
    cleaned = _TITLE_CLEANUP.sub("", cleaned)
    cleaned = _PARENS.sub(" ", cleaned)
    cleaned = " ".join(cleaned.split()).strip().strip("-–—").strip()
    return cleaned or title.strip()


def title_variants(title: str) -> list[str]:
    raw = title.strip()
    cleaned = clean_title(raw)
    no_hash = re.sub(r"\s*#.+$", "", raw).strip()
    variants = [raw, cleaned, no_hash, _PARENS.sub(" ", raw).strip()]
    seen: set[str] = set()
    unique: list[str] = []
    for variant in variants:
        key = variant.casefold()
        if variant and key not in seen:
            seen.add(key)
            unique.append(variant)
    return unique


def artist_matches(expected: str, candidate: str) -> bool:
    a = simplify(expected)
    b = simplify(candidate)
    if not a or not b:
        return bool(a == b)
    return a in b or b in a or a.split()[0] == b.split()[0]


def title_matches(expected: str, candidate: str) -> bool:
    a = simplify(expected)
    b = simplify(candidate)
    if not a or not b:
        return a == b
    return a in b or b in a or a[:4] == b[:4]


def search_queries(track: Track) -> list[str]:
    artist = track.artist.strip()
    queries: list[str] = []

    for title in title_variants(track.title):
        queries.extend(
            [
                f"track:{title} artist:{artist}",
                f"{title} {artist}",
                f"{title} artist:{artist}",
            ]
        )
        if len(title) >= 2:
            queries.append(title)

    seen: set[str] = set()
    unique: list[str] = []
    for query in queries:
        key = query.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(query)
    return unique


def primary_search_query(track: Track) -> str:
    return f"{track.title.strip()} {track.artist.strip()}"


def _score_match(track: Track, item: dict) -> float:
    item_title = item.get("name", "")
    item_artists = [a.get("name", "") for a in item.get("artists", [])]

    best = 0.0
    for title in title_variants(track.title):
        if title_matches(title, item_title):
            best = max(best, 0.7)
        elif title_matches(clean_title(title), item_title):
            best = max(best, 0.55)

    if any(artist_matches(track.artist, name) for name in item_artists):
        best += 0.35

    return min(best, 1.0)


def pick_best_match(track: Track, items: list[dict], *, relaxed: bool = False) -> str | None:
    if not items:
        return None

    scored = sorted(
        ((_score_match(track, item), item) for item in items),
        key=lambda pair: pair[0],
        reverse=True,
    )
    best_score, best_item = scored[0]
    threshold = 0.45 if relaxed else 0.55
    if best_score >= threshold:
        return best_item["uri"]

    if relaxed and best_score >= 0.25 and artist_matches(
        track.artist, best_item.get("artists", [{}])[0].get("name", "")
    ):
        return best_item["uri"]

    return None
