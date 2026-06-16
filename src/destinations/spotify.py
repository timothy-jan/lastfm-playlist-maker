"""Spotify playlist destination."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

import spotipy
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyOAuth

from ..config import (
    SPOTIFY_SEARCH_WORKERS,
    has_spotify_config,
    spotify_client_id,
    spotify_client_secret,
    spotify_redirect_uri,
)
from ..destinations.base import PlaylistDestination
from ..lastfm_spotify_resolver import LastFmSpotifyResolver
from ..models import PlaylistCreateResult, Track
from ..spotify_playlist import add_tracks_to_playlist
from ..track_cache import TrackCache
from ..track_matcher import (
    fast_search_queries,
    is_acceptable_match,
    pick_best_match,
    search_queries,
)

if TYPE_CHECKING:
    from spotipy.cache_handler import CacheHandler

SCOPES = "playlist-modify-public playlist-modify-private"
SEARCH_LIMIT = 20


def _track_key(track: Track) -> tuple[str, str]:
    return track.artist.casefold(), track.title.casefold()


class SpotifyDestination(PlaylistDestination):
    def __init__(
        self,
        *,
        cache_handler: CacheHandler | None = None,
        open_browser: bool = True,
        lastfm_resolver: LastFmSpotifyResolver | None = None,
        track_cache: TrackCache | None = None,
    ):
        self._cache_handler = cache_handler
        self._open_browser = open_browser
        self._track_cache = track_cache or TrackCache.shared()
        self._lastfm_resolver = lastfm_resolver or LastFmSpotifyResolver(self._track_cache)
        self._client: spotipy.Spotify | None = None
        self._auth: SpotifyOAuth | None = None
        self._thread_local = threading.local()
        # Access token captured in the request thread for use by worker threads.
        # Flask's session proxy cannot be read outside the request context, so
        # threaded searches must use a plain token-based client instead of the
        # session-backed auth manager.
        self._worker_token: str | None = None

    @property
    def auth(self) -> SpotifyOAuth:
        if self._auth is None:
            self._auth = SpotifyOAuth(
                client_id=spotify_client_id(),
                client_secret=spotify_client_secret(),
                redirect_uri=spotify_redirect_uri(),
                scope=SCOPES,
                cache_handler=self._cache_handler,
                open_browser=self._open_browser,
                show_dialog=True,
            )
        return self._auth

    @property
    def client(self) -> spotipy.Spotify:
        if self._client is None:
            self._client = spotipy.Spotify(auth_manager=self.auth)
        return self._client

    def _thread_client(self) -> spotipy.Spotify:
        """Token-based client safe to use inside worker threads.

        Uses the access token captured in the request thread so it never touches
        the Flask session proxy (which is unavailable outside a request context).
        """
        token = self._worker_token
        client = getattr(self._thread_local, "client", None)
        cached_token = getattr(self._thread_local, "token", None)
        if client is None or cached_token != token:
            if token:
                client = spotipy.Spotify(auth=token)
            else:
                client = spotipy.Spotify(auth_manager=self.auth)
            self._thread_local.client = client
            self._thread_local.token = token
        return client

    def is_authenticated(self) -> bool:
        if not has_spotify_config():
            return False
        return self.auth.get_cached_token() is not None

    def get_authorize_url(self) -> str:
        return self.auth.get_authorize_url()

    def complete_auth(self, code: str) -> None:
        self.auth.get_access_token(code, as_dict=True)

    def _access_token(self) -> str:
        token_info = self.auth.get_cached_token()
        if not token_info or "access_token" not in token_info:
            raise SpotifyException(401, -1, "Spotify session expired. Connect again.")
        return token_info["access_token"]

    def _spotify_search(self, query: str) -> list[dict]:
        if not query:
            return []
        for attempt in range(4):
            try:
                result = self._thread_client().search(
                    q=query, type="track", limit=SEARCH_LIMIT
                )
                return result.get("tracks", {}).get("items", [])
            except SpotifyException as exc:
                if exc.http_status == 429 and attempt < 3:
                    retry_after = 1.0
                    if exc.headers:
                        retry_after = float(exc.headers.get("Retry-After", retry_after))
                    time.sleep(min(retry_after, 5.0))
                    continue
                return []
            except Exception:
                # Never let an unexpected error (e.g. transient network) kill the
                # whole batch — just treat this query as a miss.
                return []
        return []

    def _search_track(self, track: Track, *, relaxed: bool = False) -> str | None:
        if not relaxed:
            hit, cached_uri = self._track_cache.get_search(track.artist, track.title)
            if hit and cached_uri:
                return cached_uri

        ordered = search_queries(track) if relaxed else fast_search_queries(track)
        candidates: dict[str, dict] = {}

        for query in ordered:
            for item in self._spotify_search(query):
                uri = item.get("uri")
                if uri:
                    candidates[uri] = item

            # Early exit on the fast pass once we have a confident strict match,
            # to keep request volume (and rate-limit risk) low on big playlists.
            if not relaxed and candidates:
                strict_uri = pick_best_match(
                    track, list(candidates.values()), relaxed=False
                )
                if strict_uri and any(
                    is_acceptable_match(track, item, tier="strict")
                    for item in candidates.values()
                ):
                    self._track_cache.set_search(track.artist, track.title, strict_uri)
                    return strict_uri

        uri = pick_best_match(track, list(candidates.values()), relaxed=relaxed)
        if uri and not relaxed:
            self._track_cache.set_search(track.artist, track.title, uri)
        return uri

    def _spotify_track_items(self, uris: list[str]) -> dict[str, dict | None]:
        if not uris:
            return {}

        ids = [uri.rsplit(":", 1)[-1] for uri in uris]
        items: dict[str, dict | None] = {}
        for start in range(0, len(ids), 50):
            chunk_ids = ids[start : start + 50]
            chunk_uris = uris[start : start + 50]
            try:
                response = self.client.tracks(chunk_ids)
            except SpotifyException:
                for uri in chunk_uris:
                    items[uri] = None
                continue

            for uri, item in zip(chunk_uris, response.get("tracks", [])):
                items[uri] = item
        return items

    def _validate_lastfm_uri(self, track: Track, uri: str, item: dict | None) -> bool:
        # Non-destructive: if Spotify metadata is unavailable (API error, rate
        # limit, missing track), trust the Last.fm-embedded link rather than
        # dropping a likely-correct match. Only reject on a confirmed mismatch.
        if not item:
            return True
        spotify_item = {
            "name": item.get("name", ""),
            "artists": item.get("artists", []),
            "uri": uri,
        }
        return is_acceptable_match(track, spotify_item, tier="best_effort")

    def _search_tracks_parallel(
        self, tracks: list[Track], *, relaxed: bool = False
    ) -> dict[int, str | None]:
        if not tracks:
            return {}

        results: dict[int, str | None] = {}

        if len(tracks) == 1:
            results[0] = self._search_track(tracks[0], relaxed=relaxed)
            return results

        with ThreadPoolExecutor(max_workers=SPOTIFY_SEARCH_WORKERS) as executor:
            futures = {
                executor.submit(self._search_track, track, relaxed=relaxed): index
                for index, track in enumerate(tracks)
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    results[index] = future.result()
                except Exception:
                    results[index] = None
        return results

    def _resolve_all_tracks(self, tracks: list[Track]) -> tuple[list[str], list[Track]]:
        if not tracks:
            return [], []

        # Capture a valid access token in the request thread so worker threads
        # can search Spotify without touching the Flask session proxy.
        try:
            self._worker_token = self._access_token()
        except SpotifyException:
            self._worker_token = None

        url_by_index: list[str] = [
            self._lastfm_resolver.track_url(
                lastfm_url=track.lastfm_url,
                artist=track.artist,
                title=track.title,
            )
            for track in tracks
        ]

        lastfm_ids = self._lastfm_resolver.resolve_many(
            [(track.lastfm_url, track.artist, track.title) for track in tracks]
        )

        resolved: list[str | None] = [None] * len(tracks)
        uri_by_key: dict[tuple[str, str], str] = {}
        cache_writes: list[tuple[str, str, str]] = []

        for index, track in enumerate(tracks):
            spotify_id = lastfm_ids.get(url_by_index[index])
            if spotify_id:
                uri = LastFmSpotifyResolver.to_spotify_uri(spotify_id)
                resolved[index] = uri
                uri_by_key[_track_key(track)] = uri

        lastfm_validation: dict[str, dict | None] = {}
        lastfm_uris = [uri for uri in resolved if uri]
        if lastfm_uris:
            lastfm_validation = self._spotify_track_items(lastfm_uris)

        for index, track in enumerate(tracks):
            uri = resolved[index]
            if not uri:
                continue
            if self._validate_lastfm_uri(track, uri, lastfm_validation.get(uri)):
                cache_writes.append((track.artist, track.title, uri))
                continue
            resolved[index] = None
            uri_by_key.pop(_track_key(track), None)

        need_search: list[Track] = []
        need_search_indices: list[int] = []
        for index, track in enumerate(tracks):
            if resolved[index]:
                continue
            key = _track_key(track)
            if key in uri_by_key:
                resolved[index] = uri_by_key[key]
                continue
            need_search.append(track)
            need_search_indices.append(index)

        if need_search:
            unique_groups: dict[tuple[str, str], list[int]] = {}
            unique_tracks: list[Track] = []
            for track, index in zip(need_search, need_search_indices):
                key = _track_key(track)
                if key not in unique_groups:
                    unique_groups[key] = []
                    unique_tracks.append(track)
                unique_groups[key].append(index)

            pairs = [(track.artist, track.title) for track in unique_tracks]
            cached = self._track_cache.get_search_many(pairs)
            still_search: list[Track] = []
            still_search_keys: list[tuple[str, str]] = []
            for track in unique_tracks:
                key = _track_key(track)
                hit, uri = cached.get((track.artist, track.title), (False, None))
                if hit and uri:
                    uri_by_key[key] = uri
                    for index in unique_groups[key]:
                        resolved[index] = uri
                else:
                    still_search.append(track)
                    still_search_keys.append(key)

            if still_search:
                search_uris = self._search_tracks_parallel(still_search, relaxed=False)
                for position, key in enumerate(still_search_keys):
                    uri = search_uris.get(position)
                    if uri:
                        uri_by_key[key] = uri
                        for index in unique_groups[key]:
                            resolved[index] = uri

        retry_indices = [index for index, uri in enumerate(resolved) if not uri]
        if retry_indices:
            retry_groups: dict[tuple[str, str], list[int]] = {}
            retry_tracks: list[Track] = []
            for index in retry_indices:
                track = tracks[index]
                key = _track_key(track)
                if key not in retry_groups:
                    retry_groups[key] = []
                    retry_tracks.append(track)
                retry_groups[key].append(index)

            retry_uris = self._search_tracks_parallel(retry_tracks, relaxed=True)
            for position, track in enumerate(retry_tracks):
                uri = retry_uris.get(position)
                if not uri:
                    continue
                key = _track_key(track)
                for index in retry_groups[key]:
                    resolved[index] = uri
                cache_writes.append((track.artist, track.title, uri))

        if cache_writes:
            self._track_cache.set_search_many(cache_writes)

        uris = [uri for uri in resolved if uri]
        not_found = [track for uri, track in zip(resolved, tracks) if not uri]
        return uris, not_found

    def resolve_tracks(self, tracks: list[Track]) -> tuple[list[str], list[Track]]:
        return self._resolve_all_tracks(tracks)

    def create_empty_playlist(self, name: str, description: str) -> tuple[str, str]:
        playlist = self.client.current_user_playlist_create(
            name, public=True, description=description
        )
        return playlist["id"], playlist["external_urls"]["spotify"]

    def append_tracks(self, playlist_id: str, uris: list[str]) -> None:
        if uris:
            add_tracks_to_playlist(
                self._access_token(), playlist_id, uris, append=True
            )

    def create_playlist(self, name: str, description: str, tracks: list[Track]) -> PlaylistCreateResult:
        uris, not_found = self._resolve_all_tracks(tracks)

        playlist = self.client.current_user_playlist_create(
            name, public=True, description=description
        )
        playlist_id = playlist["id"]
        playlist_url = playlist["external_urls"]["spotify"]

        if uris:
            self.append_tracks(playlist_id, uris)

        return PlaylistCreateResult(
            url=playlist_url,
            matched=len(uris),
            total=len(tracks),
            not_found=not_found,
        )
