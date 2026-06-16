"""Playlist destination abstraction for future Apple Music / YouTube Music support."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import PlaylistCreateResult, Track


class PlaylistDestination(ABC):
    @abstractmethod
    def create_playlist(
        self, name: str, description: str, tracks: list[Track]
    ) -> PlaylistCreateResult:
        """Create a playlist and return details including the URL."""


class NotImplementedDestination(PlaylistDestination):
    """Placeholder for destinations not yet built."""

    def __init__(self, service_name: str):
        self.service_name = service_name

    def create_playlist(
        self, name: str, description: str, tracks: list[Track]
    ) -> PlaylistCreateResult:
        raise NotImplementedError(
            f"{self.service_name} support is planned but not implemented yet."
        )
