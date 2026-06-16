"""Low-level Spotify playlist track operations."""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from spotipy.exceptions import SpotifyException
from urllib3.util.retry import Retry

SPOTIFY_API = "https://api.spotify.com/v1"
BATCH_SIZE = 100

_session: requests.Session | None = None


def _http_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        retry = Retry(total=2, backoff_factor=0.1, status_forcelist=(429, 500, 502, 503, 504))
        adapter = HTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=retry)
        _session.mount("https://", adapter)
    return _session


def add_tracks_to_playlist(
    access_token: str,
    playlist_id: str,
    uris: list[str],
    *,
    append: bool = True,
) -> None:
    """Add track URIs to a playlist.

    When append=True (default), always POST so tracks are added to the end.
    When append=False, the first batch PUT-replaces (for single-shot small playlists).
    """
    if not uris:
        return

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    session = _http_session()

    for index in range(0, len(uris), BATCH_SIZE):
        batch = uris[index : index + BATCH_SIZE]
        url = f"{SPOTIFY_API}/playlists/{playlist_id}/items"
        payload = {"uris": batch}

        if append or index > 0:
            response = session.post(url, headers=headers, json=payload, timeout=30)
        else:
            response = session.put(url, headers=headers, json=payload, timeout=30)

        if response.status_code in (200, 201):
            continue

        response = session.post(url, headers=headers, json=batch, timeout=30)
        if response.status_code in (200, 201):
            continue

        message = _response_message(response)
        raise SpotifyException(response.status_code, -1, message)


def _response_message(response: requests.Response) -> str:
    try:
        payload = response.json()
        error = payload.get("error", {})
        if isinstance(error, dict):
            return error.get("message") or response.text
        return response.text
    except ValueError:
        return response.text or "Unknown Spotify error"
