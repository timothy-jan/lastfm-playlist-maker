"""Resolve Last.fm tracks to Spotify URIs — single orchestrated pipeline.

Strategy (first principles):
  1. Dedupe identical artist/title pairs.
  2. SQLite cache — instant on repeat builds.
  3. Spotify search (1–3 queries per track) — fast, works for most music.
  4. Last.fm page scrape — fallback only for remaining misses.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Protocol

from .config import SPOTIFY_SEARCH_WORKERS
from .lastfm_spotify_resolver import LastFmSpotifyResolver
from .models import Track
from .track_cache import TrackCache
from .track_matcher import pick_best, search_queries

SEARCH_LIMIT = 10


class SpotifySearchFn(Protocol):
    def __call__(self, query: str) -> list[dict]: ...


def track_key(track: Track) -> tuple[str, str]:
    return track.artist.casefold().strip(), track.title.casefold().strip()


class TrackResolver:
    def __init__(
        self,
        *,
        cache: TrackCache | None = None,
        lastfm: LastFmSpotifyResolver | None = None,
        search: SpotifySearchFn,
        search_workers: int = SPOTIFY_SEARCH_WORKERS,
        rate_limited: threading.Event | None = None,
    ) -> None:
        self._cache = cache or TrackCache.shared()
        self._lastfm = lastfm or LastFmSpotifyResolver(self._cache)
        self._search = search
        self._search_workers = max(1, search_workers)
        self._search_sem = threading.Semaphore(self._search_workers)
        self._rate_limited = rate_limited or threading.Event()

    def resolve(self, tracks: list[Track]) -> tuple[list[str], list[Track]]:
        if not tracks:
            return [], []

        n = len(tracks)
        resolved: list[str | None] = [None] * n

        key_to_indices: dict[tuple[str, str], list[int]] = {}
        key_to_track: dict[tuple[str, str], Track] = {}
        for index, track in enumerate(tracks):
            key = track_key(track)
            key_to_indices.setdefault(key, []).append(index)
            key_to_track[key] = track

        pending_keys = list(key_to_track.keys())
        cache_writes: list[tuple[str, str, str]] = []

        # ── 1. Cache ──────────────────────────────────────────────────────
        pairs = [(key_to_track[k].artist, key_to_track[k].title) for k in pending_keys]
        cached = self._cache.get_search_many(pairs)
        still: list[tuple[str, str]] = []

        for key in pending_keys:
            track = key_to_track[key]
            hit, uri = cached.get((track.artist, track.title), (False, None))
            if hit and uri:
                for index in key_to_indices[key]:
                    resolved[index] = uri
            else:
                still.append(key)

        # ── 2. Spotify search (parallel, rate-aware) ──────────────────────
        if still and not self._rate_limited.is_set():
            search_results = self._search_batch({k: key_to_track[k] for k in still})
            for key, uri in search_results.items():
                if not uri:
                    continue
                track = key_to_track[key]
                cache_writes.append((track.artist, track.title, uri))
                for index in key_to_indices[key]:
                    resolved[index] = uri

        # ── 3. Last.fm scrape (fallback, smaller set) ─────────────────────
        still_missing = [k for k in still if not resolved[key_to_indices[k][0]]]
        if still_missing:
            url_for_key: dict[tuple[str, str], str] = {}
            for key in still_missing:
                track = key_to_track[key]
                url_for_key[key] = self._lastfm.track_url(
                    lastfm_url=track.lastfm_url,
                    artist=track.artist,
                    title=track.title,
                )

            ids_by_url = self._lastfm.resolve_urls(list(url_for_key.values()))
            for key, url in url_for_key.items():
                spotify_id = ids_by_url.get(url)
                if not spotify_id:
                    continue
                uri = LastFmSpotifyResolver.to_spotify_uri(spotify_id)
                track = key_to_track[key]
                cache_writes.append((track.artist, track.title, uri))
                for index in key_to_indices[key]:
                    resolved[index] = uri

        if cache_writes:
            self._cache.set_search_many(cache_writes)

        uris = [uri for uri in resolved if uri]
        not_found = [track for uri, track in zip(resolved, tracks) if not uri]
        return uris, not_found

    def _search_batch(self, tracks_by_key: dict[tuple[str, str], Track]) -> dict[tuple[str, str], str | None]:
        results: dict[tuple[str, str], str | None] = {}
        if not tracks_by_key:
            return results

        items = list(tracks_by_key.items())
        if len(items) == 1:
            key, track = items[0]
            results[key] = self._spotify_resolve(track)
            return results

        with ThreadPoolExecutor(max_workers=self._search_workers) as executor:
            futures = {
                executor.submit(self._spotify_resolve, track): key
                for key, track in items
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    results[key] = future.result()
                except Exception:
                    results[key] = None
        return results

    def _spotify_resolve(self, track: Track) -> str | None:
        if self._rate_limited.is_set():
            return None

        for query in search_queries(track):
            items = self._spotify_query(query)
            uri = pick_best(track, items)
            if uri:
                return uri
        return None

    def _spotify_query(self, query: str) -> list[dict]:
        if not query or self._rate_limited.is_set():
            return []
        with self._search_sem:
            try:
                return self._search(query)[:SEARCH_LIMIT]
            except Exception:
                return []
