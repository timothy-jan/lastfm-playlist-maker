"""Last.fm API client."""

from __future__ import annotations

import time

import requests

from .config import LASTFM_PAGE_SIZE
from .date_range import DateRange, date_range_to_unix
from .models import MAX_TRACK_LIMIT, Track

BASE_URL = "https://ws.audioscrobbler.com/2.0/"
PAGE_SIZE = min(LASTFM_PAGE_SIZE, 200)


class LastFmError(Exception):
    pass


def _as_track_list(value) -> list:
    if not value:
        return []
    if isinstance(value, dict):
        return [value]
    return value


def _parse_attr_int(value, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class LastFmClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()

    def _get(self, method: str, **params) -> dict:
        payload = {
            "method": method,
            "api_key": self.api_key,
            "format": "json",
            **params,
        }
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self.session.get(BASE_URL, params=payload, timeout=30)
                response.raise_for_status()
                data = response.json()
                if "error" in data:
                    code = data.get("error")
                    message = data.get("message", "Unknown Last.fm error")
                    raise LastFmError(f"Last.fm error {code}: {message}")
                return data
            except requests.HTTPError as exc:
                last_error = exc
                status = exc.response.status_code if exc.response is not None else 0
                if status in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(0.4 * (attempt + 1))
                    continue
                raise LastFmError(
                    f"Last.fm request failed ({status}). Try again in a moment."
                ) from exc
            except requests.RequestException as exc:
                raise LastFmError(f"Could not reach Last.fm: {exc}") from exc

        if last_error:
            raise LastFmError("Last.fm request failed. Try again in a moment.") from last_error
        raise LastFmError("Last.fm request failed. Try again in a moment.")

    def verify_user(self, username: str) -> dict:
        """Return basic profile info; raises if user does not exist."""
        data = self._get("user.getInfo", user=username)
        return data["user"]

    def get_top_tracks(
        self,
        username: str,
        *,
        period: str = "overall",
        limit: int = 1000,
        min_plays: int | None = None,
    ) -> list[Track]:
        limit = min(limit, MAX_TRACK_LIMIT)
        tracks: list[Track] = []
        page = 1
        total_pages: int | None = None

        while len(tracks) < limit:
            if total_pages is not None and page > total_pages:
                break

            remaining = limit - len(tracks)
            batch_limit = min(PAGE_SIZE, remaining)
            try:
                data = self._get(
                    "user.getTopTracks",
                    user=username,
                    period=period,
                    limit=batch_limit,
                    page=page,
                )
            except LastFmError:
                if tracks and page > 1:
                    break
                raise

            toptracks = data.get("toptracks", {})
            attrs = toptracks.get("@attr", {})
            if total_pages is None:
                total_pages = _parse_attr_int(attrs.get("totalPages"))

            batch = _as_track_list(toptracks.get("track"))
            if not batch:
                break

            for item in batch:
                playcount = int(item.get("playcount", 0))
                if min_plays is not None and playcount < min_plays:
                    continue
                artist = item.get("artist", {})
                name = artist.get("name") if isinstance(artist, dict) else str(artist)
                tracks.append(
                    Track(
                        artist=name,
                        title=item["name"],
                        playcount=playcount,
                        lastfm_url=item.get("url") or None,
                    )
                )
                if len(tracks) >= limit:
                    break

            if len(batch) < batch_limit:
                break
            page += 1

        return tracks

    def get_top_tracks_in_range(
        self,
        username: str,
        date_range: DateRange,
        *,
        limit: int = 1000,
        min_plays: int | None = None,
    ) -> list[Track]:
        """Aggregate scrobbles between two dates into ranked top tracks."""
        from_ts, to_ts = date_range_to_unix(date_range)
        limit = min(limit, MAX_TRACK_LIMIT)

        counts: dict[tuple[str, str], tuple[int, str | None]] = {}
        page = 1
        page_size = min(PAGE_SIZE, 200)

        while True:
            try:
                data = self._get(
                    "user.getRecentTracks",
                    user=username,
                    limit=page_size,
                    page=page,
                    **{"from": from_ts, "to": to_ts},
                )
            except LastFmError:
                if counts and page > 1:
                    break
                raise

            recent = data.get("recenttracks", {})
            batch = _as_track_list(recent.get("track"))
            if not batch:
                break

            for item in batch:
                attrs = item.get("@attr", {})
                if attrs.get("nowplaying") == "true":
                    continue

                artist = item.get("artist", {})
                if isinstance(artist, dict):
                    artist_name = artist.get("name") or artist.get("#text") or ""
                else:
                    artist_name = str(artist)

                title = item.get("name", "")
                if not artist_name or not title:
                    continue

                key = (artist_name, title)
                playcount, url = counts.get(key, (0, item.get("url")))
                counts[key] = (playcount + 1, url or item.get("url"))

            total_pages = int(recent.get("@attr", {}).get("totalPages", page))
            if page >= total_pages:
                break
            page += 1

        ranked = sorted(counts.items(), key=lambda entry: entry[1][0], reverse=True)
        tracks: list[Track] = []
        for (artist_name, title), (playcount, url) in ranked:
            if min_plays is not None and playcount < min_plays:
                continue
            tracks.append(
                Track(
                    artist=artist_name,
                    title=title,
                    playcount=playcount,
                    lastfm_url=url,
                )
            )
            if len(tracks) >= limit:
                break

        return tracks

    def get_loved_tracks(self, username: str, *, limit: int = 1000) -> list[Track]:
        limit = min(limit, MAX_TRACK_LIMIT)
        tracks: list[Track] = []
        page = 1
        total_pages: int | None = None

        while len(tracks) < limit:
            if total_pages is not None and page > total_pages:
                break

            remaining = limit - len(tracks)
            batch_limit = min(PAGE_SIZE, remaining)
            try:
                data = self._get(
                    "user.getLovedTracks",
                    user=username,
                    limit=batch_limit,
                    page=page,
                )
            except LastFmError:
                if tracks and page > 1:
                    break
                raise

            lovedtracks = data.get("lovedtracks", {})
            attrs = lovedtracks.get("@attr", {})
            if total_pages is None:
                total_pages = _parse_attr_int(attrs.get("totalPages"))

            batch = _as_track_list(lovedtracks.get("track"))
            if not batch:
                break

            for item in batch:
                artist = item.get("artist", {})
                name = artist.get("name") if isinstance(artist, dict) else str(artist)
                tracks.append(
                    Track(
                        artist=name,
                        title=item["name"],
                        loved=True,
                        lastfm_url=item.get("url") or None,
                    )
                )
                if len(tracks) >= limit:
                    break

            if len(batch) < batch_limit:
                break
            page += 1

        return tracks
