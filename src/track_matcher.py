"""Match Last.fm tracks to Spotify URIs."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Literal

from .models import Track

MatchTier = Literal["strict", "relaxed", "best_effort"]

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

_TIER_THRESHOLDS: dict[MatchTier, tuple[float, float, float]] = {
    "strict": (0.78, 0.65, 0.45),
    "relaxed": (0.66, 0.54, 0.36),
    "best_effort": (0.48, 0.40, 0.24),
}


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


def artist_correlates(
    expected: str,
    candidate: str,
    *,
    minimum: float = 0.65,
) -> bool:
    for variant in artist_variants(expected):
        if similarity(variant, candidate) >= minimum:
            return True
    return False


def artist_matches(expected: str, candidate: str) -> bool:
    return artist_correlates(expected, candidate, minimum=0.65)


def title_matches(expected: str, candidate: str) -> bool:
    for variant in title_variants(expected):
        if similarity(variant, candidate) >= 0.70:
            return True
        if similarity(clean_title(variant), candidate) >= 0.70:
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
            penalty -= 0.10
    return penalty


def _dedupe(queries: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for query in queries:
        key = query.casefold()
        if query and key not in seen:
            seen.add(key)
            unique.append(query)
    return unique


def fast_search_queries(track: Track) -> list[str]:
    """A single precise query for the first pass to minimize API calls.

    A field-filtered query (track:/artist:) on the cleaned title is the most
    reliable single query, so the common case costs exactly one request.
    """
    artist = artist_variants(track.artist)[0]
    cleaned = clean_title(track.title)
    return _dedupe([f"track:{cleaned} artist:{artist}"])


def search_queries(track: Track) -> list[str]:
    """A small ordered set of fallback queries used only when the fast pass misses.

    Kept intentionally short (a handful of requests max) to stay well under
    Spotify's rate limits on large playlists.
    """
    artist = track.artist.strip()
    primary_artist = artist_variants(artist)[0]
    cleaned = clean_title(track.title)
    raw = track.title.strip()

    queries = [
        f'track:"{cleaned}" artist:"{primary_artist}"',
        f"{cleaned} {primary_artist}",
        f"track:{raw} artist:{artist}",
    ]
    if len(cleaned) >= 2:
        queries.append(cleaned)

    seen: set[str] = set()
    unique: list[str] = []
    for query in queries:
        key = query.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(query)
    return unique


def match_components(
    track: Track,
    item: dict,
    *,
    apply_version_penalty: bool = True,
) -> tuple[float, float, float]:
    """Return combined, title, and artist scores for a Spotify search item."""
    item_title = item.get("name", "")
    item_artists = [a.get("name", "") for a in item.get("artists", [])]
    title_score = _best_title_similarity(track.title, item_title)
    artist_score = _best_artist_similarity(track.artist, item_artists)
    combined = (0.68 * title_score) + (0.32 * artist_score)
    if apply_version_penalty:
        combined += _version_penalty(track.title, item_title)
    combined = max(0.0, min(1.0, combined))
    return combined, title_score, artist_score


_TIER_ARTIST_MINIMUM: dict[MatchTier, float] = {
    "strict": 0.65,
    "relaxed": 0.55,
    "best_effort": 0.45,
}


def is_acceptable_match(
    track: Track,
    item: dict,
    *,
    tier: MatchTier = "strict",
) -> bool:
    item_artists = [a.get("name", "") for a in item.get("artists", [])]
    artist_ok = any(
        artist_correlates(
            track.artist,
            name,
            minimum=_TIER_ARTIST_MINIMUM[tier],
        )
        for name in item_artists
    )
    if not artist_ok:
        return False

    apply_penalty = tier == "strict"
    combined, title_score, artist_score = match_components(
        track, item, apply_version_penalty=apply_penalty
    )
    min_combined, min_title, min_artist = _TIER_THRESHOLDS[tier]

    if combined >= min_combined and title_score >= min_title and artist_score >= min_artist:
        return True

    # Same artist, title close enough after cleanup (live/remaster/hashtag variants).
    if tier != "strict" and title_score >= 0.68:
        return True

    return False


def pick_best_match(
    track: Track,
    items: list[dict],
    *,
    relaxed: bool = False,
) -> str | None:
    """Pick the best Spotify URI, falling back to weaker tiers when needed."""
    if not items:
        return None

    scored = sorted(
        ((_score_match(track, item), item) for item in items),
        key=lambda pair: pair[0],
        reverse=True,
    )

    tiers: list[MatchTier] = (
        ["relaxed", "best_effort"] if relaxed else ["strict", "relaxed", "best_effort"]
    )
    for tier in tiers:
        for _, item in scored:
            if is_acceptable_match(track, item, tier=tier):
                return item["uri"]
    return None


def _score_match(track: Track, item: dict) -> float:
    combined, _, _ = match_components(track, item, apply_version_penalty=False)
    return combined
