"""Match Last.fm tracks to Spotify URIs."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .models import Track

# Strip featured artists, live/remaster tags, etc.
_TITLE_CLEANUP = re.compile(
    r"\s*[\(\[\{][^\)\]\}]*(?:"
    r"remaster(?:ed)?|radio edit|single version|album version|deluxe|bonus track|"
    r"original mix|extended mix|club mix|"
    r"live\s*版|live版|live"
    r")[^\)\]\}]*[\)\]\}]",
    re.IGNORECASE,
)
_PARENS = re.compile(r"\s*[\(\[\{][^\)\]\}]*[\)\]\}]\s*")
_TRAILING_TAGS = re.compile(
    r"\s*[-–—]\s*(?:"
    r"radio edit|single version|album version|live|acoustic|remix|"
    r"original mix|extended mix|club mix"
    r")\s*$",
    re.IGNORECASE,
)

_VERSION_TAGS = (
    "live",
    "acoustic",
    "remix",
    "demo",
    "instrumental",
    "karaoke",
    "cover",
    "edit",
    "版",
)


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
_ARTIST_SPLIT = re.compile(
    r"\s+(?:feat\.?|ft\.?|featuring|with)\.?\s+|\s*&\s*|\s*,\s*|\s+/\s+",
    re.IGNORECASE,
)


def clean_title(title: str) -> str:
    cleaned = _FEAT_SUFFIX.sub("", title)
    cleaned = _HASHTAG.sub("", cleaned)
    cleaned = _TITLE_CLEANUP.sub("", cleaned)
    cleaned = _PARENS.sub(" ", cleaned)
    cleaned = _TRAILING_TAGS.sub("", cleaned)
    cleaned = " ".join(cleaned.split()).strip().strip("-–—").strip()
    return cleaned or title.strip()


def title_variants(title: str) -> list[str]:
    raw = title.strip()
    cleaned = clean_title(raw)
    no_hash = re.sub(r"\s*#.+$", "", raw).strip()
    no_parens = _PARENS.sub(" ", raw).strip()
    variants = [raw, cleaned, no_hash, no_parens]
    seen: set[str] = set()
    unique: list[str] = []
    for variant in variants:
        key = variant.casefold()
        if variant and key not in seen:
            seen.add(key)
            unique.append(variant)
    return unique


def artist_variants(artist: str) -> list[str]:
    raw = artist.strip()
    parts = [part.strip() for part in _ARTIST_SPLIT.split(raw) if part.strip()]
    variants = [raw, *parts]
    if parts:
        variants.append(parts[0])
    seen: set[str] = set()
    unique: list[str] = []
    for variant in variants:
        key = variant.casefold()
        if variant and key not in seen:
            seen.add(key)
            unique.append(variant)
    return unique


def similarity(left: str, right: str) -> float:
    """Return 0-1 similarity between two artist/title strings."""
    a = simplify(left)
    b = simplify(right)
    if not a or not b:
        return 1.0 if a == b else 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
        return 0.86 + 0.14 * (len(shorter) / max(len(longer), 1))
    return SequenceMatcher(None, a, b).ratio()


def artist_matches(expected: str, candidate: str) -> bool:
    for variant in artist_variants(expected):
        if similarity(variant, candidate) >= 0.72:
            return True
    return False


def title_matches(expected: str, candidate: str) -> bool:
    for variant in title_variants(expected):
        if similarity(variant, candidate) >= 0.78:
            return True
        if similarity(clean_title(variant), candidate) >= 0.78:
            return True
    return False


def _best_title_similarity(expected_title: str, candidate_title: str) -> float:
    best = 0.0
    for variant in title_variants(expected_title):
        best = max(best, similarity(variant, candidate_title))
        best = max(best, similarity(clean_title(variant), candidate_title))
    return best


def _best_artist_similarity(expected_artist: str, candidate_artists: list[str]) -> float:
    best = 0.0
    for candidate in candidate_artists:
        for variant in artist_variants(expected_artist):
            best = max(best, similarity(variant, candidate))
    return best


def _version_penalty(expected_title: str, candidate_title: str) -> float:
    expected = simplify(expected_title)
    candidate = simplify(candidate_title)
    penalty = 0.0
    for tag in _VERSION_TAGS:
        expected_has = tag in expected
        candidate_has = tag in candidate
        if expected_has != candidate_has:
            penalty -= 0.22
    return penalty


def fast_search_queries(track: Track) -> list[str]:
    """Minimal queries for the first pass — expanded set used on retry."""
    artist = track.artist.strip()
    title = track.title.strip()
    cleaned = clean_title(title)
    queries = [
        f'track:"{title}" artist:"{artist}"',
        f"{title} {artist}",
        f"track:{title} artist:{artist}",
    ]
    if cleaned != title:
        queries.append(f'track:"{cleaned}" artist:"{artist}"')
        queries.append(f"track:{cleaned} artist:{artist}")
    seen: set[str] = set()
    unique: list[str] = []
    for query in queries:
        key = query.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(query)
    return unique


def search_queries(track: Track) -> list[str]:
    artist = track.artist.strip()
    queries: list[str] = []

    for title in title_variants(track.title):
        queries.extend(
            [
                f'track:"{title}" artist:"{artist}"',
                f"track:{title} artist:{artist}",
                f"{title} {artist}",
                f"{title} artist:{artist}",
            ]
        )
        if len(title) >= 2:
            queries.append(title)

    primary_artist = artist_variants(artist)[0]
    cleaned = clean_title(track.title)
    if cleaned and cleaned != track.title:
        queries.append(f"{cleaned} {primary_artist}")

    seen: set[str] = set()
    unique: list[str] = []
    for query in queries:
        key = query.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(query)
    return unique


def _score_match(track: Track, item: dict) -> float:
    item_title = item.get("name", "")
    item_artists = [a.get("name", "") for a in item.get("artists", [])]

    title_score = _best_title_similarity(track.title, item_title)
    artist_score = _best_artist_similarity(track.artist, item_artists)
    score = (0.68 * title_score) + (0.32 * artist_score)
    score += _version_penalty(track.title, item_title)
    return max(0.0, min(1.0, score))


def match_components(track: Track, item: dict) -> tuple[float, float, float]:
    """Return combined, title, and artist scores for a Spotify search item."""
    item_title = item.get("name", "")
    item_artists = [a.get("name", "") for a in item.get("artists", [])]
    title_score = _best_title_similarity(track.title, item_title)
    artist_score = _best_artist_similarity(track.artist, item_artists)
    combined = (0.68 * title_score) + (0.32 * artist_score)
    combined += _version_penalty(track.title, item_title)
    combined = max(0.0, min(1.0, combined))
    return combined, title_score, artist_score


def is_acceptable_match(
    track: Track,
    item: dict,
    *,
    relaxed: bool = False,
) -> bool:
    combined, title_score, artist_score = match_components(track, item)
    if relaxed:
        return combined >= 0.74 and title_score >= 0.62 and artist_score >= 0.45
    return combined >= 0.84 and title_score >= 0.72 and artist_score >= 0.52


def pick_best_match(track: Track, items: list[dict], *, relaxed: bool = False) -> str | None:
    if not items:
        return None

    scored = sorted(
        ((_score_match(track, item), item) for item in items),
        key=lambda pair: pair[0],
        reverse=True,
    )
    for _, item in scored:
        if is_acceptable_match(track, item, relaxed=relaxed):
            return item["uri"]
    return None
