"""Resolve Spotify track IDs from Last.fm track pages."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import LASTFM_RESOLVE_WORKERS
from .track_cache import TrackCache

SPOTIFY_TRACK_RE = re.compile(
    r"(?:open\.spotify\.com/track/|spotify:track:)([a-zA-Z0-9]{22})"
)
USER_AGENT = "LastFmPlaylistMaker/0.1 (https://github.com/local/lastfm-playlist-maker)"


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    retry = Retry(total=2, backoff_factor=0.1, status_forcelist=(429, 500, 502, 503, 504))
    adapter = HTTPAdapter(
        pool_connections=LASTFM_RESOLVE_WORKERS,
        pool_maxsize=LASTFM_RESOLVE_WORKERS,
        max_retries=retry,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class LastFmSpotifyResolver:
    """Extract Spotify track IDs embedded on Last.fm track pages."""

    def __init__(self, cache: TrackCache | None = None) -> None:
        self._cache = cache or TrackCache.shared()
        self._memory: dict[str, str | None] = {}
        self._session = _build_session()

    @staticmethod
    def build_track_url(artist: str, title: str) -> str:
        return f"https://www.last.fm/music/{quote(artist)}/_/{quote(title)}"

    @staticmethod
    def to_spotify_uri(spotify_id: str) -> str:
        return f"spotify:track:{spotify_id}"

    def track_url(self, *, lastfm_url: str | None, artist: str, title: str) -> str:
        return lastfm_url or self.build_track_url(artist, title)

    def candidate_urls(
        self, *, lastfm_url: str | None, artist: str, title: str
    ) -> list[str]:
        candidates: list[str] = []
        if lastfm_url:
            candidates.append(lastfm_url)
            if "www.last.fm" in lastfm_url:
                candidates.append(lastfm_url.replace("www.last.fm", "last.fm"))
        candidates.append(self.build_track_url(artist, title))

        seen: set[str] = set()
        unique: list[str] = []
        for url in candidates:
            if url not in seen:
                seen.add(url)
                unique.append(url)
        return unique

    def resolve(
        self,
        *,
        lastfm_url: str | None,
        artist: str,
        title: str,
    ) -> str | None:
        results = self.resolve_many([(lastfm_url, artist, title)])
        primary = self.track_url(lastfm_url=lastfm_url, artist=artist, title=title)
        return results.get(primary)

    def resolve_many(
        self,
        tracks: list[tuple[str | None, str, str]],
    ) -> dict[str, str | None]:
        """Resolve many tracks, deduplicating URLs and using disk + memory cache."""
        track_urls: list[tuple[str | None, str, str, list[str]]] = []
        for lastfm_url, artist, title in tracks:
            primary = self.track_url(lastfm_url=lastfm_url, artist=artist, title=title)
            candidates = self.candidate_urls(
                lastfm_url=lastfm_url, artist=artist, title=title
            )
            track_urls.append((lastfm_url, artist, title, candidates))

        url_map: dict[str, str | None] = {}

        # Phase 1: primary URL per track only (most hits, fewest requests).
        primary_urls = list(
            dict.fromkeys(
                self.track_url(lastfm_url=lf, artist=a, title=t)
                for lf, a, t, _ in track_urls
            )
        )
        self._fetch_urls(primary_urls, url_map)

        # Phase 2: alternate URLs only for tracks still missing.
        alternate_urls: list[str] = []
        for lastfm_url, artist, title, candidates in track_urls:
            primary = self.track_url(lastfm_url=lastfm_url, artist=artist, title=title)
            if url_map.get(primary):
                continue
            for url in candidates:
                if url != primary and url not in url_map and url not in self._memory:
                    alternate_urls.append(url)
        self._fetch_urls(list(dict.fromkeys(alternate_urls)), url_map)

        return self._primary_results(track_urls, url_map)

    def _primary_results(
        self,
        track_urls: list[tuple[str | None, str, str, list[str]]],
        url_map: dict[str, str | None],
    ) -> dict[str, str | None]:
        primary_results: dict[str, str | None] = {}
        for lastfm_url, artist, title, candidates in track_urls:
            primary = self.track_url(lastfm_url=lastfm_url, artist=artist, title=title)
            spotify_id = None
            for url in candidates:
                spotify_id = url_map.get(url)
                if spotify_id:
                    break
            primary_results[primary] = spotify_id
        return primary_results

    def _fetch_urls(self, urls: list[str], url_map: dict[str, str | None]) -> None:
        to_fetch = [url for url in urls if url not in self._memory and url not in url_map]
        if not to_fetch:
            return

        cached = self._cache.get_lastfm_many(to_fetch)
        still_fetch: list[str] = []
        for url in to_fetch:
            if url in self._memory:
                url_map[url] = self._memory[url]
                continue
            hit, value = cached.get(url, (False, None))
            if hit and value:
                self._memory[url] = value
                url_map[url] = value
            elif not hit:
                still_fetch.append(url)

        if not still_fetch:
            return

        fetched: dict[str, str | None] = {}
        with ThreadPoolExecutor(max_workers=LASTFM_RESOLVE_WORKERS) as executor:
            futures = {
                executor.submit(self._fetch_spotify_id, url): url for url in still_fetch
            }
            for future in as_completed(futures):
                url = futures[future]
                try:
                    fetched[url] = future.result()
                except Exception:
                    fetched[url] = None

        successes = {url: sid for url, sid in fetched.items() if sid}
        self._cache.set_lastfm_many(successes)
        for url, spotify_id in fetched.items():
            self._memory[url] = spotify_id
            url_map[url] = spotify_id

    def _fetch_spotify_id(self, lastfm_url: str) -> str | None:
        try:
            response = self._session.get(lastfm_url, timeout=10)
            response.raise_for_status()
        except requests.RequestException:
            return None

        matches = SPOTIFY_TRACK_RE.findall(response.text)
        return matches[0] if matches else None
