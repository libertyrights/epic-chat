import asyncio
import json
import os
import secrets
import subprocess
import time
import winsound
from pathlib import Path
from queue import Queue
from threading import Thread
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QSize, QUrl
from PyQt6.QtGui import QFont, QIcon, QAction, QColor, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem, QLabel, QPushButton, QLineEdit,
    QTextEdit, QDialog, QMessageBox, QMenu, QFrame, QScrollArea,
    QInputDialog, QFileDialog, QStatusBar, QSplitter, QHeaderView,
    QStyleFactory, QProgressBar, QTabWidget, QFormLayout, QCheckBox,
    QSystemTrayIcon, QGroupBox,
)

from discord_client import DiscordClient
from epic_client import EpicClient, FriendInfo
from irc_client import IRCClient
from spotify_client import SpotifyClient, NowPlaying
from steam_client import SteamClient
from zerotier_client import ZeroTierClient
from sound import generate_notify_sound, generate_online_sound, play_easter_egg, SOUND_PATH, ONLINE_SOUND_PATH
from uploader import upload_file

CONFIG_DIR = Path(os.environ.get("APPDATA", ".")) / "EpicChat"
CONFIG_FILE = CONFIG_DIR / "config.json"
SOUND_ENABLED_FILE = CONFIG_DIR / "sound_enabled.txt"

STYLESHEET = """
QMainWindow, QDialog {
    background-color: #0A0A14;
    color: #E0E0E0;
}
QTreeWidget {
    background-color: #0F0F1E;
    color: #E0E0E0;
    border: none;
    font-size: 13px;
    outline: none;
}
QTreeWidget::item {
    padding: 6px 4px;
    border-bottom: 1px solid #1A1A30;
}
QTreeWidget::item:hover {
    background-color: #1A1A35;
}
QTreeWidget::item:selected {
    background-color: #1E1E45;
    color: #00D4FF;
}
QPushButton {
    background-color: #1A1A3E;
    color: #00D4FF;
    border: 1px solid #00D4FF;
    border-radius: 4px;
    padding: 5px 14px;
    font-size: 12px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #252550;
    border-color: #00F0FF;
}
QPushButton:pressed {
    background-color: #0F0F30;
}
QPushButton:disabled {
    background-color: #151520;
    color: #555;
    border-color: #333;
}
QPushButton.toggle-active {
    background-color: #00D4FF;
    color: #0A0A14;
}
QLabel {
    color: #E0E0E0;
}
QLineEdit {
    background-color: #151528;
    color: #E0E0E0;
    border: 1px solid #2A2A50;
    border-radius: 4px;
    padding: 6px 10px;
    font-size: 13px;
}
QLineEdit:focus {
    border-color: #00D4FF;
}
QTextEdit {
    background-color: #0D0D1A;
    color: #E0E0E0;
    border: 1px solid #2A2A50;
    border-radius: 4px;
    font-size: 13px;
}
QScrollBar:vertical {
    background: #0F0F1E;
    width: 8px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #2A2A50;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #3A3A70;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QMenu {
    background-color: #141428;
    color: #E0E0E0;
    border: 1px solid #2A2A50;
    border-radius: 4px;
    padding: 4px;
}
QMenu::item {
    padding: 6px 24px;
    border-radius: 3px;
}
QMenu::item:selected {
    background-color: #1E1E45;
    color: #00D4FF;
}
QStatusBar {
    background-color: #080812;
    color: #888;
    border-top: 1px solid #1A1A30;
}
QTabWidget::pane { border: 1px solid #2A2A50; background: #0A0A14; }
QTabBar::tab { background: #151528; color: #888; padding: 8px 16px; border: 1px solid #2A2A50; border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; }
QTabBar::tab:selected { background: #1E1E45; color: #00D4FF; }
QGroupBox { border: 1px solid #2A2A50; border-radius: 4px; margin-top: 8px; padding-top: 12px; color: #E0E0E0; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
QProgressBar { background: #1A1A30; border: 1px solid #2A2A50; border-radius: 3px; text-align: center; color: #CCC; font-size: 10px; }
QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #00D4FF, stop:1 #9B59B6); border-radius: 2px; }
"""

PLATFORM_STYLES = {
    "EPIC": ("Epic", "#2A2A2A"),
    "STEAM": ("Steam", "#1B2838"),
    "PSN": ("PS", "#003087"),
    "XBL": ("Xbox", "#107C10"),
    "NINTENDO": ("Switch", "#E60012"),
    "DISCORD": ("Discord", "#5865F2"),
}

SOUND_ENABLED = SOUND_ENABLED_FILE.exists() and SOUND_ENABLED_FILE.read_text().strip() == "1"
if not SOUND_ENABLED_FILE.exists():
    SOUND_ENABLED_FILE.write_text("1")
    SOUND_ENABLED = True


def _play_notify():
    if not SOUND_ENABLED:
        return
    try:
        path = SOUND_PATH
        if not path.exists():
            generate_notify_sound(path)
        winsound.PlaySound(str(path), winsound.SND_ASYNC | winsound.SND_FILENAME | winsound.SND_NODEFAULT)
    except Exception:
        pass


def _play_online():
    if not SOUND_ENABLED:
        return
    try:
        path = ONLINE_SOUND_PATH
        if not path.exists():
            generate_online_sound(path)
        winsound.PlaySound(str(path), winsound.SND_ASYNC | winsound.SND_FILENAME | winsound.SND_NODEFAULT)
    except Exception:
        pass


def _handle_sounder(text: str) -> bool:
    if not text.startswith("{S") and not text.startswith("{s"):
        return False
    rest = text[2:].strip().lstrip()
    if not rest:
        return False
    fname = rest.split()[0].strip().strip("{}").strip()
    if not fname:
        return False
    path = play_easter_egg(fname)
    if path:
        try:
            winsound.PlaySound(path, winsound.SND_ASYNC | winsound.SND_FILENAME | winsound.SND_NODEFAULT)
        except Exception:
            pass
    return True


def _toggle_sound():
    global SOUND_ENABLED
    SOUND_ENABLED = not SOUND_ENABLED
    SOUND_ENABLED_FILE.write_text("1" if SOUND_ENABLED else "0")
    return SOUND_ENABLED


class PropertiesDialog(QDialog):
    def __init__(self, parent, friend: FriendInfo):
        super().__init__(parent)
        self.setWindowTitle(f"Properties \u2014 {friend.display_name}")
        self.setFixedSize(380, 320)
        self.setStyleSheet(STYLESHEET)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        name = QLabel(f"<b style='font-size:16px'>{friend.display_name}</b>")
        name.setStyleSheet("color: #00D4FF;")
        layout.addWidget(name)
        info = QLabel(
            f"<b>Epic ID:</b> {friend.friend_id}<br>"
            f"<b>Status:</b> {'🟢 Online' if friend.is_online else '○ Offline'}"
            + (f" \u2014 {friend.activity}" if friend.activity else "")
        )
        info.setWordWrap(True)
        info.setStyleSheet("padding: 8px 0;")
        layout.addWidget(info)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #2A2A50;")
        layout.addWidget(line)
        layout.addWidget(QLabel("<b>Linked Accounts</b>"))
        if friend.platform_accounts:
            for plat, acct in sorted(friend.platform_accounts.items()):
                style = PLATFORM_STYLES.get(plat)
                tag = style[0] if style else plat
                lbl = QLabel(f"<span style='color:#888'>[{tag}]</span> {acct}")
                layout.addWidget(lbl)
        else:
            layout.addWidget(QLabel("  No linked accounts"))
        layout.addStretch()
        btn = QPushButton("Close")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignRight)


class ChatWindow(QDialog):
    def __init__(self, parent, friend_name: str, send_fn, accent="#00D4FF", notice_fn=None):
        super().__init__(parent)
        self.setWindowTitle(f"Chat \u2014 {friend_name}")
        self.setMinimumSize(420, 480)
        self.setStyleSheet(STYLESHEET)
        self.send_fn = send_fn
        self.notice_fn = notice_fn or send_fn
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        header = QLabel(f"<b style='font-size:14px'>{friend_name}</b>")
        header.setStyleSheet(f"color: {accent}; padding-bottom: 6px;")
        layout.addWidget(header)
        self.chat_log = QTextEdit()
        self.chat_log.setReadOnly(True)
        self.chat_log.setMinimumHeight(300)
        layout.addWidget(self.chat_log)
        entry_frame = QHBoxLayout()
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("Type a message...")
        self.entry.returnPressed.connect(self.send)
        entry_frame.addWidget(self.entry)
        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self.send)
        entry_frame.addWidget(send_btn)
        chirp_btn = QPushButton("🔊 Chirp")
        chirp_btn.setFixedWidth(80)
        chirp_btn.setStyleSheet("color: #00D4FF; font-weight: bold;")
        chirp_btn.clicked.connect(self._chirp)
        entry_frame.addWidget(chirp_btn)
        upload_btn = QPushButton("📎 Upload")
        upload_btn.setFixedWidth(80)
        upload_btn.clicked.connect(self._upload)
        entry_frame.addWidget(upload_btn)
        layout.addLayout(entry_frame)

    def send(self):
        text = self.entry.text().strip()
        if text:
            self.send_fn(text)
            self.append_message("You", text, "#00D4FF")
            self.entry.clear()

    def _chirp(self):
        self.send_fn("{S chirp.wav}")
        self.chat_log.append("<b style='color:#00D4FF'>🔊 Chirp!</b>")
        self.entry.clear()
        path = play_easter_egg("chirp.wav")
        if path:
            try:
                winsound.PlaySound(path, winsound.SND_ASYNC | winsound.SND_FILENAME | winsound.SND_NODEFAULT)
            except Exception:
                pass

    def _upload(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select file to share")
        if not path:
            return
        from uploader import upload_file
        import asyncio
        from threading import Thread

        def _do():
            loop = asyncio.new_event_loop()
            try:
                url = loop.run_until_complete(upload_file(path))
                self.chat_log.append(f"<b style='color:#FFAA00'>\u26a0 Shared:</b> "
                                     f"<a href='{url}'>{Path(path).name}</a>")
                self.notice_fn(url)
            except Exception as e:
                self.chat_log.append(f"<b style='color:#FF4444'>Upload failed:</b> {e}")
            finally:
                loop.close()

        Thread(target=_do, daemon=True).start()

    def append_message(self, who: str, text: str, color="#E0E0E0"):
        self.chat_log.append(f"<b style='color:{color}'>{who}:</b> {text}")
        _play_notify()


class SettingsDialog(QDialog):
    def __init__(self, parent, config: dict):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(520, 400)
        self.setStyleSheet(STYLESHEET)
        self.config = config
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        dc = QWidget()
        tabs.addTab(dc, "Discord")
        dfl = QFormLayout(dc)
        self.dc_id = QLineEdit(config.get("discord", {}).get("client_id", ""))
        self.dc_secret = QLineEdit(config.get("discord", {}).get("client_secret", ""))
        self.dc_bot = QLineEdit(config.get("discord", {}).get("bot_token", ""))
        self.dc_bot.setEchoMode(QLineEdit.EchoMode.Password)
        self.dc_secret.setEchoMode(QLineEdit.EchoMode.Password)
        dfl.addRow("Client ID:", self.dc_id)
        dfl.addRow("Client Secret:", self.dc_secret)
        dfl.addRow("Bot Token:", self.dc_bot)

        sp = QWidget()
        tabs.addTab(sp, "Spotify")
        sfl = QFormLayout(sp)
        self.sp_id = QLineEdit(config.get("spotify", {}).get("client_id", ""))
        self.sp_secret = QLineEdit(config.get("spotify", {}).get("client_secret", ""))
        self.sp_secret.setEchoMode(QLineEdit.EchoMode.Password)
        sfl.addRow("Client ID:", self.sp_id)
        sfl.addRow("Client Secret:", self.sp_secret)

        st = QWidget()
        tabs.addTab(st, "Steam")
        stfl = QFormLayout(st)
        self.st_key = QLineEdit(config.get("steam", {}).get("api_key", ""))
        self.st_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.st_id = QLineEdit(config.get("steam", {}).get("steam_id", ""))
        stfl.addRow("API Key:", self.st_key)
        stfl.addRow("Steam ID64:", self.st_id)

        gn = QWidget()
        tabs.addTab(gn, "General")
        gfl = QVBoxLayout(gn)
        self.sound_cb = QCheckBox("Enable notification sounds")
        self.sound_cb.setChecked(SOUND_ENABLED)
        self.sound_cb.setStyleSheet("color: #E0E0E0;")
        gfl.addWidget(self.sound_cb)
        gfl.addStretch()

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _save(self):
        self.config["discord"] = {
            "client_id": self.dc_id.text().strip(),
            "client_secret": self.dc_secret.text().strip(),
            "bot_token": self.dc_bot.text().strip(),
        }
        self.config["spotify"] = {
            "client_id": self.sp_id.text().strip(),
            "client_secret": self.sp_secret.text().strip(),
        }
        self.config["steam"] = {
            "api_key": self.st_key.text().strip(),
            "steam_id": self.st_id.text().strip(),
        }
        global SOUND_ENABLED
        SOUND_ENABLED = self.sound_cb.isChecked()
        SOUND_ENABLED_FILE.write_text("1" if SOUND_ENABLED else "0")
        CONFIG_FILE.write_text(json.dumps(self.config, indent=2))
        self.accept()


class SteamCompareDialog(QDialog):
    def __init__(self, parent, friend_name: str, result: dict):
        super().__init__(parent)
        self.setWindowTitle(f"Library vs {friend_name}")
        self.setMinimumSize(520, 460)
        self.setStyleSheet(STYLESHEET)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        header = QLabel(
            f"<b style='font-size:15px'>Steam Library Comparison</b><br>"
            f"<span style='color:#888'>with {friend_name}</span>"
        )
        header.setStyleSheet("padding-bottom: 10px;")
        layout.addWidget(header)

        def make_section(title, games, color):
            frame = QFrame()
            frame.setStyleSheet("background: #151528; border-radius: 6px; padding: 6px;")
            fl = QVBoxLayout(frame)
            fl.setContentsMargins(8, 6, 8, 6)
            cl = QLabel(f"<b style='color:{color}'>{title}</b>  <span style='color:#888'>({len(games)})</span>")
            fl.addWidget(cl)
            if games:
                text = ", ".join(g["name"] for g in games[:25])
                if len(games) > 25:
                    text += f" \u2026and {len(games) - 25} more"
                gl = QLabel(text)
                gl.setWordWrap(True)
                gl.setStyleSheet("color: #CCC; padding: 4px 0;")
                fl.addWidget(gl)
            else:
                fl.addWidget(QLabel("<span style='color:#555'>None</span>"))
            return frame

        layout.addWidget(make_section("🟣 Both Own", result.get("common", []), "#BB86FC"))
        layout.addWidget(make_section("🟢 You Only", result.get("my_uniques", []), "#00FF88"))
        layout.addWidget(make_section("🟠 They Only", result.get("friend_uniques", []), "#FFA500"))
        btn = QPushButton("Close")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignRight)


class EpicChatApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Epic Chat")
        self.setMinimumSize(600, 720)
        self.resize(640, 800)
        self.setStyleSheet(STYLESHEET)

        self.epic_client: Optional[EpicClient] = None
        self.discord_client: Optional[DiscordClient] = None
        self.irc_client: Optional[IRCClient] = None
        self.spotify_client: Optional[SpotifyClient] = None
        self.steam_client: Optional[SteamClient] = None
        self.zt_client: Optional[ZeroTierClient] = None
        self.chat_windows: dict[str, ChatWindow] = {}
        self.event_queue: Queue = Queue()
        self._dcc_transfers: list[dict] = []
        self._config: dict = {}
        self._discord_tree_user: Optional[QTreeWidgetItem] = None

        self._build_ui()
        self._build_tray()

        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll_events)
        self._poll_timer.start(100)

    # ==================== UI BUILD ====================

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 0)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(20)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.itemDoubleClicked.connect(self._on_item_double_click)
        layout.addWidget(self.tree, stretch=1)

        self._build_sections()
        self._build_statusbar()

    def _build_statusbar(self):
        sb = self.statusBar()
        self.status_label = QLabel("Not connected")
        self.status_label.setStyleSheet("color: #888; padding-left: 8px;")
        sb.addWidget(self.status_label, 1)

        self.dcc_progress = QProgressBar()
        self.dcc_progress.setFixedWidth(140)
        self.dcc_progress.setFixedHeight(16)
        self.dcc_progress.setTextVisible(True)
        self.dcc_progress.setVisible(False)
        sb.addPermanentWidget(self.dcc_progress)

        self.sound_btn = QPushButton("🔊" if SOUND_ENABLED else "🔇")
        self.sound_btn.setFixedWidth(36)
        self.sound_btn.clicked.connect(self._toggle_sound_btn)
        sb.addPermanentWidget(self.sound_btn)

        self.zt_btn = QPushButton("ZT Off")
        self.zt_btn.clicked.connect(self._prompt_zt_network)
        sb.addPermanentWidget(self.zt_btn)

        self.discord_btn = QPushButton("DC")
        self.discord_btn.clicked.connect(self._toggle_discord)
        sb.addPermanentWidget(self.discord_btn)

        self.spotify_btn = QPushButton("🎵")
        self.spotify_btn.clicked.connect(self._toggle_spotify)
        sb.addPermanentWidget(self.spotify_btn)

        self.irc_join_btn = QPushButton("+Ch")
        self.irc_join_btn.setFixedWidth(36)
        self.irc_join_btn.clicked.connect(self._join_irc_channel)
        sb.addPermanentWidget(self.irc_join_btn)

        self.irc_part_btn = QPushButton("-Ch")
        self.irc_part_btn.setFixedWidth(36)
        self.irc_part_btn.clicked.connect(self._part_irc_channel)
        sb.addPermanentWidget(self.irc_part_btn)

        self.irc_btn = QPushButton("Chat Offline")
        self.irc_btn.clicked.connect(self._prompt_irc_setup)
        sb.addPermanentWidget(self.irc_btn)

        self.epic_btn = QPushButton("Epic")
        self.epic_btn.clicked.connect(self._prompt_login)
        sb.addPermanentWidget(self.epic_btn)

        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setFixedWidth(34)
        self.settings_btn.clicked.connect(self._open_settings)
        sb.addPermanentWidget(self.settings_btn)

    def _build_sections(self):
        self.section_items = {}
        self.opencode_item = None
        self.activity_root = None
        self.spotify_section = None
        self.discord_section = None

        sections = [
            ("OPENCODE", "OpenCode AI", "#9B59B6"),
            ("FEED", "🎮 Activity Feed", "#FF6B35"),
            ("SPOTIFY", "🎵 Now Playing", "#1DB954"),
            ("DISCORD", "Discord", "#5865F2"),
            ("EPIC", "Epic", "#2A2A2A"),
            ("STEAM", "Steam", "#1B2838"),
            ("PSN", "PS", "#003087"),
            ("XBL", "Xbox", "#107C10"),
            ("NINTENDO", "Switch", "#E60012"),
            ("LAN", "🌐 LAN Party", "#00FF88"),
        ]
        for key, label, color in sections:
            item = QTreeWidgetItem(self.tree, [label])
            item.setExpanded(True)
            f = item.font(0)
            f.setBold(True)
            f.setPointSize(11)
            item.setFont(0, f)
            item.setForeground(0, QColor(color))
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            self.section_items[key] = item

        oc_child = QTreeWidgetItem(self.section_items["OPENCODE"], ["  OpenCode AI"])
        oc_child.setForeground(0, QColor("#BB86FC"))
        oc_child.setData(0, Qt.ItemDataRole.UserRole, "__opencode__")
        self.opencode_item = oc_child

        self.activity_root = self.section_items["FEED"]
        self.spotify_section = self.section_items["SPOTIFY"]
        self.discord_section = self.section_items["DISCORD"]
        self.lan_root = self.section_items["LAN"]

        self.friend_items: dict[str, QTreeWidgetItem] = {}

    def _build_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setToolTip("Epic Chat")
        tray_menu = QMenu(self)
        show_act = tray_menu.addAction("Show / Hide")
        show_act.triggered.connect(self._toggle_visible)
        tray_menu.addSeparator()
        quit_act = tray_menu.addAction("Quit")
        quit_act.triggered.connect(self.close)
        self.tray.setContextMenu(tray_menu)
        self.tray.activated.connect(lambda reason: self._toggle_visible() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray.show()

    # ==================== SYSTEM TRAY ====================

    def _toggle_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    # ==================== POLLING ====================

    def _poll_events(self):
        try:
            while True:
                event_type, data = self.event_queue.get_nowait()
                self._handle_event(event_type, data)
        except Exception:
            pass

    def _handle_event(self, event_type: str, data):
        handlers = {
            "auth_required": lambda: self._show_auth_dialog(data),
            "auth_ready": lambda: self._on_auth_ready(data),
            "auth_failed": lambda: self._show_status(data, "#FF4444"),
            "friends_updated": self._update_friends_list,
            "presence_changed": lambda: self._on_presence_changed(data),
            "message": lambda: self._handle_incoming_message(data),
            "irc_status": lambda: self._on_irc_status(data),
            "irc_ready": lambda: self._show_status(f"IRC: {data}", "#00FF88"),
            "irc_error": lambda: self._show_status(data, "#FF4444"),
            "irc_message": lambda: self._handle_irc_message(data),
            "irc_ping_result": lambda: self._show_status(f"Ping: {data['latency_ms']}ms", "#00D4FF"),
            "irc_channel_joined": lambda: self._show_status(f"Joined: {data}", "#00FF88"),
            "dcc_offer": lambda: self._handle_dcc_offer(data),
            "dcc_progress": lambda: self._update_dcc_progress(data),
            "dcc_sent": lambda: self._show_status(f"Sent: {data}", "#00FF88"),
            "opencode_response": lambda: self._on_opencode_response(data),
            "steam_compare_result": self._on_steam_compare,
            "spotify_update": self._on_spotify_update,
            "discord_ready": self._on_discord_ready,
            "zt_status": lambda: self._on_zt_status(data),
            "zt_ip": lambda: self._on_zt_ip(data),
            "zt_error": lambda: self._show_status(data, "#FF4444"),
            "upload_done": lambda: self._on_upload_done(data),
        }
        handler = handlers.get(event_type)
        if handler:
            handler()

    # ==================== STATUS HELPERS ====================

    def _show_status(self, msg: str, color="#888"):
        self.status_label.setText(str(msg))
        self.status_label.setStyleSheet(f"color: {color}; padding-left: 8px;")

    def _on_auth_ready(self, name: str):
        self._show_status(f"Epic: {name}", "#00FF88")
        self.epic_btn.setText("Epic ✓")

    def _on_irc_status(self, msg: str):
        self._show_status(msg)
        self.irc_btn.setText("Chat ✓" if "Connected" in str(msg) else "Chat Offline")

    # ==================== AUTH ====================

    def _show_auth_dialog(self, message: str):
        code, ok = QInputDialog.getText(self, "Epic Login", str(message) + "\n\nExchange Code:")
        if ok and code.strip():
            pass  # handled by epic_client

    def _prompt_login(self):
        if not self.epic_client:
            self.epic_client = EpicClient(self.event_queue)
            self.epic_client.start()
        else:
            self.epic_client.stop()
            self.epic_client = EpicClient(self.event_queue)
            self.epic_client.start()

    # ==================== DISCORD ====================

    def _toggle_discord(self):
        if not self.discord_client:
            return
        if self.discord_client.logged_in:
            self.discord_client.logout()
            self.discord_btn.setText("DC")
            self._show_status("Discord logged out", "#888")
            self._update_discord_section(None)
        else:
            self.discord_client.start_auth()
            asyncio.run_coroutine_threadsafe(
                self.discord_client.login_async(), self.epic_client._loop
            )

    def _on_discord_ready(self, data):
        if data is None:
            self.discord_btn.setText("DC")
            self._update_discord_section(None)
            return
        self.discord_btn.setText("DC ✓")
        self._show_status(f"Discord: {data['username']}", "#5865F2")
        self._update_discord_section(data)

    def _update_discord_section(self, data):
        sec = self.discord_section
        if not sec:
            return
        while sec.childCount():
            sec.removeChild(sec.child(0))

        if data is None:
            child = QTreeWidgetItem(sec, ["  Not logged in"])
            child.setForeground(0, QColor("#555"))
            child.setFlags(child.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            return

        # Avatar + username child
        user = QTreeWidgetItem(sec, [f"  {data['username']}  ✦"])
        user.setForeground(0, QColor("#BB86FC"))
        self._discord_tree_user = user

        connections = data.get("connections", {})
        if connections:
            conns = "  ".join(f"[{k}] {v}" for k, v in connections.items())
            c = QTreeWidgetItem(sec, [f"  {conns}"])
            c.setForeground(0, QColor("#888"))
            c.setFlags(c.flags() & ~Qt.ItemFlag.ItemIsSelectable)

    # ==================== SPOTIFY ====================

    def _toggle_spotify(self):
        if not self.spotify_client:
            return
        if self.spotify_client.logged_in:
            self.spotify_client.logout()
            self.spotify_btn.setText("🎵")
            self._on_spotify_update(None)
            self._show_status("Spotify logged out", "#888")
        else:
            self.spotify_client.start_auth()
            asyncio.run_coroutine_threadsafe(
                self.spotify_client.login_async(), self.epic_client._loop
            )

    def _on_spotify_update(self, np):
        sec = self.spotify_section
        if not sec:
            return
        while sec.childCount():
            sec.removeChild(sec.child(0))

        if np is None:
            child = QTreeWidgetItem(sec, ["  Not playing"])
            child.setForeground(0, QColor("#555"))
            child.setFlags(child.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.spotify_btn.setText("🎵")
            return

        self.spotify_btn.setText("🎵 ✓")
        track = QTreeWidgetItem(sec, [f"  ♪ {np.track}"])
        track.setForeground(0, QColor("#1DB954"))
        artist = QTreeWidgetItem(sec, [f"    {np.artist}"])
        artist.setForeground(0, QColor("#CCC"))
        artist.setFlags(artist.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        if np.album:
            album = QTreeWidgetItem(sec, [f"    {np.album}"])
            album.setForeground(0, QColor("#888"))
            album.setFlags(album.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        # Progress bar inline
        if np.duration_ms > 0:
            pct = int(np.progress_ms * 100 / np.duration_ms)
            bar = QProgressBar()
            bar.setFixedHeight(8)
            bar.setValue(pct)
            bar.setTextVisible(False)
            bar.setStyleSheet(
                "QProgressBar { background: #1A1A30; border: none; border-radius: 2px; }"
                "QProgressBar::chunk { background: #1DB954; border-radius: 2px; }"
            )
            pw = QWidget()
            pl = QVBoxLayout(pw)
            pl.setContentsMargins(24, 2, 8, 2)
            pl.addWidget(bar)
            pi = QTreeWidgetItem(sec)
            sec.setItemWidget(pi, 0, pw)

    # ==================== ZEROTIER / LAN PARTY ====================

    def _prompt_zt_network(self):
        if not self.zt_client:
            self.zt_client = ZeroTierClient(self.event_queue)
            asyncio.run_coroutine_threadsafe(
                self.zt_client.start(), self.epic_client._loop
            )
            return
        if not self.zt_client.is_ready:
            nid, ok = QInputDialog.getText(self, "ZeroTier", "Enter Network ID:")
            if ok and nid.strip():
                asyncio.run_coroutine_threadsafe(
                    self.zt_client.join_network(nid.strip()), self.epic_client._loop
                )
        else:
            asyncio.run_coroutine_threadsafe(
                self.zt_client.leave_network(), self.epic_client._loop
            )

    def _on_zt_status(self, msg: str):
        self._show_status(str(msg))
        msg_s = str(msg).lower()
        if "ip:" in msg_s:
            self.zt_btn.setText("ZT ✓")
        elif "not found" in msg_s or "not running" in msg_s:
            self.zt_btn.setText("ZT ✗")

    def _on_zt_ip(self, ip: str):
        if self.irc_client:
            self.irc_client.dcc_override_ip = ip.split("/")[0]
        self._update_lan_party()

    def _update_lan_party(self):
        sec = self.lan_root
        if not sec:
            return
        while sec.childCount():
            sec.removeChild(sec.child(0))

        zt = self.zt_client
        if not zt or not zt.is_ready:
            c = QTreeWidgetItem(sec, ["  Not connected"])
            c.setForeground(0, QColor("#555"))
            c.setFlags(c.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            return

        ip = QTreeWidgetItem(sec, [f"  ZT IP: {zt.zt_ip}"])
        ip.setForeground(0, QColor("#00FF88"))
        ip.setFlags(ip.flags() & ~Qt.ItemFlag.ItemIsSelectable)

        def _refresh():
            loop = asyncio.new_event_loop()
            summary = loop.run_until_complete(zt.lan_party_summary())
            loop.close()
            self.event_queue.put(("lan_summary", summary))

        Thread(target=_refresh, daemon=True).start()

    def _on_lan_summary(self, data: dict):
        sec = self.lan_root
        if not sec:
            return
        # Refresh the root children after summary
        pass  # handled inline

    # ==================== IRC ====================

    def _prompt_irc_setup(self):
        if self.irc_client and self.irc_client.is_connected:
            asyncio.run_coroutine_threadsafe(
                self.irc_client.disconnect(), self.epic_client._loop
            )
            return
        nick = self.epic_client.logged_in_user if self.epic_client else "Gamer"
        nick, ok1 = QInputDialog.getText(self, "Chat Setup", "Choose a nickname:", text=nick or "Gamer")
        if not ok1 or not nick.strip():
            return
        nick = nick.strip()
        email, ok2 = QInputDialog.getText(self, "Chat Setup", "Email (to register your nickname):")
        if not ok2 or not email.strip():
            return
        self.irc_client = IRCClient(self.event_queue, nickname=nick)
        pw = secrets.token_hex(12)
        self.irc_client.nickserv_password = pw
        self.irc_client.nickserv_email = email.strip()
        self.irc_client.save_config()
        asyncio.run_coroutine_threadsafe(self.irc_client.connect(), self.epic_client._loop)

    def _handle_irc_message(self, data: dict):
        cid = f"irc:{data['from']}"
        content = data["content"]
        is_notice = data.get("is_notice", False)
        is_chirp = _handle_sounder(content)
        if is_chirp:
            if cid not in self.chat_windows:
                nick = data["from"]
                cw = ChatWindow(self, nick,
                                lambda t: self.irc_client.send_privmsg(nick, t),
                                notice_fn=lambda t: self.irc_client.send_notice(nick, t))
                self.chat_windows[cid] = cw
                cw.finished.connect(lambda: self.chat_windows.pop(cid, None))
                cw.show()
            self.chat_windows[cid].append_message(data["from"], content)
            self.chat_windows[cid].raise_()
            self.chat_windows[cid].activateWindow()
            return
        if is_notice:
            _play_online()
            if cid in self.chat_windows:
                self.chat_windows[cid].append_message(data["from"], f"\u26a0 {content}", "#FFAA00")
            else:
                self._show_status(f"Notice from {data['from']}: {content[:40]}", "#FFAA00")
            if self.tray and self.tray.supportsMessages():
                self.tray.showMessage("Notice", f"{data['from']}: {content[:80]}",
                                      QSystemTrayIcon.MessageIcon.Information, 5000)
            return
        if cid in self.chat_windows:
            self.chat_windows[cid].append_message(data["from"], content)
        else:
            self._show_status(f"Msg from {data['from']}: {content[:40]}", "#FFAA00")
            _play_notify()
            if self.tray and self.tray.supportsMessages():
                self.tray.showMessage("Epic Chat", f"{data['from']}: {content[:80]}",
                                      QSystemTrayIcon.MessageIcon.Information, 3000)

    # ==================== DCC ====================

    def _handle_dcc_offer(self, transfer):
        resp = QMessageBox.question(self, "Incoming File",
            f"{transfer.sender_nick} wants to send:\n{transfer.filename} ({transfer.size} bytes)\n\n"
            "⚠ Your IP will be visible. Accept?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if resp != QMessageBox.StandardButton.Yes:
            return
        folder = QFileDialog.getExistingDirectory(self, "Save to...")
        if folder:
            asyncio.run_coroutine_threadsafe(
                self._do_accept_dcc(transfer, folder), self.epic_client._loop
            )

    async def _do_accept_dcc(self, transfer, folder: str):
        path = await transfer.accept(folder)
        if path:
            self.event_queue.put(("irc_status", f"Received: {path.name}"))
        else:
            self.event_queue.put(("irc_error", "File transfer failed"))

    def _update_dcc_progress(self, data: dict):
        sent = data.get("sent", data.get("received", 0))
        size = data.get("size", 0)
        if size > 0:
            pct = int(sent * 100 / size)
            self.dcc_progress.setValue(pct)
            self.dcc_progress.setFormat(f"{data['file']} ({pct}%)")
            self.dcc_progress.setVisible(True)
            if sent >= size:
                self.dcc_progress.setVisible(False)

    # ==================== IRC CHANNELS ====================

    def _join_irc_channel(self):
        if not self.irc_client:
            QMessageBox.warning(self, "Not Connected", "Connect to IRC first.")
            return
        name, ok = QInputDialog.getText(self, "Join Channel", "Channel name (e.g. #gaming):")
        if ok and name.strip():
            chan = name.strip() if name.strip().startswith("#") else f"#{name.strip()}"
            asyncio.run_coroutine_threadsafe(
                self.irc_client.join(chan), self.epic_client._loop
            )
            self._show_status(f"Joining {chan}...")

    def _part_irc_channel(self):
        if not self.irc_client:
            return
        name, ok = QInputDialog.getText(self, "Leave Channel", "Channel name (e.g. #gaming):")
        if ok and name.strip():
            chan = name.strip() if name.strip().startswith("#") else f"#{name.strip()}"
            asyncio.run_coroutine_threadsafe(
                self.irc_client.part(chan), self.epic_client._loop
            )

    # ==================== FRIENDS LIST ====================

    def _on_presence_changed(self, data):
        fid, old_status, new_status = data if isinstance(data, (list, tuple)) else (data, None, None)
        if old_status in (None, "offline") and new_status in ("online", "away"):
            _play_online()
        self._update_friends_list()

    def _update_friends_list(self):
        if not self.epic_client:
            return
        friends = self.epic_client.friends
        groups = {"EPIC": [], "STEAM": [], "PSN": [], "XBL": [], "NINTENDO": []}
        for fid, info in friends.items():
            assigned = False
            for plat in ["STEAM", "PSN", "XBL", "NINTENDO"]:
                if plat in info.platform_accounts:
                    groups[plat].append(info)
                    assigned = True
                    break
            if not assigned:
                groups["EPIC"].append(info)

        for key, items in groups.items():
            sec = self.section_items.get(key)
            if not sec:
                continue
            while sec.childCount():
                sec.removeChild(sec.child(0))
            self.friend_items = {k: v for k, v in self.friend_items.items() if v.parent() != sec}
            if not items:
                c = QTreeWidgetItem(sec, ["  No friends"])
                c.setForeground(0, QColor("#555"))
                c.setFlags(c.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                continue
            for info in items:
                dot = "🟢" if info.is_online else "○"
                name = info.display_name
                badges = [v for k, v in PLATFORM_STYLES.items() if k in info.platform_accounts]
                if badges:
                    name += "  " + " ".join(f"[{b[0]}]" for b in badges)
                display = f"{dot} {name}"
                if info.activity:
                    display += f"  \u2014  {info.activity}"
                child = QTreeWidgetItem(sec, [display])
                child.setData(0, Qt.ItemDataRole.UserRole, info.friend_id)
                child.setForeground(0, QColor("#E0E0E0") if info.is_online else QColor("#666"))
                self.friend_items[info.friend_id] = child

        self._update_activity_feed()

    def _update_activity_feed(self):
        if not self.epic_client or not self.activity_root:
            return
        root = self.activity_root
        while root.childCount():
            root.removeChild(root.child(0))
        acts = []
        for info in self.epic_client.friends.values():
            if info.activity:
                acts.append((info.display_name, info.activity, info.is_online))
            elif info.is_online:
                acts.append((info.display_name, "Online", info.is_online))
        if not acts:
            c = QTreeWidgetItem(root, ["  No activity"])
            c.setForeground(0, QColor("#555"))
            c.setFlags(c.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            return
        for name, activity, online in sorted(acts, key=lambda x: (not x[2], x[0])):
            dot = "🟢" if online else "○"
            c = QTreeWidgetItem(root, [f"  {dot} {name} \u2014 {activity}"])
            c.setForeground(0, QColor("#E0E0E0") if online else QColor("#555"))

    def _on_item_double_click(self, item, column):
        fid = item.data(0, Qt.ItemDataRole.UserRole)
        if fid == "__opencode__":
            self._open_opencode_chat()
            return
        if not self.epic_client:
            return
        friend = self.epic_client.friends.get(fid) if fid else None
        if friend:
            self._open_chat_for(friend)

    # ==================== CONTEXT MENU ====================

    def _show_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item or not item.data(0, Qt.ItemDataRole.UserRole):
            return
        fid = item.data(0, Qt.ItemDataRole.UserRole)
        menu = QMenu(self)

        if fid == "__opencode__":
            menu.addAction("Send Message", self._open_opencode_chat)
            menu.addSeparator()
            menu.addAction("About OpenCode", self._show_opencode_info)
            menu.exec(self.tree.mapToGlobal(pos))
            return

        if fid == "LAN" or fid == "FEED" or fid == "SPOTIFY":
            if fid == "LAN" and self.zt_client and self.zt_client.is_ready:
                menu.addAction("Refresh LAN Party", self._update_lan_party)
                menu.addSeparator()
                menu.addAction("Leave Network", self._prompt_zt_network)
            menu.exec(self.tree.mapToGlobal(pos))
            return

        friend = self.epic_client.friends.get(fid) if self.epic_client else None
        if not friend:
            return

        menu.addAction("Properties", lambda: PropertiesDialog(self, friend).exec())
        menu.addAction("Send Message", lambda: self._open_chat_for(friend))
        menu.addAction("📞 Direct Connect", lambda: self._direct_connect(friend))
        menu.addSeparator()
        if self._has_steam(friend):
            menu.addAction("Compare Steam Library", lambda: self._compare_steam_library(friend))
        menu.addAction("Ping (CTCP)", lambda: self._ping_friend(friend))
        menu.addAction("Send File...", lambda: self._send_file(friend))
        menu.addAction("Upload & Share Link", lambda: self._upload_and_share(
            lambda t: self.epic_client.send_message(friend.friend_id, t)))
        menu.exec(self.tree.mapToGlobal(pos))

    # ==================== CHAT ====================

    def _open_chat_for(self, friend: FriendInfo):
        cid = friend.friend_id
        if cid in self.chat_windows:
            self.chat_windows[cid].raise_()
            self.chat_windows[cid].activateWindow()
            return
        cw = ChatWindow(self, friend.display_name,
                        lambda t: self.epic_client.send_message(friend.friend_id, t))
        self.chat_windows[cid] = cw
        cw.finished.connect(lambda: self.chat_windows.pop(cid, None))
        cw.show()

    def _direct_connect(self, friend: FriendInfo):
        self._open_chat_for(friend)
        self.chat_windows[friend.friend_id]._chirp()

    def _handle_incoming_message(self, data: dict):
        fid = data["friend_id"]
        content = data["content"]
        is_chirp = _handle_sounder(content)
        if is_chirp:
            friend = self.epic_client.friends.get(fid) if self.epic_client else None
            if friend:
                self._open_chat_for(friend)
                self.chat_windows[fid].append_message(data["display_name"], content)
                self.chat_windows[fid].raise_()
                self.chat_windows[fid].activateWindow()
            return
        if fid in self.chat_windows:
            self.chat_windows[fid].append_message(data["display_name"], content)
        else:
            _play_notify()
            if self.tray and self.tray.supportsMessages():
                self.tray.showMessage("Epic Chat", f"{data['display_name']}: {content[:80]}",
                                      QSystemTrayIcon.MessageIcon.Information, 3000)

    # ==================== PING / FILE ====================

    def _ping_friend(self, friend: FriendInfo):
        if self.irc_client:
            self.irc_client.ping_user(friend.display_name)
            self._show_status(f"Pinging {friend.display_name}...", "#00D4FF")

    def _send_file(self, friend: FriendInfo):
        if not self.irc_client:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Select file to send")
        if not path:
            return
        QMessageBox.warning(self, "IP Warning",
            f"Sending via DCC.\n{friend.display_name} will see your IP address.")
        asyncio.run_coroutine_threadsafe(
            self.irc_client.dcc_send_file(friend.display_name, Path(path)),
            self.epic_client._loop
        )

    def _upload_and_share(self, send_fn):
        path, _ = QFileDialog.getOpenFileName(self, "Select file to share")
        if not path:
            return

        def _do():
            loop = asyncio.new_event_loop()
            try:
                url = loop.run_until_complete(upload_file(path))
                self.event_queue.put(("upload_done", (url, send_fn)))
            except Exception as e:
                self.event_queue.put(("upload_done", (None, send_fn, str(e))))
            finally:
                loop.close()

        self._show_status("Uploading...", "#FFAA00")
        Thread(target=_do, daemon=True).start()

    def _on_upload_done(self, data):
        url, send_fn = data[0], data[1]
        if url:
            send_fn(url)
            self._show_status(f"Shared: {url}", "#00FF88")
        else:
            err = data[2] if len(data) > 2 else "Upload failed"
            self._show_status(err, "#FF4444")

    # ==================== STEAM ====================

    def _has_steam(self, friend: FriendInfo) -> bool:
        return "STEAM" in friend.platform_accounts

    def _compare_steam_library(self, friend: FriendInfo):
        if not self.steam_client:
            QMessageBox.warning(self, "Steam Not Configured", "Add your Steam API key and Steam ID to config.json")
            return
        sid = friend.platform_accounts["STEAM"]
        self._show_status(f"Fetching Steam library for {friend.display_name}...", "#FFA500")

        def run():
            try:
                loop = asyncio.new_event_loop()
                result = loop.run_until_complete(self.steam_client.compare_with_friend(sid))
                loop.close()
                self.event_queue.put(("steam_compare_result", (friend.display_name, result)))
            except Exception as e:
                self.event_queue.put(("steam_compare_result", (friend.display_name, None, str(e))))

        Thread(target=run, daemon=True).start()

    def _on_steam_compare(self, data):
        name, result = data
        if result is None:
            self._show_status(f"Steam compare failed for {name}", "#FF4444")
        else:
            self._show_status("Steam library comparison ready", "#00FF88")
            SteamCompareDialog(self, name, result).exec()

    # ==================== OPENCODE AI ====================

    def _open_opencode_chat(self):
        cid = "__opencode__"
        if cid in self.chat_windows:
            self.chat_windows[cid].raise_()
            self.chat_windows[cid].activateWindow()
            return
        cw = ChatWindow(self, "OpenCode AI", self._send_to_opencode, "#BB86FC")
        cw.setWindowTitle("Chat \u2014 OpenCode AI")
        cw.entry.setPlaceholderText("Ask big pickle anything...")
        cw.append_message("OpenCode AI", "Hey! Ask me anything \u2014 I'm powered by opencode + big pickle.", "#BB86FC")
        self.chat_windows[cid] = cw
        cw.finished.connect(lambda: self.chat_windows.pop(cid, None))
        cw.show()

    def _send_to_opencode(self, text: str):
        def run():
            try:
                result = subprocess.run(["opencode", "run", text],
                    capture_output=True, text=True, timeout=120)
                lines = result.stdout.splitlines()
                response = "\n".join(l for l in lines if l and not l.startswith("timestamp=") and not l.startswith(">"))
                self.event_queue.put(("opencode_response", response.strip()))
            except subprocess.TimeoutExpired:
                self.event_queue.put(("opencode_response", "(timed out \u2014 120s)"))
            except Exception as e:
                self.event_queue.put(("opencode_response", f"(error: {e})"))

        Thread(target=run, daemon=True).start()

    def _on_opencode_response(self, data):
        cw = self.chat_windows.get("__opencode__")
        if cw:
            cw.append_message("OpenCode AI", str(data), "#BB86FC")

    def _show_opencode_info(self):
        try:
            r = subprocess.run(["opencode", "--version"], capture_output=True, text=True, timeout=10)
            ver = r.stdout.strip() or r.stderr.strip()
        except Exception:
            ver = "unknown"
        QMessageBox.about(self, "About OpenCode AI",
            f"<b>OpenCode AI</b><br><br>Version: {ver}<br>Model: big-pickle<br><br>"
            "A gamer-friendly AI assistant integrated right into your chat app. "
            "Powered by opencode \u2014 the AI CLI for gamers who code.")

    # ==================== SETTINGS / SOUND ====================

    def _open_settings(self):
        dlg = SettingsDialog(self, self._config)
        if dlg.exec():
            self._config = dlg.config

    def set_config(self, config: dict):
        self._config = config

    def _toggle_sound_btn(self):
        on = _toggle_sound()
        self.sound_btn.setText("🔊" if on else "🔇")

    # ==================== SETTERS ====================

    def set_epic_client(self, client: EpicClient):
        self.epic_client = client

    def set_irc_client(self, client: IRCClient):
        self.irc_client = client

    def set_discord_client(self, client: DiscordClient):
        self.discord_client = client
        if client and client.logged_in:
            self.discord_btn.setText("DC ✓")

    def set_zt_client(self, client: ZeroTierClient):
        self.zt_client = client
        if client and client.is_ready:
            self.zt_btn.setText("ZT ✓")

    # ==================== LIFECYCLE ====================

    def closeEvent(self, event):
        if self.epic_client:
            self.epic_client.stop()
        self.tray.hide()
        event.accept()
