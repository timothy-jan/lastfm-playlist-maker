"""Environment and application configuration."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _get(name: str) -> str:
    return os.getenv(name, "").strip()


def _require(name: str) -> str:
    value = _get(name)
    if not value:
        raise RuntimeError(
            f"Missing {name}. Copy .env.example to .env and fill in your credentials."
        )
    return value


def has_lastfm_config() -> bool:
    return bool(_get("LASTFM_API_KEY"))


def has_spotify_config() -> bool:
    return bool(_get("SPOTIFY_CLIENT_ID") and _get("SPOTIFY_CLIENT_SECRET"))


def lastfm_api_key() -> str:
    return _require("LASTFM_API_KEY")


def spotify_client_id() -> str:
    return _require("SPOTIFY_CLIENT_ID")


def spotify_client_secret() -> str:
    return _require("SPOTIFY_CLIENT_SECRET")


def flask_secret_key() -> str:
    return os.getenv("FLASK_SECRET_KEY", "dev-change-me-in-production").strip()


def spotify_redirect_uri() -> str:
    return os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:5000/callback").strip()


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# Performance tuning (override via .env)
LASTFM_PAGE_SIZE = _int_env("LASTFM_PAGE_SIZE", 1000)
LASTFM_RESOLVE_WORKERS = _int_env("LASTFM_RESOLVE_WORKERS", 16)
SPOTIFY_SEARCH_WORKERS = _int_env("SPOTIFY_SEARCH_WORKERS", 4)
