import asyncio
import json
import os
import webbrowser
from pathlib import Path
from queue import Queue
from threading import Thread
from typing import Optional
from urllib.parse import urlencode, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler

import aiohttp

CONFIG_DIR = Path(os.environ.get("APPDATA", ".")) / "EpicChat"
TOKEN_FILE = CONFIG_DIR / "discord_token.json"

DISCORD_API = "https://discord.com/api"
REDIRECT_PORT = 8765
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"


class DiscordFriendInfo:
    def __init__(self, user_id: str, username: str, display_name: str, avatar_url: str = ""):
        self.user_id = user_id
        self.username = username
        self.display_name = display_name
        self.avatar_url = avatar_url
        self.platform_accounts: dict[str, str] = {}
        self.status = "unknown"
        self.activity = ""

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
            "status": self.status,
            "activity": self.activity,
            "platform_accounts": dict(self.platform_accounts),
        }


class DiscordClient:
    def __init__(self, event_queue: Queue, client_id: str, client_secret: str, bot_token: str = ""):
        self.event_queue = event_queue
        self.client_id = client_id
        self.client_secret = client_secret
        self.bot_token = bot_token
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.user_info: Optional[dict] = None
        self.connections: list[dict] = []
        self.discord_friends: dict[str, DiscordFriendInfo] = {}

    @property
    def logged_in(self) -> bool:
        return self.access_token is not None

    @property
    def logged_in_user(self) -> Optional[str]:
        if self.user_info:
            return self.user_info.get("global_name") or self.user_info.get("username")
        return None

    # ---- public API ----

    def start_auth(self):
        """Open browser for Discord OAuth2. Run this from tkinter thread."""
        self._start_local_server()
        params = urlencode({
            "client_id": self.client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": "identify connections guilds",
            "prompt": "consent",
        })
        webbrowser.open(f"{DISCORD_API}/oauth2/authorize?{params}")

    def logout(self):
        self.access_token = None
        self.refresh_token = None
        self.user_info = None
        self.connections = []
        self.discord_friends = {}
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()  # delete file

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

    # ---- internal ----

    def _start_local_server(self):
        """Start temporary HTTP server on a thread to catch OAuth redirect."""
        self.auth_code = None

        class Handler(BaseHTTPRequestHandler):
            def do_GET(inner_self):
                qs = parse_qs(inner_self.path.split("?", 1)[-1])
                self.auth_code = qs.get("code", [None])[0]
                inner_self.send_response(200)
                inner_self.send_header("Content-Type", "text/html")
                inner_self.end_headers()
                inner_self.wfile.write(
                    b"<html><body><h1>Authorized!</h1><p>Close this tab.</p></body></html>"
                )

            def log_message(inner_self, fmt, *args):
                pass

        self._server = HTTPServer(("localhost", REDIRECT_PORT), Handler)
        Thread(target=self._server.serve_forever, daemon=True).start()

    async def _wait_and_exchange(self):
        """Wait for the redirect, then exchange code for token."""
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
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            async with session.post(
                f"{DISCORD_API}/oauth2/token", data=data, headers=headers
            ) as resp:
                result = await resp.json()
                self.access_token = result.get("access_token")
                self.refresh_token = result.get("refresh_token")

            if self.access_token:
                TOKEN_FILE.write_text(
                    json.dumps({
                        "access_token": self.access_token,
                        "refresh_token": self.refresh_token,
                    })
                )
                await self._fetch_user_info()
                await self._fetch_connections()

    async def _fetch_user_info(self):
        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{DISCORD_API}/users/@me", headers=headers) as resp:
                self.user_info = await resp.json()

            async with session.get(
                f"{DISCORD_API}/users/@me/connections", headers=headers
            ) as resp:
                self.connections = await resp.json()

        avatar_hash = self.user_info.get("avatar", "")
        user_id = self.user_info.get("id", "")
        avatar_url = ""
        if avatar_hash:
            animated = avatar_hash.startswith("a_")
            ext = "gif" if animated else "png"
            avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{ext}"

        platform_map = {}
        for conn in self.connections:
            conn_type = conn.get("type", "").upper()
            conn_name = conn.get("name", "")
            if conn_type in ("STEAM", "XBOX", "PLAYSTATION", "NINTENDO"):
                platform_map[conn_type] = conn_name

        self.event_queue.put((
            "discord_ready",
            {
                "username": self.user_info.get("global_name") or self.user_info.get("username"),
                "user_id": user_id,
                "avatar_url": avatar_url,
                "connections": platform_map,
            },
        ))

    async def login_async(self):
        """Call from async context after start_auth."""
        await self._wait_and_exchange()

    def refresh_user_info_sync(self):
        """Refresh user info from tkinter thread."""
        if not self.access_token:
            return
        try:
            import threading
            result = {}

            async def _fetch():
                headers = {"Authorization": f"Bearer {self.access_token}"}
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{DISCORD_API}/users/@me", headers=headers) as resp:
                        result["user"] = await resp.json()
                    async with session.get(
                        f"{DISCORD_API}/users/@me/connections", headers=headers
                    ) as resp:
                        result["connections"] = await resp.json()

            loop = asyncio.new_event_loop()
            loop.run_until_complete(_fetch())
            loop.close()

            self.user_info = result.get("user", self.user_info)
            self.connections = result.get("connections", self.connections)
        except Exception:
            pass
