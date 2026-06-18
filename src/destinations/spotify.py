"""Spotify playlist destination."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import spotipy
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyOAuth

from ..config import (
    has_spotify_config,
    spotify_client_id,
    spotify_client_secret,
    spotify_redirect_uri,
)
from ..destinations.base import PlaylistDestination
from ..models import PlaylistCreateResult, Track
from ..spotify_playlist import add_tracks_to_playlist
from ..track_cache import TrackCache
from ..track_resolver import TrackResolver

if TYPE_CHECKING:
    from spotipy.cache_handler import CacheHandler

SCOPES = "playlist-modify-public playlist-modify-private"


class SpotifyDestination(PlaylistDestination):
    def __init__(
        self,
        *,
        cache_handler: CacheHandler | None = None,
        open_browser: bool = True,
        track_cache: TrackCache | None = None,
    ):
        self._cache_handler = cache_handler
        self._open_browser = open_browser
        self._track_cache = track_cache or TrackCache.shared()
        self._client: spotipy.Spotify | None = None
        self._auth: SpotifyOAuth | None = None
        self._thread_local = threading.local()
        self._worker_token: str | None = None
        self._rate_limited = threading.Event()

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
        if not query or self._rate_limited.is_set():
            return []
        for attempt in range(3):
            try:
                result = self._thread_client().search(q=query, type="track", limit=10)
                return result.get("tracks", {}).get("items", [])
            except SpotifyException as exc:
                if exc.http_status == 429:
                    retry_after = 1.0
                    if exc.headers:
                        retry_after = float(exc.headers.get("Retry-After", retry_after))
                    if retry_after > 10 or attempt >= 2:
                        self._rate_limited.set()
                        return []
                    time.sleep(min(retry_after, 3.0))
                    continue
                raise
        return []

    def _make_resolver(self) -> TrackResolver:
        return TrackResolver(
            cache=self._track_cache,
            search=self._spotify_search,
            rate_limited=self._rate_limited,
        )

    def resolve_tracks(self, tracks: list[Track]) -> tuple[list[str], list[Track]]:
        try:
            self._worker_token = self._access_token()
        except SpotifyException:
            self._worker_token = None
        self._rate_limited.clear()
        return self._make_resolver().resolve(tracks)

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

    def create_playlist(
        self, name: str, description: str, tracks: list[Track]
    ) -> PlaylistCreateResult:
        uris, not_found = self.resolve_tracks(tracks)

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
