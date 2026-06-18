"""Spotify: login, search, create playlist."""

from __future__ import annotations

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
from ..spotify_match import resolve_tracks
from ..spotify_playlist import add_tracks_to_playlist

if TYPE_CHECKING:
    from spotipy.cache_handler import CacheHandler

SCOPES = "playlist-modify-public playlist-modify-private"


class SpotifyDestination(PlaylistDestination):
    def __init__(
        self,
        *,
        cache_handler: CacheHandler | None = None,
        open_browser: bool = True,
    ):
        self._cache_handler = cache_handler
        self._open_browser = open_browser
        self._client: spotipy.Spotify | None = None
        self._auth: SpotifyOAuth | None = None

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

    def resolve_tracks(self, tracks: list[Track]) -> tuple[list[str], list[Track]]:
        return resolve_tracks(self.client, tracks)

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
