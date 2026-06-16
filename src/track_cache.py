"""Persistent cache for Last.fm URL and search lookups."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .config import cache_dir

CACHE_DIR = cache_dir()
CACHE_DB = CACHE_DIR / "spotify_tracks.db"
MATCHER_CACHE_VERSION = 3


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
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cache_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self.conn.commit()
        self._purge_negative_entries()
        self._ensure_matcher_cache_version()

    def _purge_negative_entries(self) -> None:
        """Remove cached misses so improved matching can retry."""
        with self._db_lock:
            self.conn.execute("DELETE FROM lastfm_url WHERE spotify_id = ''")
            self.conn.execute("DELETE FROM track_search WHERE spotify_uri = ''")
            self.conn.commit()

    def _ensure_matcher_cache_version(self) -> None:
        """Drop stale search cache when matching logic changes."""
        with self._db_lock:
            row = self.conn.execute(
                "SELECT value FROM cache_meta WHERE key = 'matcher_version'"
            ).fetchone()
            current = str(MATCHER_CACHE_VERSION)
            if row and row[0] == current:
                return
            self.conn.execute("DELETE FROM track_search")
            self.conn.execute(
                "INSERT OR REPLACE INTO cache_meta (key, value) VALUES ('matcher_version', ?)",
                (current,),
            )
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

    def get_search_many(
        self, pairs: list[tuple[str, str]]
    ) -> dict[tuple[str, str], tuple[bool, str | None]]:
        if not pairs:
            return {}
        unique = list(dict.fromkeys(pairs))
        placeholders = ",".join("(?, ?)" for _ in unique)
        flat = [part for pair in unique for part in pair]
        rows = self.conn.execute(
            f"SELECT artist, title, spotify_uri FROM track_search WHERE (artist, title) IN ({placeholders})",
            flat,
        ).fetchall()
        found = {
            (artist, title): (True, spotify_uri)
            for artist, title, spotify_uri in rows
            if spotify_uri
        }
        return {pair: found.get(pair, (False, None)) for pair in pairs}

    def set_search_many(self, entries: list[tuple[str, str, str]]) -> None:
        if not entries:
            return
        with self._db_lock:
            self.conn.executemany(
                "INSERT OR REPLACE INTO track_search (artist, title, spotify_uri) VALUES (?, ?, ?)",
                entries,
            )
            self.conn.commit()

    def set_search(self, artist: str, title: str, spotify_uri: str | None) -> None:
        if not spotify_uri:
            return
        with self._db_lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO track_search (artist, title, spotify_uri) VALUES (?, ?, ?)",
                (artist, title, spotify_uri),
            )
            self.conn.commit()
