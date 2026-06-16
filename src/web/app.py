"""Flask web application."""

from __future__ import annotations

import os

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from spotipy.cache_handler import FlaskSessionCacheHandler
from spotipy.exceptions import SpotifyException

from ..config import (
    flask_secret_key,
    has_lastfm_config,
    has_spotify_config,
    is_production,
    lastfm_api_key,
    public_base_url,
    spotify_redirect_uri,
)
from ..demo_data import DEMO_TRACKS
from ..destinations.spotify import SpotifyDestination
from ..lastfm_client import LastFmClient, LastFmError
from ..config import PLAYLIST_CHUNK_SIZE, should_chunk_playlist
from ..date_range import default_custom_range
from ..models import MAX_TRACK_LIMIT, TIME_PERIODS, BuildResult, Track
from ..playlist_builder import fetch_tracks, prepare_playlist

PENDING_FORM_KEY = "pending_form"
LAST_RESULT_KEY = "last_result"
CHUNK_JOB_KEY = "chunk_job"


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = flask_secret_key()

    if is_production():
        app.config["SESSION_COOKIE_SECURE"] = True
        app.config["SESSION_COOKIE_HTTPONLY"] = True
        app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    @app.context_processor
    def inject_globals():
        return {
            "spotify_callback_url": spotify_redirect_uri(),
            "public_base_url": public_base_url(),
            "vercel_analytics": bool(os.getenv("VERCEL")),
        }

    @app.get("/health")
    def health():
        return {"status": "ok"}

    def spotify_destination() -> SpotifyDestination:
        return SpotifyDestination(
            cache_handler=FlaskSessionCacheHandler(session),
            open_browser=False,
        )

    @app.get("/")
    def index():
        spotify = spotify_destination()
        default_range = default_custom_range()
        return render_template(
            "index.html",
            periods=TIME_PERIODS,
            spotify_connected=spotify.is_authenticated(),
            spotify_configured=has_spotify_config(),
            lastfm_configured=has_lastfm_config(),
            default_date_from=default_range.start.isoformat(),
            default_date_to=default_range.end.isoformat(),
            today=default_range.end.isoformat(),
        )

    @app.get("/logout")
    def logout():
        session.pop("token_info", None)
        flash("Disconnected from Spotify.", "info")
        return redirect(url_for("index"))

    @app.get("/login")
    def login():
        if not has_spotify_config():
            flash("Add Spotify credentials to .env before connecting.", "error")
            return redirect(url_for("index"))
        spotify = spotify_destination()
        return redirect(spotify.get_authorize_url())

    @app.get("/callback")
    def callback():
        error = request.args.get("error")
        if error:
            message = f"Spotify authorization failed: {error}"
            if error in {"redirect_uri_mismatch", "invalid_request"}:
                message = (
                    f"Spotify redirect URI mismatch. Add this exact URI in your Spotify app settings "
                    f"and click Save: {spotify_redirect_uri()}"
                )
            flash(message, "error")
            return redirect(url_for("index"))

        code = request.args.get("code")
        if not code:
            flash("Missing authorization code from Spotify.", "error")
            return redirect(url_for("index"))

        spotify = spotify_destination()
        try:
            spotify.complete_auth(code)
        except Exception as exc:
            flash(f"Could not complete Spotify login: {exc}", "error")
            return redirect(url_for("index"))

        flash("Connected to Spotify.", "success")

        if PENDING_FORM_KEY in session:
            return redirect(url_for("create_playlist_resume"))
        return redirect(url_for("index"))

    def _run_create_playlist(params: dict):
        if not has_spotify_config():
            return _error_response("Add Spotify Client ID and Secret to .env first.")

        lastfm = LastFmClient(lastfm_api_key())
        spotify = spotify_destination()
        try:
            tracks, name, description, _display_name = prepare_playlist(
                lastfm,
                params["username"],
                source=params["source"],
                period=params["period"],
                limit=params["limit"],
                min_plays=params.get("min_plays"),
                playlist_name=params.get("name") or None,
                date_from=params.get("date_from"),
                date_to=params.get("date_to"),
            )
        except LastFmError as exc:
            return _error_response(str(exc))
        except RuntimeError as exc:
            return _error_response(str(exc))
        except Exception as exc:
            return _error_response(f"Something went wrong: {exc}")

        if should_chunk_playlist(len(tracks)):
            return _start_chunked_playlist(spotify, tracks, name, description)

        try:
            create_result = spotify.create_playlist(name, description, tracks)
        except SpotifyException as exc:
            return _error_response(_spotify_error_message(exc))
        except Exception as exc:
            return _error_response(f"Something went wrong: {exc}")

        result = BuildResult(
            url=create_result.url,
            tracks=tracks,
            playlist_name=name,
            lastfm_user=_display_name,
            create_result=create_result,
        )
        return _success_response(result, spotify.is_authenticated())

    @app.post("/create/chunk")
    def create_playlist_chunk():
        if not _wants_json():
            return redirect(url_for("index"))

        job = session.get(CHUNK_JOB_KEY)
        if not job:
            return jsonify({"success": False, "error": "Session expired. Please try again."}), 400

        payload = request.get_json(silent=True) or {}
        if payload.get("playlist_id") != job["playlist_id"]:
            return jsonify({"success": False, "error": "Session expired. Please try again."}), 400

        tracks = [_track_from_dict(item) for item in payload.get("tracks", [])]
        if not tracks:
            return jsonify({"success": False, "error": "No tracks in chunk."}), 400

        spotify = spotify_destination()
        try:
            uris, not_found = spotify.resolve_tracks(tracks)
            if uris:
                spotify.append_tracks(job["playlist_id"], uris)
        except SpotifyException as exc:
            return jsonify({"success": False, "error": _spotify_error_message(exc)}), 400
        except Exception as exc:
            return jsonify({"success": False, "error": f"Something went wrong: {exc}"}), 400

        job["matched"] += len(uris)
        job["not_found"].extend(
            {"artist": track.artist, "title": track.title} for track in not_found
        )
        session[CHUNK_JOB_KEY] = job

        processed = int(payload.get("offset", 0)) + len(tracks)
        done = processed >= job["total"]

        if done:
            if job["matched"] == 0:
                session.pop(CHUNK_JOB_KEY, None)
                return jsonify(
                    {"success": False, "error": "Could not match any tracks on Spotify."}
                ), 400

            session[LAST_RESULT_KEY] = {
                "url": job["playlist_url"],
                "playlist_name": job["playlist_name"],
                "matched": job["matched"],
                "total": job["total"],
                "not_found": job["not_found"],
            }
            session.pop(CHUNK_JOB_KEY, None)
            return jsonify(
                {
                    "success": True,
                    "done": True,
                    "redirect": url_for("show_result"),
                    "processed": processed,
                    "total": job["total"],
                }
            )

        return jsonify(
            {
                "success": True,
                "done": False,
                "processed": processed,
                "total": job["total"],
            }
        )

    @app.get("/result")
    def show_result():
        data = session.pop(LAST_RESULT_KEY, None)
        if not data:
            return redirect(url_for("index"))

        from types import SimpleNamespace

        result = SimpleNamespace(
            url=data["url"],
            playlist_name=data["playlist_name"],
            create_result=SimpleNamespace(
                matched=data["matched"],
                total=data["total"],
                not_found=[Track(**t) for t in data["not_found"]],
            ),
        )
        spotify = spotify_destination()
        return render_template(
            "result.html",
            result=result,
            spotify_connected=spotify.is_authenticated(),
        )

    @app.get("/create")
    def create_playlist_resume():
        if PENDING_FORM_KEY not in session:
            return redirect(url_for("index"))
        return render_template("generating.html")

    @app.post("/create/resume")
    def create_playlist_resume_post():
        pending = session.pop(PENDING_FORM_KEY, None)
        if not pending:
            flash("Session expired. Please try again.", "error")
            return redirect(url_for("index"))
        return _run_create_playlist(pending)

    @app.post("/preview")
    def preview():
        params = _parse_form(request.form)
        if params is None:
            return redirect(url_for("index"))

        username = params["username"]
        source = params["source"]
        period = params["period"]
        limit = params["limit"]
        min_plays = params["min_plays"]
        date_from = params["date_from"]
        date_to = params["date_to"]

        if not has_lastfm_config():
            tracks = DEMO_TRACKS[:limit]
            if min_plays is not None:
                tracks = [t for t in tracks if t.playcount and t.playcount >= min_plays]
            flash(
                "Demo preview — add LASTFM_API_KEY to .env to fetch real Last.fm data.",
                "info",
            )
            return render_template(
                "index.html",
                periods=TIME_PERIODS,
                spotify_connected=spotify_destination().is_authenticated(),
                spotify_configured=has_spotify_config(),
                lastfm_configured=False,
                default_date_from=default_custom_range().start.isoformat(),
                default_date_to=default_custom_range().end.isoformat(),
                today=default_custom_range().end.isoformat(),
                preview={
                    "username": username,
                    "count": len(tracks),
                    "tracks": tracks[:15],
                    "demo": True,
                },
                form=request.form,
            )

        lastfm = LastFmClient(lastfm_api_key())
        try:
            user = lastfm.verify_user(username)
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
            if not tracks:
                flash(
                    "No tracks matched your filters. Try a wider time range or lower min plays.",
                    "error",
                )
                return redirect(url_for("index"))
        except LastFmError as exc:
            flash(str(exc), "error")
            return redirect(url_for("index"))
        except RuntimeError as exc:
            flash(str(exc), "error")
            return redirect(url_for("index"))

        return render_template(
            "index.html",
            periods=TIME_PERIODS,
            spotify_connected=spotify_destination().is_authenticated(),
            spotify_configured=has_spotify_config(),
            lastfm_configured=has_lastfm_config(),
            default_date_from=default_custom_range().start.isoformat(),
            default_date_to=default_custom_range().end.isoformat(),
            today=default_custom_range().end.isoformat(),
            preview={
                "username": user.get("name", username),
                "count": len(tracks),
                "tracks": tracks[:15],
            },
            form=request.form,
        )

    @app.post("/create")
    def create_playlist():
        params = _parse_form(request.form)
        if params is None:
            return redirect(url_for("index"))

        username = params["username"]
        source = params["source"]
        period = params["period"]
        limit = params["limit"]
        min_plays = params["min_plays"]
        playlist_name = params["name"] or None
        date_from = params["date_from"]
        date_to = params["date_to"]

        spotify = spotify_destination()
        if not spotify.is_authenticated():
            if not has_spotify_config():
                flash("Add Spotify Client ID and Secret to .env, then click Connect Spotify.", "error")
                return redirect(url_for("index"))
            session[PENDING_FORM_KEY] = {
                "username": username,
                "source": source,
                "period": period,
                "limit": limit,
                "min_plays": min_plays,
                "name": playlist_name or "",
                "date_from": date_from or "",
                "date_to": date_to or "",
            }
            flash("Connect Spotify to create your playlist.", "info")
            return redirect(url_for("login"))

        return _run_create_playlist(
            {
                "username": username,
                "source": source,
                "period": period,
                "limit": limit,
                "min_plays": min_plays,
                "name": playlist_name or "",
                "date_from": date_from,
                "date_to": date_to,
            }
        )

    return app


def _start_chunked_playlist(spotify, tracks: list[Track], name: str, description: str):
    try:
        playlist_id, playlist_url = spotify.create_empty_playlist(name, description)
    except SpotifyException as exc:
        return _error_response(_spotify_error_message(exc))
    except Exception as exc:
        return _error_response(f"Something went wrong: {exc}")

    session[CHUNK_JOB_KEY] = {
        "playlist_id": playlist_id,
        "playlist_url": playlist_url,
        "playlist_name": name,
        "matched": 0,
        "not_found": [],
        "total": len(tracks),
    }

    if _wants_json():
        return jsonify(
            {
                "success": True,
                "chunked": True,
                "chunk_size": PLAYLIST_CHUNK_SIZE,
                "playlist_id": playlist_id,
                "total": len(tracks),
                "tracks": [_track_to_dict(track) for track in tracks],
            }
        )

    flash("Large playlist started — this UI path should use AJAX.", "info")
    return redirect(url_for("index"))


def _track_to_dict(track: Track) -> dict:
    return {
        "artist": track.artist,
        "title": track.title,
        "lastfm_url": track.lastfm_url,
        "playcount": track.playcount,
        "loved": track.loved,
    }


def _track_from_dict(data: dict) -> Track:
    return Track(
        artist=data["artist"],
        title=data["title"],
        lastfm_url=data.get("lastfm_url"),
        playcount=data.get("playcount"),
        loved=bool(data.get("loved")),
    )


def _wants_json() -> bool:
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _error_response(message: str):
    if _wants_json():
        return jsonify({"success": False, "error": message}), 400
    flash(message, "error")
    return redirect(url_for("index"))


def _serialize_result(result: BuildResult) -> dict:
    create_result = result.create_result
    return {
        "url": result.url,
        "playlist_name": result.playlist_name,
        "matched": create_result.matched if create_result else 0,
        "total": create_result.total if create_result else len(result.tracks),
        "not_found": [
            {"artist": track.artist, "title": track.title}
            for track in (create_result.not_found if create_result else [])
        ],
    }


def _success_response(result: BuildResult, spotify_connected: bool):
    session[LAST_RESULT_KEY] = _serialize_result(result)
    if _wants_json():
        return jsonify({"success": True, "redirect": url_for("show_result")})
    from types import SimpleNamespace

    return render_template(
        "result.html",
        result=result,
        spotify_connected=spotify_connected,
    )


def _parse_form(form) -> dict | None:
    from ..date_range import parse_date_range

    username = form.get("username", "").strip()
    source = form.get("source", "top")
    period = form.get("period", "overall")
    limit = _parse_int(form.get("limit"), 50)
    min_plays = _parse_optional_int(form.get("min_plays"))
    playlist_name = form.get("name", "").strip()
    date_from = form.get("date_from", "").strip() or None
    date_to = form.get("date_to", "").strip() or None

    if not username:
        flash("Enter a Last.fm username.", "error")
        return None

    if period == "custom":
        _, error = parse_date_range(date_from, date_to)
        if error:
            flash(error, "error")
            return None

    return {
        "username": username,
        "source": source,
        "period": period,
        "limit": limit,
        "min_plays": min_plays,
        "name": playlist_name,
        "date_from": date_from,
        "date_to": date_to,
    }


def _parse_int(value: str | None, default: int) -> int:
    try:
        parsed = int(value) if value else default
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, MAX_TRACK_LIMIT))


def _parse_optional_int(value: str | None) -> int | None:
    if not value or not value.strip():
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _spotify_error_message(exc: SpotifyException) -> str:
    if exc.http_status == 403:
        return (
            "Spotify denied access (403). New apps run in Development Mode — "
            "open your app in the Spotify Developer Dashboard, go to User Management, "
            "and add your Spotify account email. The app owner also needs Spotify Premium. "
            "Then click Disconnect and Connect Spotify again."
        )
    return f"Spotify error ({exc.http_status}): {exc.msg or 'Unknown error'}"


def main() -> None:
    app = create_app()
    debug = os.getenv("FLASK_DEBUG", "1") == "1"
    app.run(host="127.0.0.1", port=5000, debug=debug)


if __name__ == "__main__":
    main()
