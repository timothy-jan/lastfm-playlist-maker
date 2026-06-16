"""Shared data models."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Track:
    artist: str
    title: str
    playcount: int | None = None
    loved: bool = False
    lastfm_url: str | None = None

    @property
    def display(self) -> str:
        return f"{self.artist} — {self.title}"


@dataclass
class PlaylistCreateResult:
    url: str
    matched: int
    total: int
    not_found: list[Track] = field(default_factory=list)


@dataclass
class BuildResult:
    url: str
    tracks: list[Track]
    playlist_name: str
    lastfm_user: str
    create_result: PlaylistCreateResult | None = None


# Last.fm chart periods
TIME_PERIODS = {
    "7day": "Past 7 days",
    "1month": "Past month",
    "3month": "Past 3 months",
    "6month": "Past 6 months",
    "12month": "Past year",
    "overall": "All time",
    "custom": "Pick your own dates…",
}

MAX_TRACK_LIMIT = 10_000
