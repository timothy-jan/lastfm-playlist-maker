"""Build playlists from Last.fm data."""

from __future__ import annotations

from .date_range import DateRange, format_date_range_human, parse_date_range
from .destinations.base import PlaylistDestination
from .lastfm_client import LastFmClient
from .models import TIME_PERIODS, BuildResult, Track


def _dedupe_tracks(tracks: list[Track]) -> list[Track]:
    seen: set[tuple[str, str]] = set()
    unique: list[Track] = []
    for track in tracks:
        key = (track.artist.lower(), track.title.lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(track)
    return unique


def period_label(period: str, date_range: DateRange | None = None) -> str:
    if period == "custom" and date_range:
        return format_date_range_human(date_range)
    return TIME_PERIODS.get(period, period)


def fetch_tracks(
    client: LastFmClient,
    username: str,
    *,
    source: str,
    period: str,
    limit: int,
    min_plays: int | None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[Track]:
    date_range: DateRange | None = None
    if period == "custom":
        date_range, error = parse_date_range(date_from, date_to)
        if error or date_range is None:
            raise RuntimeError(error or "Invalid custom date range.")

    if source == "top":
        if period == "custom" and date_range:
            return client.get_top_tracks_in_range(
                username, date_range, limit=limit, min_plays=min_plays
            )
        return client.get_top_tracks(
            username, period=period, limit=limit, min_plays=min_plays
        )
    if source == "loved":
        return client.get_loved_tracks(username, limit=limit)
    if source == "both":
        if period == "custom" and date_range:
            top = client.get_top_tracks_in_range(
                username, date_range, limit=limit, min_plays=min_plays
            )
        else:
            top = client.get_top_tracks(
                username, period=period, limit=limit, min_plays=min_plays
            )
        loved = client.get_loved_tracks(username, limit=limit)
        return _dedupe_tracks(top + loved)
    raise ValueError(f"Unknown source: {source}")


def default_playlist_name(
    username: str,
    source: str,
    period: str,
    date_range: DateRange | None = None,
) -> str:
    label = period_label(period, date_range)
    if source == "loved":
        return f"{username} — Loved on Last.fm"
    if source == "both":
        return f"{username} — Top + Loved ({label})"
    return f"{username} — Top Tracks ({label})"


def build_playlist_description(
    username: str,
    source: str,
    period: str,
    min_plays: int | None,
    date_range: DateRange | None = None,
) -> str:
    parts = [f"Generated from Last.fm user {username}."]
    if source in ("top", "both"):
        parts.append(f"Period: {period_label(period, date_range)}.")
    if min_plays is not None:
        parts.append(f"Minimum plays: {min_plays}.")
    if source == "loved":
        parts.append("Source: loved tracks.")
    elif source == "both":
        parts.append("Source: top tracks + loved tracks.")
    else:
        parts.append("Source: top tracks.")
    return " ".join(parts)


def prepare_playlist(
    lastfm: LastFmClient,
    username: str,
    *,
    source: str = "top",
    period: str = "overall",
    limit: int = 50,
    min_plays: int | None = None,
    playlist_name: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[list[Track], str, str, str]:
    """Fetch tracks and build playlist metadata without touching Spotify."""
    user = lastfm.verify_user(username)
    display_name = user.get("name", username)

    date_range: DateRange | None = None
    if period == "custom":
        date_range, error = parse_date_range(date_from, date_to)
        if error or date_range is None:
            raise RuntimeError(error or "Invalid custom date range.")

    tracks = fetch_tracks(
        lastfm,
        username,
        source=source,
        period=period,
        limit=limit,
        min_plays=min_plays,
        date_from=date_from,
        date_to=date_to,
    )
    tracks = _dedupe_tracks(tracks)
    if not tracks:
        raise RuntimeError("No tracks matched your filters. Try a wider time range or lower min plays.")

    name = playlist_name or default_playlist_name(username, source, period, date_range)
    description = build_playlist_description(
        username, source, period, min_plays, date_range
    )
    return tracks, name, description, display_name


def create_playlist_from_lastfm(
    lastfm: LastFmClient,
    destination: PlaylistDestination,
    username: str,
    *,
    source: str = "top",
    period: str = "overall",
    limit: int = 50,
    min_plays: int | None = None,
    playlist_name: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> BuildResult:
    tracks, name, description, display_name = prepare_playlist(
        lastfm,
        username,
        source=source,
        period=period,
        limit=limit,
        min_plays=min_plays,
        playlist_name=playlist_name,
        date_from=date_from,
        date_to=date_to,
    )

    create_result = destination.create_playlist(name, description, tracks)
    return BuildResult(
        url=create_result.url,
        tracks=tracks,
        playlist_name=name,
        lastfm_user=display_name,
        create_result=create_result,
    )
