# Last.fm Playlist Maker

Create Spotify playlists from your Last.fm listening history. Enter a username, pick your filters, and the tool builds the playlist for you.

## Features

- **Username only** — no Last.fm login required to read public stats
- **Top tracks** with adjustable time range (7 days → all time, or pick your own dates)
- **Minimum play count** filter for top tracks
- **Loved tracks** from Last.fm
- **Combine** top + loved in one playlist
- **Spotify** playlist creation (Apple Music & YouTube Music planned)

## Setup

### 1. Install dependencies

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

### 2. Get API credentials

**Last.fm** — [Create an API account](https://www.last.fm/api/account/create) and copy your API key.

**Spotify** — [Create an app](https://developer.spotify.com/dashboard):

1. Add redirect URIs:
   - `http://127.0.0.1:5000/callback` (web app)
   - `http://127.0.0.1:8888/callback` (CLI, optional)
2. Copy Client ID and Client Secret

### 3. Configure environment

```bash
copy .env.example .env
```

Fill in your keys in `.env`.

## Web app

Start the local web UI:

```bash
python -m src.web.app
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000), enter a Last.fm username, adjust filters, preview tracks, connect Spotify, and create your playlist.

## Deploy (Vercel)

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/timothy-jan/lastfm-playlist-maker&env=LASTFM_API_KEY,SPOTIFY_CLIENT_ID,SPOTIFY_CLIENT_SECRET,FLASK_SECRET_KEY&envDescription=API%20keys%20for%20Last.fm%20and%20Spotify&project-name=lastfm-playlist-maker)

This app runs on [Vercel](https://vercel.com) as a Flask serverless function (`wsgi.py`).

1. Click **Deploy with Vercel** above (or import the [GitHub repo](https://github.com/timothy-jan/lastfm-playlist-maker) in the Vercel dashboard).
2. Set these environment variables:
   - `LASTFM_API_KEY`
   - `SPOTIFY_CLIENT_ID`
   - `SPOTIFY_CLIENT_SECRET`
   - `FLASK_SECRET_KEY` (any long random string)
3. After deploy, copy your production URL (e.g. `https://lastfm-playlist-maker.vercel.app`).
4. In the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard), add a redirect URI:
   - `https://YOUR-APP.vercel.app/callback`
5. Optionally set `SPOTIFY_REDIRECT_URI` in Vercel to that exact URL so preview deploys don't break OAuth.

**Note:** Large playlists can take a while to build. Vercel's free tier has a 60-second request limit — use fewer tracks or upgrade if you hit timeouts.

### Deploy from CLI

```bash
npm i -g vercel
vercel login
vercel --prod
```

## CLI usage

```bash
python -m src.cli YOUR_LASTFM_USERNAME
```

### Examples

```bash
# Top 50 tracks, all time
python -m src.cli yourusername

# Top tracks from the past month, at least 10 plays
python -m src.cli yourusername --period 1month --min-plays 10 --limit 100

# Loved tracks only
python -m src.cli yourusername --source loved

# Top + loved, past year, custom name
python -m src.cli yourusername --source both --period 12month --name "My 2025 Mix"
```

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `--source` | `top`, `loved`, or `both` | `top` |
| `--period` | `7day`, `1month`, `3month`, `6month`, `12month`, `overall`, `custom` | `overall` |
| `--from-date` | Custom range start (`YYYY-MM-DD`, with `--period custom`) | none |
| `--to-date` | Custom range end (`YYYY-MM-DD`, with `--period custom`) | none |
| `--min-plays` | Minimum play count (top tracks only) | none |
| `--limit` | Max tracks to fetch | `50` |
| `--name` | Custom playlist name | auto-generated |
| `--destination` | `spotify` (default), `apple`, `youtube` | `spotify` |

On first Spotify run, your browser opens for authorization. The web app stores auth in your session; the CLI caches credentials locally in `.cache`.

## How it works

1. Fetches tracks from the Last.fm API using the username you provide
2. Applies your filters (time period, min plays, source type)
3. Searches each track on Spotify by artist + title
4. Creates a new playlist on your Spotify account and adds matched tracks

Tracks that can't be matched on Spotify are listed in the terminal output.

## Roadmap

- [ ] Apple Music support
- [ ] YouTube Music support
- [x] Web UI
- [ ] Smarter track matching (album, duration, ISRC)
