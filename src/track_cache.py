"""Persistent cache for Last.fm URL and search lookups."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .config import cache_dir

CACHE_DIR = cache_dir()
CACHE_DB = CACHE_DIR / "spotify_tracks.db"


class TrackCache:
    _instance: TrackCache | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        CACHE_DIR.mkdir(exist_ok=True)
        self._db_lock = threading.Lock()
        self.conn = sqlite3.connect(CACHE_DB, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lastfm_url (
                url TEXT PRIMARY KEY,
                spotify_id TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS track_search (
                artist TEXT NOT NULL,
                title TEXT NOT NULL,
                spotify_uri TEXT NOT NULL,
                PRIMARY KEY (artist, title)
            )
            """
        )
        self.conn.commit()
        self._purge_negative_entries()

    def _purge_negative_entries(self) -> None:
        """Remove cached misses so improved matching can retry."""
        with self._db_lock:
            self.conn.execute("DELETE FROM lastfm_url WHERE spotify_id = ''")
            self.conn.execute("DELETE FROM track_search WHERE spotify_uri = ''")
            self.conn.commit()

    @classmethod
    def shared(cls) -> TrackCache:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def get_lastfm(self, url: str) -> tuple[bool, str | None]:
        row = self.conn.execute(
            "SELECT spotify_id FROM lastfm_url WHERE url = ?", (url,)
        ).fetchone()
        if row is None:
            return False, None
        value = row[0]
        if not value:
            return False, None
        return True, value

    def set_lastfm(self, url: str, spotify_id: str | None) -> None:
        if not spotify_id:
            return
        with self._db_lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO lastfm_url (url, spotify_id) VALUES (?, ?)",
                (url, spotify_id),
            )
            self.conn.commit()

    def get_lastfm_many(self, urls: list[str]) -> dict[str, tuple[bool, str | None]]:
        if not urls:
            return {}
        placeholders = ",".join("?" for _ in urls)
        rows = self.conn.execute(
            f"SELECT url, spotify_id FROM lastfm_url WHERE url IN ({placeholders})",
            urls,
        ).fetchall()
        found = {
            url: (True, spotify_id)
            for url, spotify_id in rows
            if spotify_id
        }
        return {url: found.get(url, (False, None)) for url in urls}

    def set_lastfm_many(self, entries: dict[str, str | None]) -> None:
        successes = [(url, sid) for url, sid in entries.items() if sid]
        if not successes:
            return
        with self._db_lock:
            self.conn.executemany(
                "INSERT OR REPLACE INTO lastfm_url (url, spotify_id) VALUES (?, ?)",
                successes,
            )
            self.conn.commit()

    def get_search(self, artist: str, title: str) -> tuple[bool, str | None]:
        row = self.conn.execute(
            "SELECT spotify_uri FROM track_search WHERE artist = ? AND title = ?",
            (artist, title),
        ).fetchone()
        if row is None:
            return False, None
        value = row[0]
        if not value:
            return False, None
        return True, value

    def set_search(self, artist: str, title: str, spotify_uri: str | None) -> None:
        if not spotify_uri:
            return
        with self._db_lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO track_search (artist, title, spotify_uri) VALUES (?, ?, ?)",
                (artist, title, spotify_uri),
            )
            self.conn.commit()
