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


def public_base_url() -> str | None:
    """Canonical HTTPS URL when deployed."""
    app_url = _get("APP_URL")
    if app_url:
        return app_url.rstrip("/")

    prod_url = _get("VERCEL_PROJECT_PRODUCTION_URL")
    if prod_url:
        return f"https://{prod_url.rstrip('/')}"

    vercel_url = _get("VERCEL_URL")
    if vercel_url:
        return f"https://{vercel_url.rstrip('/')}"

    render_url = _get("RENDER_EXTERNAL_URL")
    if render_url:
        return render_url.rstrip("/")
    return None


def spotify_redirect_uri() -> str:
    explicit = _get("SPOTIFY_REDIRECT_URI")
    if explicit:
        return explicit
    base = public_base_url()
    if base:
        return f"{base}/callback"
    return "http://127.0.0.1:5000/callback"


def is_production() -> bool:
    return bool(_get("VERCEL") or _get("RENDER") or _get("FLASK_ENV") == "production")


def cache_dir() -> Path:
    """Writable cache directory (Vercel only allows /tmp)."""
    if _get("VERCEL"):
        return Path("/tmp/lastfm-playlist-maker")
    return PROJECT_ROOT / ".cache"


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


LASTFM_PAGE_SIZE = _int_env("LASTFM_PAGE_SIZE", 200)

# Chunked playlist builds (Vercel timeout). ~50 tracks/chunk ≈ few seconds of search.
PLAYLIST_CHUNK_SIZE = _int_env("PLAYLIST_CHUNK_SIZE", 50)
PLAYLIST_CHUNK_THRESHOLD = _int_env("PLAYLIST_CHUNK_THRESHOLD", 200)


def should_chunk_playlist(track_count: int) -> bool:
    """Process large playlists in multiple requests to avoid serverless timeouts."""
    if track_count <= PLAYLIST_CHUNK_THRESHOLD:
        return False
    return True
