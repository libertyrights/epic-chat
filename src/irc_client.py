import asyncio
import json
import os
import random
import re
import socket
import struct
from pathlib import Path
from queue import Queue
from typing import Optional

CONFIG_DIR = Path(os.environ.get("APPDATA", ".")) / "EpicChat"
IRC_CONFIG_FILE = CONFIG_DIR / "irc_config.json"

IRC_MSG_RE = re.compile(r"^(:(\S+) )?(\S+)( (?!:)(.+?))?( :(.+))?$")
CTCP_RE = re.compile(r"\x01(\S+)( .+?)?\x01")


def ip_to_int(ip: str) -> int:
    parts = [int(x) for x in ip.split(".")]
    return (parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]


def int_to_ip(val: int) -> str:
    return f"{(val >> 24) & 0xFF}.{(val >> 16) & 0xFF}.{(val >> 8) & 0xFF}.{val & 0xFF}"


def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


class IRCMessage:
    def __init__(self, prefix: str, command: str, params: list[str], trailing: str):
        self.prefix = prefix
        self.command = command
        self.params = params
        self.trailing = trailing
        self.nick = prefix.split("!")[0] if prefix and "!" in prefix else (prefix or "")

    @classmethod
    def parse(cls, raw: str) -> Optional["IRCMessage"]:
        raw = raw.strip()
        m = IRC_MSG_RE.match(raw)
        if not m:
            return None
        prefix = m.group(2) or ""
        command = m.group(3) or ""
        mid = m.group(5) or ""
        trailing = m.group(7) or ""
        params = mid.split() if mid else []
        return cls(prefix, command, params, trailing)

    @property
    def is_ctcp(self) -> bool:
        return bool(CTCP_RE.match(self.trailing))

    def parse_ctcp(self) -> Optional[tuple[str, list[str]]]:
        m = CTCP_RE.match(self.trailing)
        if not m:
            return None
        tag = m.group(1)
        rest = (m.group(2) or "").strip()
        args = rest.split() if rest else []
        return tag, args


class DCCTransfer:
    def __init__(self, filename: str, ip: str, port: int, size: int, sender_nick: str,
                 event_queue: Queue = None):
        self.filename = os.path.basename(filename)
        self.ip = ip
        self.port = port
        self.size = size
        self.sender_nick = sender_nick
        self.received = 0
        self.resume_pos = 0
        self._writer: Optional[asyncio.StreamWriter] = None
        self._event_queue = event_queue

    async def accept(self, output_dir: str) -> Optional[Path]:
        try:
            reader, writer = await asyncio.open_connection(self.ip, self.port)
            self._writer = writer
            output_path = Path(output_dir) / self.filename
            mode = "ab" if self.resume_pos > 0 else "wb"
            total = self.size - self.resume_pos
            with open(output_path, mode) as f:
                remaining = total
                while remaining > 0:
                    chunk = await reader.read(min(65536, remaining))
                    if not chunk:
                        break
                    f.write(chunk)
                    self.received += len(chunk)
                    remaining -= len(chunk)
                    if self._event_queue:
                        self._event_queue.put(("dcc_progress", {
                            "file": self.filename,
                            "received": self.received,
                            "size": total,
                            "direction": "download",
                        }))
            writer.close()
            return output_path if self.received >= total else None
        except Exception:
            return None
        finally:
            if self._writer and not self._writer.is_closing():
                self._writer.close()

    def request_resume(self, irc: "IRCClient"):
        if self.resume_pos > 0:
            irc._send(
                f"PRIVMSG {self.sender_nick} :\x01DCC RESUME \"{self.filename}\" "
                f"{self.port} {self.resume_pos}\x01"
            )


class IRCClient:
    def __init__(self, event_queue: Queue, nickname: str = ""):
        from identd import IdentServer

        self.event_queue = event_queue
        self.nickname = nickname or "EpicChatUser"
        self.username = "epicchat"
        self.realname = "Epic Chat"
        self.server = "irc.libera.chat"
        self.port = 6667
        self.password = ""
        self.nickserv_password = ""
        self.channels: list[str] = []

        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self._dcc_server: Optional[asyncio.AbstractServer] = None
        self._connected = False
        self._registered = False
        self._ping_task: Optional[asyncio.Task] = None
        self._dcc_tasks: list[asyncio.Task] = []
        self.dcc_override_ip: Optional[str] = None
        self._identd = IdentServer(ident=self.username)

    @property
    def is_connected(self) -> bool:
        return self._connected and self._registered

    def set_config(self, server: str, port: int, nickname: str,
                   password: str = "", nickserv_password: str = ""):
        self.server = server
        self.port = port
        self.nickname = nickname
        self.password = password
        self.nickserv_password = nickserv_password

    def load_config(self) -> bool:
        if IRC_CONFIG_FILE.exists():
            try:
                data = json.loads(IRC_CONFIG_FILE.read_text())
                self.server = data.get("server", self.server)
                self.port = data.get("port", self.port)
                self.nickname = data.get("nickname", self.nickname)
                self.password = data.get("password", "")
                self.nickserv_password = data.get("nickserv_password", "")
                self.channels = data.get("channels", [])
                return True
            except Exception:
                return False
        return False

    def save_config(self):
        IRC_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        IRC_CONFIG_FILE.write_text(json.dumps({
            "server": self.server, "port": self.port,
            "nickname": self.nickname, "password": self.password,
            "nickserv_password": self.nickserv_password,
            "channels": self.channels,
        }, indent=2))

    # -- connection --

    async def connect(self):
        try:
            self.reader, self.writer = await asyncio.open_connection(
                self.server, self.port)
            self._connected = True
            if self.password:
                self._send(f"PASS {self.password}")
            self._send(f"NICK {self.nickname}")
            self._send(f"USER {self.username} 0 * :{self.realname}")
            asyncio.ensure_future(self._read_loop())
            self._ping_task = asyncio.ensure_future(self._ping_loop())
            asyncio.ensure_future(self._identd.start())
            self.event_queue.put(("irc_status", "Connecting..."))
        except Exception as e:
            self._connected = False
            self.event_queue.put(("irc_error", f"IRC connection failed: {e}"))

    def _send(self, raw: str):
        if self.writer and not self.writer.is_closing():
            self.writer.write(f"{raw}\r\n".encode("utf-8"))

    async def _read_loop(self):
        while self._connected and self.reader:
            try:
                line = (await self.reader.readline()).decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                await self._handle_line(line)
            except Exception as e:
                self.event_queue.put(("irc_error", f"IRC connection lost: {e}"))
                self._connected = False
                self._registered = False
                self.event_queue.put(("irc_status", "Disconnected"))
                break

    async def _handle_line(self, line: str):
        msg = IRCMessage.parse(line)
        if not msg:
            return

        if msg.command == "PING":
            self._send(f"PONG :{msg.trailing}")
            return

        if msg.command == "001":
            self._registered = True
            self.event_queue.put(("irc_status", f"IRC: {self.nickname}@{self.server}"))
            self.event_queue.put(("irc_ready", self.nickname))
            if self.nickserv_password:
                self._send(f"PRIVMSG NickServ :IDENTIFY {self.nickserv_password}")
            for ch in self.channels:
                self.join(ch)

        elif msg.command == "NICK":
            if msg.nick == self.nickname and msg.trailing:
                self.nickname = msg.trailing

        elif msg.command == "PRIVMSG" and msg.is_ctcp:
            await self._handle_ctcp(msg)

        elif msg.command == "PRIVMSG" and not msg.is_ctcp:
            target = msg.params[0] if msg.params else ""
            is_channel = target.startswith("#")
            self.event_queue.put(("irc_message", {
                "from": msg.nick, "target": target,
                "content": msg.trailing, "is_channel": is_channel,
                "is_notice": False,
            }))

        elif msg.command == "NOTICE" and not msg.is_ctcp:
            target = msg.params[0] if msg.params else ""
            is_channel = target.startswith("#")
            self.event_queue.put(("irc_message", {
                "from": msg.nick, "target": target,
                "content": msg.trailing, "is_channel": is_channel,
                "is_notice": True,
            }))

        elif msg.command == "433":
            self.event_queue.put(("irc_error", "IRC nick in use, trying alt..."))
            self._send(f"NICK {self.nickname}_")

    # -- CTCP / DCC handling --

    async def _handle_ctcp(self, msg: IRCMessage):
        parsed = msg.parse_ctcp()
        if not parsed:
            return
        tag, args = parsed
        if tag == "DCC" and len(args) >= 4:
            await self._handle_dcc(msg.nick, args)
        elif tag == "VERSION":
            self._send(f"NOTICE {msg.nick} :\x01VERSION EpicChat 1.0 (Windows)\x01")
        elif tag == "PING":
            import time
            timestamp = args[0] if args else str(time.time())
            if msg.command == "PRIVMSG":
                self._send(f"NOTICE {msg.nick} :\x01PING {timestamp}\x01")
            else:
                try:
                    sent = float(timestamp)
                    latency = int((time.time() - sent) * 1000)
                    self.event_queue.put(("irc_ping_result", {"nick": msg.nick, "latency_ms": latency}))
                except ValueError:
                    pass

    async def _handle_dcc(self, nick: str, args: list[str]):
        subcmd = args[0].upper()
        if subcmd == "SEND" and len(args) >= 5:
            filename = args[1].strip('"')
            ip_int = int(args[2])
            port = int(args[3])
            size = int(args[4])
            ip = int_to_ip(ip_int)
            transfer = DCCTransfer(filename, ip, port, size, nick, self.event_queue)
            self.event_queue.put(("dcc_offer", transfer))

        elif subcmd == "RESUME" and len(args) >= 4:
            filename = args[1].strip('"')
            port = int(args[2])
            position = int(args[3])
            self._send(
                f"PRIVMSG {nick} :\x01DCC ACCEPT \"{filename}\" {port} {position}\x01"
            )

        elif subcmd == "ACCEPT" and len(args) >= 4:
            port = int(args[2])
            position = int(args[3])
            self.event_queue.put(("dcc_resume_accepted", {
                "port": port, "position": position,
            }))

        elif subcmd == "CHAT" and len(args) >= 4:
            ip_int = int(args[2])
            port = int(args[3])
            ip = int_to_ip(ip_int)
            self.event_queue.put(("dcc_chat_offer", {
                "nick": nick, "ip": ip, "port": port,
            }))

    # -- DCC SEND outbound --

    async def dcc_send_file(self, target_nick: str, filepath: Path) -> bool:
        if not filepath.exists():
            return False
        size = filepath.stat().st_size
        filename = filepath.name

        local_ip = self.dcc_override_ip or get_local_ip()
        ip_int = ip_to_int(local_ip)

        server = await asyncio.start_server(
            lambda r, w: self._dcc_handle_upload(r, w, filepath),
            host="0.0.0.0", port=0)
        port = server.sockets[0].getsockname()[1]

        self._send(f"PRIVMSG {target_nick} :\x01DCC SEND \"{filename}\" {ip_int} {port} {size}\x01")

        async def cleanup():
            await asyncio.sleep(120)
            server.close()

        asyncio.ensure_future(cleanup())
        return True

    async def _dcc_handle_upload(self, reader: asyncio.StreamReader,
                                 writer: asyncio.StreamWriter, filepath: Path):
        size = filepath.stat().st_size
        sent = 0
        with open(filepath, "rb") as f:
            while chunk := f.read(65536):
                writer.write(chunk)
                await writer.drain()
                sent += len(chunk)
                self.event_queue.put(("dcc_progress", {
                    "file": filepath.name,
                    "sent": sent,
                    "size": size,
                    "direction": "upload",
                }))
        writer.close()
        self.event_queue.put(("dcc_sent", str(filepath)))

    # -- DCC CHAT --

    def ping_user(self, target_nick: str):
        import time
        ts = time.time()
        self._send(f"PRIVMSG {target_nick} :\x01PING {ts}\x01")

    def dcc_chat_offer(self, target_nick: str):
        local_ip = self.dcc_override_ip or get_local_ip()
        ip_int = ip_to_int(local_ip)
        port = random.randint(40000, 60000)
        self._send(f"PRIVMSG {target_nick} :\x01DCC CHAT chat {ip_int} {port}\x01")

    # -- basic IRC commands --

    def send_privmsg(self, target: str, message: str):
        for line in message.split("\n"):
            if line:
                self._send(f"PRIVMSG {target} :{line[:400]}")

    def send_notice(self, target: str, message: str):
        for line in message.split("\n"):
            if line:
                self._send(f"NOTICE {target} :{line[:400]}")

    def join(self, channel: str):
        if not channel.startswith("#"):
            channel = "#" + channel
        self._send(f"JOIN {channel}")
        if channel not in self.channels:
            self.channels.append(channel)
            self.save_config()

    def part(self, channel: str):
        if not channel.startswith("#"):
            channel = "#" + channel
        self._send(f"PART {channel}")
        self.channels = [c for c in self.channels if c.lower() != channel.lower()]
        self.save_config()

    # -- lifecycle --

    async def _ping_loop(self):
        while self._connected:
            await asyncio.sleep(60)
            if self._connected:
                self._send("PING :keepalive")

    async def disconnect(self):
        self._connected = False
        if self._ping_task:
            self._ping_task.cancel()
        for t in self._dcc_tasks:
            t.cancel()
        if self.writer and not self.writer.is_closing():
            self._send("QUIT :Goodbye")
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except Exception:
                pass
