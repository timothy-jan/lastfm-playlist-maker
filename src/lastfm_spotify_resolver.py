"""Resolve Spotify track IDs from Last.fm track pages (fallback only)."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import LASTFM_RESOLVE_WORKERS
from .track_cache import TrackCache

SPOTIFY_TRACK_RE = re.compile(
    r"(?:open\.spotify\.com/track/|spotify:track:)([a-zA-Z0-9]{22})"
)
USER_AGENT = "LastFmPlaylistMaker/1.0"
MAX_READ_BYTES = 120_000
CHUNK_SIZE = 16_384


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
        }
    )
    retry = Retry(total=1, backoff_factor=0.05, status_forcelist=(429, 503))
    workers = min(LASTFM_RESOLVE_WORKERS, 16)
    adapter = HTTPAdapter(pool_connections=workers, pool_maxsize=workers, max_retries=retry)
    session.mount("https://", adapter)
    return session


class LastFmSpotifyResolver:
    """Scrape embedded Spotify IDs from Last.fm pages — used only when search misses."""

    def __init__(self, cache: TrackCache | None = None) -> None:
        self._cache = cache or TrackCache.shared()
        self._session = _build_session()

    @staticmethod
    def build_track_url(artist: str, title: str) -> str:
        from urllib.parse import quote

        return f"https://www.last.fm/music/{quote(artist)}/_/{quote(title)}"

    @staticmethod
    def to_spotify_uri(spotify_id: str) -> str:
        return f"spotify:track:{spotify_id}"

    def track_url(self, *, lastfm_url: str | None, artist: str, title: str) -> str:
        return lastfm_url or self.build_track_url(artist, title)

    def resolve_urls(self, urls: list[str]) -> dict[str, str | None]:
        """Fetch Spotify IDs for a deduplicated list of Last.fm URLs."""
        unique = list(dict.fromkeys(urls))
        if not unique:
            return {}

        result: dict[str, str | None] = {}
        cached = self._cache.get_lastfm_many(unique)
        to_fetch: list[str] = []

        for url in unique:
            hit, spotify_id = cached.get(url, (False, None))
            if hit and spotify_id:
                result[url] = spotify_id
            elif not hit:
                to_fetch.append(url)

        if not to_fetch:
            return result

        workers = min(LASTFM_RESOLVE_WORKERS, 16, len(to_fetch))
        fetched: dict[str, str | None] = {}

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(self._fetch_id, url): url for url in to_fetch}
            for future in as_completed(futures):
                url = futures[future]
                try:
                    fetched[url] = future.result()
                except Exception:
                    fetched[url] = None

        successes = {url: sid for url, sid in fetched.items() if sid}
        if successes:
            self._cache.set_lastfm_many(successes)

        result.update(fetched)
        return result

    def _fetch_id(self, url: str) -> str | None:
        try:
            with self._session.get(url, stream=True, timeout=(2, 6)) as response:
                response.raise_for_status()
                buffer = []
                size = 0
                for chunk in response.iter_content(CHUNK_SIZE):
                    if not chunk:
                        continue
                    buffer.append(chunk)
                    size += len(chunk)
                    text = b"".join(buffer).decode("utf-8", errors="ignore")
                    match = SPOTIFY_TRACK_RE.search(text)
                    if match:
                        return match.group(1)
                    if size >= MAX_READ_BYTES:
                        break
        except requests.RequestException:
            return None
        return None
