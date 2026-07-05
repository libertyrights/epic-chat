import asyncio
import json
import os
import re
import subprocess
import time
from pathlib import Path
from queue import Queue
from typing import Optional

import aiohttp

CONSOLE_MAC_PREFIXES = {
    "00:50:F2": "Microsoft (Xbox)",
    "00:1D:D8": "Microsoft (Xbox 360)",
    "58:38:79": "Sony (PS4/PS5)",
    "04:D6:AA": "Sony (PS5)",
    "00:26:5C": "Sony (PSP/Vita)",
    "DC:A6:32": "Nintendo (Switch)",
    "00:19:FD": "Nintendo (Wii U)",
    "00:09:BF": "Nintendo (Wii)",
    "A4:C0:E1": "Nintendo (Switch OLED)",
    "BC:24:6D": "Microsoft (Xbox One/Series)",
    "7C:ED:8D": "Microsoft (Xbox One)",
    "48:F8:E1": "Microsoft (Xbox Series X/S)",
}

CONFIG_DIR = Path(os.environ.get("APPDATA", ".")) / "EpicChat"
ZT_CONFIG_FILE = CONFIG_DIR / "zerotier_config.json"

ZT_AUTH_TOKEN_PATH_CANDIDATES = [
    Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData")) / "ZeroTier" / "One" / "authtoken.secret",
    Path("/var/lib/zerotier-one/authtoken.secret"),
    Path.home() / ".zeroTier" / "authtoken.secret",
]

ZT_API_BASE = "http://localhost:9993"


class ZeroTierClient:
    def __init__(self, event_queue: Queue):
        self.event_queue = event_queue
        self.auth_token: Optional[str] = None
        self.network_id: str = ""
        self.zt_ip: Optional[str] = None
        self._installed = False
        self._running = False

    @property
    def is_ready(self) -> bool:
        return self._running and self.zt_ip is not None

    def _find_auth_token(self) -> Optional[str]:
        for path in ZT_AUTH_TOKEN_PATH_CANDIDATES:
            if path.exists():
                try:
                    return path.read_text().strip()
                except Exception:
                    pass
        return None

    def check_installed(self) -> bool:
        try:
            r = subprocess.run(
                ["zerotier-one", "-v"],
                capture_output=True, text=True, timeout=5
            )
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        try:
            r = subprocess.run(
                ["zerotier-cli", "info"],
                capture_output=True, text=True, timeout=5
            )
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def load_config(self) -> bool:
        if ZT_CONFIG_FILE.exists():
            try:
                data = json.loads(ZT_CONFIG_FILE.read_text())
                self.network_id = data.get("network_id", "")
                return True
            except Exception:
                return False
        return False

    def save_config(self):
        ZT_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        ZT_CONFIG_FILE.write_text(json.dumps({"network_id": self.network_id}))

    # -- LAN Party features --

    async def get_members(self) -> list[dict]:
        if not self.auth_token or not self.network_id:
            return []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{ZT_API_BASE}/network/{self.network_id}/member",
                    headers={"X-ZT1-Auth": self.auth_token}
                ) as resp:
                    if resp.status != 200:
                        return []
                    members = await resp.json()
                    result = []
                    for mid, m in members.items():
                        if m.get("online", False):
                            addrs = m.get("addresses", [])
                            ips = [a for a in addrs if "." in a]
                            result.append({
                                "id": mid[:8],
                                "name": m.get("name") or m.get("description") or mid[:8],
                                "ips": ips,
                                "last_seen": m.get("lastSeen", 0),
                            })
                    return result
        except Exception:
            return []

    async def get_managed_routes(self) -> list[dict]:
        if not self.auth_token or not self.network_id:
            return []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{ZT_API_BASE}/network/{self.network_id}",
                    headers={"X-ZT1-Auth": self.auth_token}
                ) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    routes = data.get("config", {}).get("routes", [])
                    return [r for r in routes if r.get("target") != "0.0.0.0/0"]
        except Exception:
            return []

    def scan_local_consoles(self) -> list[dict]:
        found = []
        try:
            r = subprocess.run(
                ["arp", "-a"],
                capture_output=True, text=True, timeout=10
            )
            for line in r.stdout.splitlines():
                m = re.search(r"(\d+\.\d+\.\d+\.\d+)\s+([\da-fA-F:-]{17})", line)
                if m:
                    ip = m.group(1)
                    mac = m.group(2).upper()
                    for prefix, name in CONSOLE_MAC_PREFIXES.items():
                        if mac.startswith(prefix.upper()):
                            found.append({"ip": ip, "mac": mac, "name": name})
                            break
        except Exception:
            pass
        return found

    async def lan_party_summary(self) -> dict:
        members = await self.get_members()
        routes = await self.get_managed_routes()
        consoles = self.scan_local_consoles()
        return {
            "online_members": members,
            "managed_routes": routes,
            "local_consoles": consoles,
            "bridge_active": len(routes) > 0,
        }

    async def start(self):
        self.auth_token = self._find_auth_token()
        if not self.auth_token:
            self.event_queue.put(("zt_status", "ZeroTier not found — install from zerotier.com"))
            return

        self._installed = True
        for i in range(10):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{ZT_API_BASE}/status",
                        headers={"X-ZT1-Auth": self.auth_token}
                    ) as resp:
                        if resp.status == 200:
                            self._running = True
                            break
            except:
                pass
            await asyncio.sleep(1)

        if not self._running:
            self.event_queue.put(("zt_status", "ZeroTier not running — start the service"))
            return

        self.event_queue.put(("zt_status", "ZeroTier connected"))

        if self.network_id:
            await self.join_network(self.network_id)

        asyncio.ensure_future(self._poll_ip())

    async def join_network(self, network_id: str) -> bool:
        if not self._running or not self.auth_token:
            return False

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{ZT_API_BASE}/network/{network_id}",
                headers={"X-ZT1-Auth": self.auth_token}
            ) as resp:
                if resp.status in (200, 201):
                    self.network_id = network_id
                    self.save_config()
                    self.event_queue.put(("zt_status", f"Joined ZT network {network_id[:8]}..."))
                    await self._poll_ip()
                    return True
                self.event_queue.put(("zt_error", f"Failed to join ZT network: {resp.status}"))
                return False

    async def leave_network(self):
        if not self.network_id or not self.auth_token:
            return
        async with aiohttp.ClientSession() as session:
            await session.delete(
                f"{ZT_API_BASE}/network/{self.network_id}",
                headers={"X-ZT1-Auth": self.auth_token}
            )
        self.network_id = ""
        self.zt_ip = None
        self.save_config()
        self.event_queue.put(("zt_status", "Left ZT network"))

    async def _poll_ip(self):
        for i in range(15):
            await asyncio.sleep(2)
            ip = await self._get_zt_ip()
            if ip:
                self.zt_ip = ip
                self.event_queue.put(("zt_ip", ip))
                self.event_queue.put(("zt_status", f"ZT IP: {ip}"))
                return

    async def _get_zt_ip(self) -> Optional[str]:
        if not self.auth_token or not self.network_id:
            return None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{ZT_API_BASE}/network/{self.network_id}",
                    headers={"X-ZT1-Auth": self.auth_token}
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    for addr in data.get("assignedAddresses", []):
                        if "." in addr:
                            return addr.split("/")[0]
        except:
            pass
        return None
