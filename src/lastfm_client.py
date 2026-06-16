"""Last.fm API client."""

from __future__ import annotations

import requests

from .config import LASTFM_PAGE_SIZE
from .date_range import DateRange, date_range_to_unix
from .models import MAX_TRACK_LIMIT, Track

BASE_URL = "https://ws.audioscrobbler.com/2.0/"
PAGE_SIZE = LASTFM_PAGE_SIZE


class LastFmError(Exception):
    pass


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
        response = self.session.get(BASE_URL, params=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            code = data.get("error")
            message = data.get("message", "Unknown Last.fm error")
            raise LastFmError(f"Last.fm error {code}: {message}")
        return data

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

        while len(tracks) < limit:
            remaining = limit - len(tracks)
            data = self._get(
                "user.getTopTracks",
                user=username,
                period=period,
                limit=min(PAGE_SIZE, remaining),
                page=page,
            )
            batch = data.get("toptracks", {}).get("track", [])
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

            if len(batch) < PAGE_SIZE:
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
            data = self._get(
                "user.getRecentTracks",
                user=username,
                limit=page_size,
                page=page,
                **{"from": from_ts, "to": to_ts},
            )
            recent = data.get("recenttracks", {})
            batch = recent.get("track", [])
            if not batch:
                break
            if isinstance(batch, dict):
                batch = [batch]

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

        while len(tracks) < limit:
            remaining = limit - len(tracks)
            data = self._get(
                "user.getLovedTracks",
                user=username,
                limit=min(PAGE_SIZE, remaining),
                page=page,
            )
            batch = data.get("lovedtracks", {}).get("track", [])
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

            if len(batch) < PAGE_SIZE:
                break
            page += 1

        return tracks
