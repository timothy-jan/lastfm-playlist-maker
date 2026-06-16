"""CLI entry point."""

from __future__ import annotations

import click

from .config import lastfm_api_key
from .destinations.base import NotImplementedDestination
from .destinations.spotify import SpotifyDestination
from .lastfm_client import LastFmClient, LastFmError
from .models import MAX_TRACK_LIMIT, TIME_PERIODS
from .playlist_builder import create_playlist_from_lastfm


@click.command()
@click.argument("username")
@click.option(
    "--source",
    type=click.Choice(["top", "loved", "both"], case_sensitive=False),
    default="top",
    help="Use top tracks, loved tracks, or both.",
)
@click.option(
    "--period",
    type=click.Choice(list(TIME_PERIODS.keys()), case_sensitive=False),
    default="overall",
    help="Time range for top tracks.",
)
@click.option("--from-date", "date_from", default=None, help="Custom range start (YYYY-MM-DD). Use with --period custom.")
@click.option("--to-date", "date_to", default=None, help="Custom range end (YYYY-MM-DD). Use with --period custom.")
@click.option("--min-plays", type=int, default=None, help="Minimum play count (top tracks only).")
@click.option(
    "--limit",
    type=click.IntRange(1, MAX_TRACK_LIMIT),
    default=50,
    help="Maximum number of tracks to include.",
)
@click.option("--name", "playlist_name", default=None, help="Custom Spotify playlist name.")
@click.option(
    "--destination",
    type=click.Choice(["spotify", "apple", "youtube"], case_sensitive=False),
    default="spotify",
    help="Where to create the playlist.",
)
def main(
    username: str,
    source: str,
    period: str,
    date_from: str | None,
    date_to: str | None,
    min_plays: int | None,
    limit: int,
    playlist_name: str | None,
    destination: str,
) -> None:
    """Create a playlist from a Last.fm username."""
    if period == "custom" and (not date_from or not date_to):
        raise click.ClickException("Custom period requires --from-date and --to-date (YYYY-MM-DD).")

    lastfm = LastFmClient(lastfm_api_key())

    if destination == "spotify":
        dest = SpotifyDestination()
    elif destination == "apple":
        dest = NotImplementedDestination("Apple Music")
    else:
        dest = NotImplementedDestination("YouTube Music")

    try:
        result = create_playlist_from_lastfm(
            lastfm,
            dest,
            username,
            source=source,
            period=period,
            limit=limit,
            min_plays=min_plays,
            playlist_name=playlist_name,
            date_from=date_from,
            date_to=date_to,
        )
    except LastFmError as exc:
        raise click.ClickException(str(exc)) from exc
    except NotImplementedError as exc:
        raise click.ClickException(str(exc)) from exc
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"\nFound Last.fm user: {result.lastfm_user}")
    click.echo(f"Fetched {len(result.tracks)} track(s) from Last.fm.")

    if result.create_result:
        cr = result.create_result
        click.echo(f"Added {cr.matched} of {cr.total} tracks to Spotify playlist.")
        if cr.not_found:
            click.echo(f"\nCould not match {len(cr.not_found)} track(s) on Spotify:")
            for track in cr.not_found[:10]:
                click.echo(f"  - {track.display}")
            if len(cr.not_found) > 10:
                click.echo(f"  ... and {len(cr.not_found) - 10} more")

    click.echo(f"\nDone! Playlist URL: {result.url}")


if __name__ == "__main__":
    main()
