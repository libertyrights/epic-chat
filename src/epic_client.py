import asyncio
import json
import os
from pathlib import Path
from queue import Queue
from threading import Thread
from typing import Optional

import rebootpy
from rebootpy import Client, DeviceAuth, ExchangeCode, Presence

CONFIG_DIR = Path(os.environ.get("APPDATA", ".")) / "EpicChat"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
DEVICE_AUTH_FILE = CONFIG_DIR / "device_auth.json"


class FriendInfo:
    def __init__(self, friend_id: str, display_name: str, presence: Presence = None):
        self.friend_id = friend_id
        self.display_name = display_name
        self.presence = presence
        self.platform_accounts: dict[str, str] = {}

    @property
    def status(self) -> str:
        if not self.presence:
            return "offline"
        return self.presence.status

    @property
    def activity(self) -> str:
        if not self.presence or not self.presence.raw_status:
            return ""
        return self.presence.raw_status

    @property
    def is_online(self) -> bool:
        return self.status in ("online", "away")

    def to_dict(self) -> dict:
        return {
            "friend_id": self.friend_id,
            "display_name": self.display_name,
            "status": self.status,
            "activity": self.activity,
            "platform_accounts": dict(self.platform_accounts),
        }


class EpicClient:
    def __init__(self, event_queue: Queue):
        self.event_queue = event_queue
        self.client: Optional[Client] = None
        self.friends: dict[str, FriendInfo] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[Thread] = None
        self._running = False

    @property
    def logged_in_user(self) -> Optional[str]:
        if self.client and self.client.user:
            return self.client.user.display_name
        return None

    # ---- public API called from tkinter thread ----

    def start(self):
        self._running = True
        self._thread = Thread(target=self._run_async, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)

    def send_message(self, friend_id: str, content: str):
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(
                self._do_send(friend_id, content), self._loop
            )

    async def _do_send(self, friend_id: str, content: str):
        friend = self.client.get_friend(friend_id)
        if friend:
            await friend.send(content)

    # ---- async internals ----

    def _run_async(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    async def _main(self):
        device_auth = self._load_device_auth()
        if device_auth:
            auth = DeviceAuth(
                account_id=device_auth["account_id"],
                device_id=device_auth["device_id"],
                secret=device_auth["secret"],
            )
        else:
            auth = self._prompt_exchange_code()
            if not auth:
                self._push_event("auth_failed", "No auth method available")
                return

        self.client = MyClient(auth, self)
        try:
            await self.client.start()
        except Exception as e:
            self._push_event("error", f"Connection failed: {e}")

    def _push_event(self, event_type: str, data=None):
        self.event_queue.put((event_type, data))

    def _load_device_auth(self) -> Optional[dict]:
        if DEVICE_AUTH_FILE.exists():
            try:
                return json.loads(DEVICE_AUTH_FILE.read_text())
            except Exception:
                return None
        return None

    def _save_device_auth(self, account_id: str, device_id: str, secret: str):
        DEVICE_AUTH_FILE.write_text(
            json.dumps({"account_id": account_id, "device_id": device_id, "secret": secret})
        )

    def _prompt_exchange_code(self):
        self._push_event(
            "auth_required",
            "Visit https://www.epicgames.com/id/exchange and paste the code.",
        )
        return None


class MyClient(Client):
    def __init__(self, auth, outer: EpicClient):
        super().__init__(auth)
        self.outer = outer

    async def event_ready(self):
        self.outer._push_event("auth_ready", self.user.display_name)

        if not self.outer._load_device_auth():
            da = await self.create_device_auth()
            self.outer._save_device_auth(
                da["account_id"], da["device_id"], da["secret"]
            )
            self.outer._push_event("status", "Device auth saved for future logins")

        await self._refresh_friends()

        asyncio.ensure_future(self._periodic_presence())

    async def _refresh_friends(self):
        friend_map = {}
        for friend_id, friend in self.friends.items():
            info = FriendInfo(
                friend_id=friend_id,
                display_name=friend.display_name,
                presence=friend.presence,
            )
            friend_map[friend_id] = info

        await self._fetch_linked_accounts(friend_map)
        self.outer.friends = friend_map
        self.outer._push_event("friends_updated", None)

    async def _fetch_linked_accounts(self, friend_map: dict[str, FriendInfo]):
        EXTERNAL_TYPES = {
            "steam": "steam",
            "psn": "psn",
            "xbl": "xbl",
            "nintendo": "nintendo",
        }
        for friend_id, info in friend_map.items():
            try:
                auths = await self.http.get_external_auths_by_id(friend_id)
                for ext in auths:
                    ext_type = ext.get("type", "").lower()
                    display = ext.get("external_auth_display_name") or ext.get("external_auth_id", "")
                    if ext_type in EXTERNAL_TYPES:
                        info.platform_accounts[ext_type.upper()] = display
            except Exception:
                pass

    async def _periodic_presence(self):
        while True:
            await asyncio.sleep(30)
            for friend_id, friend in self.friends.items():
                if friend_id in self.outer.friends:
                    info = self.outer.friends[friend_id]
                    if friend.presence and (
                        info.presence is None
                        or friend.presence.status != info.presence.status
                    ):
                        info.presence = friend.presence
            self.outer._push_event("friends_updated", None)

    async def event_friend_request(self, request):
        await request.accept()

    async def event_friend_presence(self, friend, before, after):
        fid = friend.id
        if fid in self.outer.friends:
            self.outer.friends[fid].presence = after
            old_status = before.status if before else None
            new_status = after.status if after else None
            self.outer._push_event("presence_changed", (fid, old_status, new_status))

    async def event_friend_message(self, message):
        self.outer._push_event(
            "message",
            {
                "friend_id": message.author.id,
                "display_name": message.author.display_name,
                "content": message.content,
            },
        )

    async def _shutdown(self):
        await self.close()
