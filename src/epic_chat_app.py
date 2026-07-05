import tkinter as tk
from tkinter import ttk, messagebox
from queue import Queue
from threading import Thread
from typing import Optional

from epic_client import EpicClient, FriendInfo
from discord_client import DiscordClient, DiscordFriendInfo
from irc_client import IRCClient
from zerotier_client import ZeroTierClient
from spotify_client import SpotifyClient, NowPlaying


PLATFORM_COLORS = {
    "EPIC": "#2A2A2A",
    "STEAM": "#1B2838",
    "PSN": "#003087",
    "XBL": "#107C10",
    "NINTENDO": "#E60012",
    "DISCORD": "#5865F2",
}

PLATFORM_BADGES = {
    "STEAM": "Steam",
    "PSN": "PS",
    "XBL": "Xbox",
    "NINTENDO": "Switch",
    "DISCORD": "DC",
}


class PropertiesDialog(tk.Toplevel):
    def __init__(self, parent, friend: FriendInfo, title="Friend Properties"):
        super().__init__(parent)
        self.title(title)
        self.geometry("380x300")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        frame = ttk.Frame(self, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text=friend.display_name, font=("Segoe UI", 14, "bold")).pack(
            anchor=tk.W
        )
        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        info = ttk.Frame(frame)
        info.pack(fill=tk.X, pady=4)
        ttk.Label(info, text="Epic ID:", width=12, anchor=tk.W).grid(row=0, column=0, sticky=tk.W)
        ttk.Label(info, text=friend.friend_id, wraplength=240).grid(
            row=0, column=1, sticky=tk.W
        )

        status_text = "Online" if friend.is_online else "Offline"
        if friend.activity:
            status_text += f"  —  {friend.activity}"
        ttk.Label(info, text="Status:", width=12, anchor=tk.W).grid(row=1, column=0, sticky=tk.W, pady=2)
        ttk.Label(info, text=status_text).grid(row=1, column=1, sticky=tk.W, pady=2)

        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        ttk.Label(frame, text="Linked Accounts", font=("Segoe UI", 11, "bold")).pack(anchor=tk.W)

        if friend.platform_accounts:
            for platform, account_name in sorted(friend.platform_accounts.items()):
                row = ttk.Frame(frame)
                row.pack(fill=tk.X, pady=2)
                badge = PLATFORM_BADGES.get(platform, platform)
                color = PLATFORM_COLORS.get(platform, "#333")
                ttk.Label(row, text=f"[{badge}]", background=color, foreground="white",
                          font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(0, 6))
                ttk.Label(row, text=account_name).pack(side=tk.LEFT)
        else:
            ttk.Label(frame, text="  No linked accounts").pack(anchor=tk.W, pady=2)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(btn_frame, text="Close", command=self.destroy).pack(side=tk.RIGHT)

    @classmethod
    def for_discord(cls, parent, friend: DiscordFriendInfo):
        dlg = cls.__new__(cls)
        dlg.__init__(parent, FriendInfo(friend.user_id, friend.display_name), title="Discord Friend Properties")
        return dlg


class ChatWindow(tk.Toplevel):
    def __init__(self, parent, friend: FriendInfo, epic_client: EpicClient):
        super().__init__(parent)
        self.friend = friend
        self.epic_client = epic_client
        self.title(f"Chat with {friend.display_name}")
        self.geometry("450x500")
        self.transient(parent)

        frame = ttk.Frame(self, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        self.msg_area = tk.Text(frame, wrap=tk.WORD, state=tk.DISABLED, height=18)
        self.msg_area.pack(fill=tk.BOTH, expand=True)

        entry_frame = ttk.Frame(frame)
        entry_frame.pack(fill=tk.X, pady=(8, 0))

        self.entry = ttk.Entry(entry_frame)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.entry.bind("<Return>", lambda e: self.send_message())

        ttk.Button(entry_frame, text="Send", command=self.send_message).pack(side=tk.RIGHT, padx=(6, 0))

    def send_message(self):
        content = self.entry.get().strip()
        if not content:
            return
        self.epic_client.send_message(self.friend.friend_id, content)
        self._show_message("You", content, "#666")
        self.entry.delete(0, tk.END)

    def receive_message(self, sender_name: str, content: str):
        self._show_message(sender_name, content, "#2A6B2A")

    def _show_message(self, who: str, content: str, color: str):
        self.msg_area.config(state=tk.NORMAL)
        self.msg_area.insert(tk.END, f"{who}: ", f"bold")
        self.msg_area.insert(tk.END, f"{content}\n")
        self.msg_area.see(tk.END)
        self.msg_area.config(state=tk.DISABLED)


class EpicChatApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Epic Chat")
        self.geometry("600*700")
        self.minsize(500, 500)

        self.epic_client: Optional[EpicClient] = None
        self.discord_client: Optional[DiscordClient] = None
        self.irc_client: Optional[IRCClient] = None
        self.zt_client: Optional[ZeroTierClient] = None
        self.spotify_client: Optional[SpotifyClient] = None
        self.chat_windows: dict[str, ChatWindow] = {}
        self.pending_auth_code: Optional[str] = None
        self.event_queue: Queue = Queue()

        self._build_ui()
        self._setup_menus()
        self._poll_events()

    def _build_ui(self):
        self.configure(bg="#1E1E1E")

        main_frame = ttk.Frame(self, padding=8)
        main_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(main_frame, bg="#1E1E1E", highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.scrollable = ttk.Frame(self.canvas)

        self.scrollable.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.create_window((0, 0), window=self.scrollable, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._build_epic_section()
        self._build_platform_section("STEAM")
        self._build_platform_section("PSN")
        self._build_platform_section("XBL")
        self._build_platform_section("NINTENDO")
        self._build_discord_section()
        self._build_lan_party_section()

        self.status_bar = ttk.Frame(self)
        self.status_bar.pack(fill=tk.X, padx=8, pady=(0, 8))
        self.status_label = ttk.Label(
            self.status_bar, text="Not connected", foreground="gray"
        )
        self.status_label.pack(side=tk.LEFT)
        self.irc_btn = ttk.Button(
            self.status_bar, text="Chat Offline",
            command=self._prompt_irc_setup
        )
        self.irc_btn.pack(side=tk.RIGHT, padx=4)
        self.discord_btn = ttk.Button(
            self.status_bar, text="Discord", command=self._prompt_discord_login
        )
        self.discord_btn.pack(side=tk.RIGHT, padx=4)
        self.auth_btn = ttk.Button(
            self.status_bar, text="Epic", command=self._prompt_login
        )
        self.auth_btn.pack(side=tk.RIGHT, padx=4)

    def _build_epic_section(self):
        self._add_section_header("EPIC", "Epic Friends")
        self.epic_frame = ttk.Frame(self.scrollable)
        self.epic_frame.pack(fill=tk.X, padx=4, pady=2)
        ttk.Label(self.epic_frame, text="Log in to see your friends.").pack(padx=8, pady=4)

    def _build_platform_section(self, platform: str):
        label = {"STEAM": "Steam", "PSN": "PlayStation", "XBL": "Xbox", "NINTENDO": "Nintendo"}[platform]
        self._add_section_header(platform, label)
        frame_name = f"{platform.lower()}_frame"
        frame = ttk.Frame(self.scrollable)
        frame.pack(fill=tk.X, padx=4, pady=2)
        setattr(self, frame_name, frame)
        ttk.Label(frame, text="Friends from Epic who also play on this platform.").pack(
            padx=8, pady=4
        )

    def _build_discord_section(self):
        self._add_section_header("DISCORD", "Discord")
        self.discord_frame = ttk.Frame(self.scrollable)
        self.discord_frame.pack(fill=tk.X, padx=4, pady=2)
        self.discord_info_label = ttk.Label(
            self.discord_frame,
            text='Click "Discord" in the status bar.',
            wraplength=400,
        )
        self.discord_info_label.pack(padx=8, pady=4)

    def _build_lan_party_section(self):
        self._add_section_header("EPIC", "LAN Party")
        self.lan_frame = ttk.Frame(self.scrollable)
        self.lan_frame.pack(fill=tk.X, padx=4, pady=2)
        ttk.Label(self.lan_frame, text="Install ZeroTier (zerotier.com) and click ZT in the status bar.",
                  wraplength=400).pack(padx=8, pady=4)

    def _add_section_header(self, platform: str, label: str):
        color = PLATFORM_COLORS.get(platform, "#333")
        header = tk.Frame(self.scrollable, bg=color, height=28)
        header.pack(fill=tk.X, padx=4, pady=(12, 0))
        lbl = tk.Label(
            header,
            text=f"  {label}",
            fg="white",
            bg=color,
            font=("Segoe UI", 11, "bold"),
            anchor=tk.W,
        )
        lbl.pack(fill=tk.BOTH, expand=True)

    def _setup_menus(self):
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="Properties", command=self._show_properties)
        self.context_menu.add_command(label="Send Message", command=self._open_chat)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Ping (CTCP)", command=self._ping_friend)
        self.context_menu.add_command(label="Send File...", command=self._send_file)
        self._context_friend: Optional[FriendInfo] = None
        self._context_is_irc: bool = False

    def _poll_events(self):
        try:
            while True:
                event_type, data = self.event_queue.get_nowait()
                self._handle_event(event_type, data)
        except:
            pass
        self.after(100, self._poll_events)

    def _handle_event(self, event_type: str, data):
        if event_type == "auth_required":
            self._show_auth_dialog(data)
        elif event_type == "auth_failed":
            messagebox.showerror("Auth Failed", str(data))
        elif event_type == "auth_ready":
            self.status_label.config(text=f"Connected as: {data}", foreground="lightgreen")
            self.auth_btn.config(text="Reconnect")
        elif event_type == "status":
            self.status_label.config(text=str(data), foreground="gray")
        elif event_type == "friends_updated":
            self._update_friends_list()
        elif event_type == "presence_changed":
            self._update_friends_list()
        elif event_type == "error":
            messagebox.showerror("Error", str(data))
        elif event_type == "message":
            self._handle_incoming_message(data)
        elif event_type == "discord_ready":
            self._handle_discord_ready(data)
        elif event_type == "discord_connections":
            pass
        elif event_type == "irc_status":
            self.status_label.config(text=str(data), foreground="lightblue")
            self.irc_btn.config(text="Chat Online" if "Connected" in str(data) else "Chat Offline")
        elif event_type == "irc_ready":
            self.status_label.config(text=f"IRC: {data} | Epic: {self.epic_client.logged_in_user or 'N/A'}")
        elif event_type == "irc_error":
            self.status_label.config(text=str(data), foreground="orange")
        elif event_type == "irc_message":
            self._handle_irc_message(data)
        elif event_type == "dcc_offer":
            self._handle_dcc_offer(data)
        elif event_type == "dcc_chat_offer":
            self.status_label.config(text=f"DCC chat offered by {data['nick']}", foreground="yellow")
        elif event_type == "irc_ping_result":
            self.status_label.config(
                text=f"Ping to {data['nick']}: {data['latency_ms']}ms",
                foreground="cyan")
        elif event_type == "spotify_update":
            if data:
                self.status_label.config(
                    text=f"🎵 {data.display()}",
                    foreground="lightgreen")
                self.spotify_btn.config(text="Now Playing")
            else:
                self.spotify_btn.config(text="Spotify")
        elif event_type == "zt_status":
            self.status_label.config(text=str(data), foreground="cyan")
            self.zt_btn.config(text="ZT On" if "IP" in str(data) or "Joined" in str(data) else "ZT Off")
        elif event_type == "zt_ip":
            if self.irc_client:
                self.irc_client.dcc_override_ip = data
            self.status_label.config(text=f"ZT IP: {data}", foreground="cyan")
            self._update_lan_party()
        elif event_type == "zt_error":
            self.status_label.config(text=str(data), foreground="orange")

    def _show_auth_dialog(self, message: str):
        dlg = tk.Toplevel(self)
        dlg.title("Epic Login")
        dlg.geometry("400x150")
        dlg.transient(self)
        dlg.grab_set()
        ttk.Label(dlg, text=message, wraplength=380).pack(padx=15, pady=(15, 8))
        ttk.Label(dlg, text="Exchange Code:").pack()
        code_var = tk.StringVar()
        entry = ttk.Entry(dlg, textvariable=code_var, width=40)
        entry.pack(pady=4)
        def submit():
            code = code_var.get().strip()
            if code:
                self.pending_auth_code = code
                dlg.destroy()
                self._finish_auth(code)
        ttk.Button(dlg, text="Submit", command=submit).pack(pady=6)

    def _finish_auth(self, code: str):
        if self.epic_client and self.epic_client._loop and not self.epic_client._loop.is_closed():
            from rebootpy import ExchangeCode
            asyncio.run_coroutine_threadsafe(
                self._restart_with_code(code), self.epic_client._loop
            )

    async def _restart_with_code(self, code: str):
        if self.epic_client and self.epic_client.client:
            await self.epic_client.client.close()

    def _prompt_login(self):
        if not self.epic_client:
            self.epic_client = EpicClient(self.event_queue)
            self.epic_client.start()
        else:
            self.pending_auth_code = None
            self.epic_client.stop()
            self.epic_client = EpicClient(self.event_queue)
            self.epic_client.start()

    def _prompt_discord_login(self):
        if not self.discord_client:
            messagebox.showinfo(
                "Discord",
                "You need a Discord App Client ID.\n"
                "Create one at https://discord.com/developers/applications\n"
                "Then add it to config.json.",
            )
        else:
            self.discord_client.start_auth()
            Thread(target=self._run_discord_auth, daemon=True).start()

    def _run_discord_auth(self):
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.discord_client.login_async())
        loop.close()

    def _handle_discord_ready(self, data: dict):
        self.status_label.config(
            text=f"Epic: {self.epic_client.logged_in_user or 'N/A'} | Discord: {data['username']}",
            foreground="lightgreen",
        )
        self._update_discord_section(data)

    def _update_discord_section(self, data: dict):
        for widget in self.discord_frame.winfo_children():
            widget.destroy()

        header = ttk.Frame(self.discord_frame)
        header.pack(fill=tk.X, pady=4)
        ttk.Label(
            header,
            text=f"Logged in as: {data['username']}",
            font=("Segoe UI", 10, "bold"),
        ).pack(side=tk.LEFT, padx=8)

        conns = data.get("connections", {})
        if conns:
            ttk.Separator(self.discord_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=4)
            ttk.Label(
                self.discord_frame, text="Linked Accounts via Discord:", font=("Segoe UI", 9, "bold")
            ).pack(anchor=tk.W, padx=8)
            for plat, name in conns.items():
                row = ttk.Frame(self.discord_frame)
                row.pack(fill=tk.X, padx=16, pady=1)
                ttk.Label(row, text=f"  {plat}: {name}").pack(anchor=tk.W)

        ttk.Label(
            self.discord_frame,
            text="\n  Note: Discord DM/group chat requires a Bot token\n"
            "  and only works between app users (not your full Discord DMs).",
            foreground="gray",
            wraplength=450,
        ).pack(padx=8, pady=8)

    # -- IRC --

    def _prompt_irc_setup(self):
        if self.irc_client and self.irc_client.is_connected:
            asyncio.run_coroutine_threadsafe(
                self.irc_client.disconnect(), self.epic_client._loop
            )
            return

        dlg = tk.Toplevel(self)
        dlg.title("Chat Setup")
        dlg.geometry("420x300")
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)

        frame = ttk.Frame(dlg, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Chat Setup", font=("Segoe UI", 12, "bold")).pack(
            anchor=tk.W
        )
        ttk.Label(
            frame,
            text="This connects you to the chat network so you can message\n"
            "friends across any platform.\n"
            "Your IP is visible to anyone you send files to (DCC).",
            foreground="gray",
            wraplength=380,
        ).pack(anchor=tk.W, pady=6)

        ttk.Label(frame, text="Nickname:").pack(anchor=tk.W, pady=(8, 0))
        nick_var = tk.StringVar(value=self.epic_client.logged_in_user or "Gamer")
        ttk.Entry(frame, textvariable=nick_var, width=30).pack(fill=tk.X)

        ttk.Label(frame, text="Email (for nick registration):").pack(anchor=tk.W, pady=(8, 0))
        email_var = tk.StringVar()
        ttk.Entry(frame, textvariable=email_var, width=30).pack(fill=tk.X)

        ttk.Label(
            frame,
            text="A random password will be generated. Your nick will be\n"
            "registered automatically. Check your email to verify.",
            foreground="gray",
            wraplength=380,
        ).pack(anchor=tk.W, pady=6)

        def do_connect():
            nick = nick_var.get().strip() or "Gamer"
            email = email_var.get().strip()
            if not email:
                messagebox.showwarning("Email Required", "Email is needed to register your chat nickname.")
                return
            from irc_client import IRCClient
            self.irc_client = IRCClient(self.event_queue, nickname=nick)
            import secrets
            pw = secrets.token_hex(12)
            self.irc_client.nickserv_password = pw
            self.irc_client.nickserv_email = email
            self.irc_client.save_config()
            dlg.destroy()
            self._connect_irc()

        ttk.Button(frame, text="Connect", command=do_connect).pack(pady=(10, 0))
        ttk.Button(frame, text="Advanced (custom server)", command=lambda: [
            dlg.destroy(), self._irc_advanced_settings()
        ]).pack(pady=4)

    def _irc_advanced_settings(self):
        dlg = tk.Toplevel(self)
        dlg.title("IRC Settings")
        dlg.geometry("400x250")
        dlg.transient(self)
        dlg.grab_set()

        frame = ttk.Frame(dlg, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)

        irc = self.irc_client or IRCClient(self.event_queue)

        ttk.Label(frame, text="Server:").pack(anchor=tk.W)
        server_var = tk.StringVar(value=irc.server)
        ttk.Entry(frame, textvariable=server_var).pack(fill=tk.X)

        ttk.Label(frame, text="Port:").pack(anchor=tk.W, pady=(6, 0))
        port_var = tk.StringVar(value=str(irc.port))
        ttk.Entry(frame, textvariable=port_var).pack(fill=tk.X)

        ttk.Label(frame, text="Nickname:").pack(anchor=tk.W, pady=(6, 0))
        nick_var = tk.StringVar(value=irc.nickname)
        ttk.Entry(frame, textvariable=nick_var).pack(fill=tk.X)

        ttk.Label(frame, text="NickServ Password:").pack(anchor=tk.W, pady=(6, 0))
        pw_var = tk.StringVar(value=irc.nickserv_password)
        ttk.Entry(frame, textvariable=pw_var, show="*").pack(fill=tk.X)

        def save_and_connect():
            irc.set_config(server_var.get(), int(port_var.get()), nick_var.get(), nickserv_password=pw_var.get())
            irc.save_config()
            self.irc_client = irc
            dlg.destroy()
            self._connect_irc()

        ttk.Button(frame, text="Save & Connect", command=save_and_connect).pack(pady=(12, 0))

    def _connect_irc(self):
        if not self.irc_client or not self.epic_client:
            return
        import asyncio
        asyncio.run_coroutine_threadsafe(self._do_irc_connect(), self.epic_client._loop)

    async def _do_irc_connect(self):
        await self.irc_client.connect()
        if self.irc_client.nickserv_password:
            await asyncio.sleep(2)
            self.irc_client._send(
                f"PRIVMSG NickServ :REGISTER {self.irc_client.nickserv_password} "
                f"{getattr(self.irc_client, 'nickserv_email', '')}"
            )
            self.event_queue.put(
                ("irc_status", "Nick registered! Check email to verify.")
            )

    def _handle_irc_message(self, data: dict):
        sender = data["from"]
        content = data["content"]
        if data["is_channel"]:
            return
        cid = f"irc:{sender}"
        if cid in self.chat_windows:
            self.chat_windows[cid].receive_message(sender, content)

    def _handle_dcc_offer(self, transfer):
        resp = messagebox.askyesno(
            "Incoming File",
            f"{transfer.sender_nick} wants to send you:\n"
            f"{transfer.filename} ({transfer.size} bytes)\n\n"
            "⚠ Your IP will be visible to them during transfer.\n"
            "Accept?",
        )
        if not resp:
            return
        from tkinter import filedialog
        folder = filedialog.askdirectory(title="Save to...")
        if not folder:
            return
        import asyncio
        asyncio.run_coroutine_threadsafe(
            self._do_accept_dcc(transfer, folder), self.epic_client._loop
        )

    async def _do_accept_dcc(self, transfer, folder: str):
        path = await transfer.accept(folder)
        if path:
            self.event_queue.put(("irc_status", f"Received: {path.name}"))
        else:
            self.event_queue.put(("irc_error", "File transfer failed"))

    # -- ZeroTier --

    def _prompt_zt_setup(self):
        if self.zt_client and self.zt_client.is_ready:
            asyncio.run_coroutine_threadsafe(
                self.zt_client.leave_network(), self.epic_client._loop
            )
            return

        dlg = tk.Toplevel(self)
        dlg.title("ZeroTier LAN Party")
        dlg.geometry("420x280")
        dlg.transient(self)
        dlg.grab_set()

        frame = ttk.Frame(dlg, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="ZeroTier Setup", font=("Segoe UI", 12, "bold")).pack(anchor=tk.W)
        ttk.Label(frame, text=
            "ZeroTier creates a virtual LAN over the internet.\n"
            "Install from zerotier.com and create a network at my.zerotier.com.",
            wraplength=380, foreground="gray").pack(anchor=tk.W, pady=6)

        ttk.Label(frame, text="Network ID (16 chars):").pack(anchor=tk.W, pady=(8, 0))
        net_var = tk.StringVar()
        ttk.Entry(frame, textvariable=net_var, width=30).pack(fill=tk.X)

        status_lbl = ttk.Label(frame, text="", foreground="cyan")
        status_lbl.pack(anchor=tk.W, pady=4)

        def do_join():
            nid = net_var.get().strip()
            if len(nid) != 16:
                status_lbl.config(text="Network ID must be 16 characters", foreground="red")
                return
            self.zt_client = ZeroTierClient(self.event_queue)
            asyncio.run_coroutine_threadsafe(
                self._do_zt_join(nid), self.epic_client._loop
            )
            dlg.destroy()

        ttk.Button(frame, text="Join Network", command=do_join).pack(pady=8)
        ttk.Label(frame, text=
            "Tip: On Android, enable 'Route all traffic' + 'Allow LAN access'\n"
            "in ZT app settings. Console → phone hotspot → ZT works on some devices.",
            foreground="gray", wraplength=380).pack(anchor=tk.W)

    async def _do_zt_join(self, network_id: str):
        self.zt_client = ZeroTierClient(self.event_queue)
        await self.zt_client.start()
        if self.zt_client.is_ready:
            await self.zt_client.join_network(network_id)
            await self._update_lan_party()

    async def _update_lan_party(self):
        if not self.zt_client or not self.zt_client.is_ready:
            return
        summary = await self.zt_client.lan_party_summary()
        for widget in self.lan_frame.winfo_children():
            widget.destroy()

        members = summary.get("online_members", [])
        routes = summary.get("managed_routes", [])
        consoles = summary.get("local_consoles", [])

        if members:
            ttk.Label(self.lan_frame, text=f"Online ({len(members)}):",
                      font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, padx=8, pady=2)
            for m in members:
                ips = ", ".join(m["ips"]) if m["ips"] else "no IP"
                ttk.Label(self.lan_frame, text=f"  {m['name']}  ({ips})",
                          foreground="cyan").pack(anchor=tk.W, padx=16)

        if consoles:
            ttk.Separator(self.lan_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=4)
            ttk.Label(self.lan_frame, text="Local Consoles Detected:",
                      font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, padx=8, pady=2)
            for c in consoles:
                ttk.Label(self.lan_frame, text=f"  {c['name']}  ({c['ip']})",
                          foreground="white").pack(anchor=tk.W, padx=16)

        if routes and not consoles:
            ttk.Label(self.lan_frame, text="ZT bridge detected — remote devices can reach your LAN.",
                      foreground="gray", wraplength=400).pack(padx=8, pady=4)
        elif not members and not consoles:
            ttk.Label(self.lan_frame, text="No devices found. Make sure others are on the same ZT network.",
                      foreground="gray", wraplength=400).pack(padx=8, pady=4)

    # -- Spotify --

    def _prompt_spotify_login(self):
        if not self.spotify_client:
            messagebox.showinfo("Spotify",
                "Add your Spotify Client ID and Secret to config.json.\n"
                "Get them at https://developer.spotify.com/dashboard")
            return
        if self.spotify_client.logged_in:
            self.spotify_client.logout()
            self.spotify_btn.config(text="Spotify")
            self.status_label.config(text="Spotify disconnected")
            return
        self.spotify_client.start_auth()
        Thread(target=self._run_spotify_auth, daemon=True).start()

    def _run_spotify_auth(self):
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.spotify_client.login_async())
        loop.close()

    def _update_friends_list(self):
        if not self.epic_client:
            return
        friends = self.epic_client.friends
        platform_groups = {"EPIC": [], "STEAM": [], "PSN": [], "XBL": [], "NINTENDO": []}

        for fid, info in friends.items():
            plat_accounts = info.platform_accounts
            assigned = False
            for plat in ["STEAM", "PSN", "XBL", "NINTENDO"]:
                if plat in plat_accounts:
                    platform_groups[plat].append(info)
                    assigned = True
                    break
            if not assigned:
                platform_groups["EPIC"].append(info)

        if platform_groups["EPIC"]:
            self._rebuild_section(self.epic_frame, platform_groups["EPIC"])
        else:
            self._rebuild_section(self.epic_frame, [], "No Epic friends yet.")

        for plat, attr in [("STEAM", "steam_frame"), ("PSN", "psn_frame"),
                           ("XBL", "xbl_frame"), ("NINTENDO", "nintendo_frame")]:
            frame = getattr(self, attr, None)
            if frame:
                if platform_groups[plat]:
                    self._rebuild_section(frame, platform_groups[plat])
                else:
                    self._rebuild_section(frame, [], "No friends on this platform.")

    def _rebuild_section(self, frame: ttk.Frame, friends: list[FriendInfo], empty_msg=""):
        for widget in frame.winfo_children():
            widget.destroy()

        if not friends:
            ttk.Label(frame, text=empty_msg, foreground="gray").pack(padx=8, pady=4)
            return

        for info in friends:
            row = ttk.Frame(frame)
            row.pack(fill=tk.X, padx=6, pady=1)

            status_dot = "●" if info.is_online else "○"
            dot_color = "green" if info.is_online else "gray"
            dot = tk.Label(row, text=status_dot, fg=dot_color, bg="#1E1E1E",
                           font=("Segoe UI", 10))
            dot.pack(side=tk.LEFT, padx=(4, 6))

            plat_badges = []
            for platform in ["STEAM", "PSN", "XBL", "NINTENDO"]:
                if platform in info.platform_accounts:
                    plat_badges.append(PLATFORM_BADGES[platform])

            name_text = info.display_name
            if plat_badges:
                name_text += f"  [{', '.join(plat_badges)}]"

            name = tk.Label(row, text=name_text, fg="white", bg="#1E1E1E",
                            font=("Segoe UI", 9), anchor=tk.W)
            name.pack(side=tk.LEFT, fill=tk.X, expand=True)

            if info.activity:
                act = tk.Label(row, text=info.activity, fg="#888", bg="#1E1E1E",
                               font=("Segoe UI", 8), anchor=tk.E)
                act.pack(side=tk.RIGHT, padx=6)

            def make_handler(fid, fname):
                def on_right_click(event):
                    self._context_friend = (fid, fname)
                    try:
                        self.context_menu.tk_popup(event.x_root, event.y_root)
                    finally:
                        self.context_menu.grab_release()

                def on_double_click(event):
                    self._open_chat_for(fid, fname)

                return on_right_click, on_double_click

            rclick, dclick = make_handler(info.friend_id, info.display_name)
            for widget in (row, dot, name):
                widget.bind("<Button-3>", rclick)
                widget.bind("<Double-Button-1>", dclick)

    def _show_properties(self):
        if not self._context_friend:
            return
        fid, fname = self._context_friend
        friend = self.epic_client.friends.get(fid)
        if friend:
            PropertiesDialog(self, friend)

    def _open_chat(self):
        if not self._context_friend:
            return
        fid, fname = self._context_friend
        self._open_chat_for(fid, fname)

    def _ping_friend(self):
        if not self._context_friend or not self.irc_client:
            return
        _, fname = self._context_friend
        self.irc_client.ping_user(fname)
        self.status_label.config(text=f"Pinging {fname}...", foreground="cyan")

    def _send_file(self):
        if not self._context_friend or not self.irc_client:
            return
        from tkinter import filedialog
        path = filedialog.askopenfilename(title="Select file to send")
        if not path:
            return
        fid, fname = self._context_friend
        messagebox.showwarning(
            "IP Warning",
            f"Sending via DCC. {fname} will see your IP address.\n"
            "This was standard in old chat systems. Proceed?"
        )
        import asyncio
        asyncio.run_coroutine_threadsafe(
            self.irc_client.dcc_send_file(fname, Path(path)),
            self.epic_client._loop
        )

    def _open_chat_for(self, friend_id: str, display_name: str):
        friend = self.epic_client.friends.get(friend_id)
        if not friend:
            return
        if friend_id in self.chat_windows:
            self.chat_windows[friend_id].lift()
            return
        friend_info = FriendInfo(friend_id, display_name, friend.presence)
        cw = ChatWindow(self, friend_info, self.epic_client)
        self.chat_windows[friend_id] = cw

        def on_close():
            self.chat_windows.pop(friend_id, None)
            cw.destroy()

        cw.protocol("WM_DELETE_WINDOW", on_close)

    def _handle_incoming_message(self, data: dict):
        fid = data["friend_id"]
        sender = data["display_name"]
        content = data["content"]
        if fid in self.chat_windows:
            self.chat_windows[fid].receive_message(sender, content)

    def set_epic_client(self, client: EpicClient):
        self.epic_client = client

    def set_discord_client(self, client: DiscordClient):
        self.discord_client = client

    def on_close(self):
        if self.epic_client:
            self.epic_client.stop()
        self.destroy()
