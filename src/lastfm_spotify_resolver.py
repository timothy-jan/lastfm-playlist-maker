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
        all_urls: set[str] = set()

        for lastfm_url, artist, title in tracks:
            primary = self.track_url(lastfm_url=lastfm_url, artist=artist, title=title)
            candidates = self.candidate_urls(
                lastfm_url=lastfm_url, artist=artist, title=title
            )
            track_urls.append((lastfm_url, artist, title, candidates))
            all_urls.update(candidates)

        url_map: dict[str, str | None] = {url: None for url in all_urls}
        cached = self._cache.get_lastfm_many(list(all_urls))
        to_fetch: list[str] = []

        for url in all_urls:
            if url in self._memory:
                url_map[url] = self._memory[url]
                continue
            hit, value = cached.get(url, (False, None))
            if hit and value:
                self._memory[url] = value
                url_map[url] = value
            elif not hit:
                to_fetch.append(url)

        if to_fetch:
            fetched: dict[str, str | None] = {}
            with ThreadPoolExecutor(max_workers=LASTFM_RESOLVE_WORKERS) as executor:
                futures = {
                    executor.submit(self._fetch_spotify_id, url): url for url in to_fetch
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

    def _fetch_spotify_id(self, lastfm_url: str) -> str | None:
        try:
            response = self._session.get(lastfm_url, timeout=15)
            response.raise_for_status()
        except requests.RequestException:
            return None

        matches = SPOTIFY_TRACK_RE.findall(response.text)
        return matches[0] if matches else None
