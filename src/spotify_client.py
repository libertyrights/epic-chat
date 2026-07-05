import asyncio
import json
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from queue import Queue
from threading import Thread
from typing import Optional, NamedTuple
from urllib.parse import urlencode, parse_qs

import aiohttp

CONFIG_DIR = Path(__file__).parent.parent / "config"
TOKEN_FILE = CONFIG_DIR / "spotify_token.json"

SPOTIFY_API = "https://api.spotify.com/v1"
ACCOUNTS_API = "https://accounts.spotify.com"
REDIRECT_PORT = 8766
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"


class NowPlaying(NamedTuple):
    track: str
    artist: str
    album: str
    album_art: str
    progress_ms: int
    duration_ms: int
    is_playing: bool

    def display(self) -> str:
        return f"{self.track} — {self.artist}"

    def to_dict(self) -> dict:
        return {
            "track": self.track,
            "artist": self.artist,
            "album": self.album,
            "album_art": self.album_art,
            "progress_ms": self.progress_ms,
            "duration_ms": self.duration_ms,
            "is_playing": self.is_playing,
        }


class SpotifyClient:
    def __init__(self, event_queue: Queue, client_id: str, client_secret: str):
        self.event_queue = event_queue
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.current: Optional[NowPlaying] = None
        self._poll_task: Optional[asyncio.Task] = None

    @property
    def logged_in(self) -> bool:
        return self.access_token is not None

    def load_token(self) -> bool:
        if TOKEN_FILE.exists():
            try:
                data = json.loads(TOKEN_FILE.read_text())
                self.access_token = data.get("access_token")
                self.refresh_token = data.get("refresh_token")
                return True
            except Exception:
                return False
        return False

    def start_auth(self):
        self.auth_code = None
        class Handler(BaseHTTPRequestHandler):
            def do_GET(inner_self):
                qs = parse_qs(inner_self.path.split("?", 1)[-1])
                self.auth_code = qs.get("code", [None])[0]
                inner_self.send_response(200)
                inner_self.send_header("Content-Type", "text/html")
                inner_self.end_headers()
                inner_self.wfile.write(b"<html><body><h1>Spotify Authorized!</h1><p>Close this tab.</p></body></html>")
            def log_message(inner_self, fmt, *args):
                pass
        self._server = HTTPServer(("localhost", REDIRECT_PORT), Handler)
        Thread(target=self._server.serve_forever, daemon=True).start()
        params = urlencode({
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": "user-read-currently-playing user-read-playback-state",
        })
        webbrowser.open(f"{ACCOUNTS_API}/authorize?{params}")

    async def login_async(self):
        while self.auth_code is None:
            await asyncio.sleep(0.1)
        self._server.shutdown()
        async with aiohttp.ClientSession() as session:
            data = {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "authorization_code",
                "code": self.auth_code,
                "redirect_uri": REDIRECT_URI,
            }
            async with session.post(f"{ACCOUNTS_API}/api/token", data=data) as resp:
                result = await resp.json()
                self.access_token = result.get("access_token")
                self.refresh_token = result.get("refresh_token")
            if self.access_token:
                TOKEN_FILE.write_text(json.dumps({
                    "access_token": self.access_token,
                    "refresh_token": self.refresh_token,
                }))
                await self._fetch_current()
                self._poll_task = asyncio.ensure_future(self._poll_loop())

    async def _refresh(self):
        if not self.refresh_token:
            return
        async with aiohttp.ClientSession() as session:
            data = {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            }
            async with session.post(f"{ACCOUNTS_API}/api/token", data=data) as resp:
                result = await resp.json()
                self.access_token = result.get("access_token")
                TOKEN_FILE.write_text(json.dumps({
                    "access_token": self.access_token,
                    "refresh_token": self.refresh_token,
                }))

    async def _fetch_current(self):
        if not self.access_token:
            return
        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{SPOTIFY_API}/me/player/currently-playing", headers=headers) as resp:
                if resp.status == 401:
                    await self._refresh()
                    headers = {"Authorization": f"Bearer {self.access_token}"}
                    async with session.get(f"{SPOTIFY_API}/me/player/currently-playing", headers=headers) as resp2:
                        if resp2.status == 204:
                            self.current = None
                            return
                        data = await resp2.json()
                elif resp.status == 204:
                    self.current = None
                    self.event_queue.put(("spotify_update", None))
                    return
                else:
                    data = await resp.json()
            item = data.get("item")
            if not item:
                self.current = None
                self.event_queue.put(("spotify_update", None))
                return
            self.current = NowPlaying(
                track=item.get("name", ""),
                artist=", ".join(a.get("name", "") for a in item.get("artists", [])),
                album=item.get("album", {}).get("name", ""),
                album_art=item.get("album", {}).get("images", [{}])[0].get("url", "") if item.get("album", {}).get("images") else "",
                progress_ms=data.get("progress_ms", 0),
                duration_ms=item.get("duration_ms", 0),
                is_playing=data.get("is_playing", False),
            )
            self.event_queue.put(("spotify_update", self.current))

    async def _poll_loop(self):
        while True:
            await asyncio.sleep(15)
            await self._fetch_current()

    def logout(self):
        self.access_token = None
        self.refresh_token = None
        self.current = None
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()
