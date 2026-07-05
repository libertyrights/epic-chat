import json
import os
import sys
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from epic_chat_app_qt import EpicChatApp
from epic_client import EpicClient
from discord_client import DiscordClient
from spotify_client import SpotifyClient
from steam_client import SteamClient
from zerotier_client import ZeroTierClient

CONFIG_DIR = Path(os.environ.get("APPDATA", ".")) / "EpicChat"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "discord": {
        "client_id": "",
        "client_secret": "",
        "bot_token": ""
    },
    "spotify": {
        "client_id": "",
        "client_secret": ""
    },
    "steam": {
        "api_key": "",
        "steam_id": ""
    }
}

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
    return dict(DEFAULT_CONFIG)


def main():
    config = load_config()

    qapp = QApplication(sys.argv)

    app = EpicChatApp()
    app.set_config(config)
    app.show()

    event_queue = app.event_queue

    epic_client = EpicClient(event_queue)
    app.set_epic_client(epic_client)

    discord_cfg = config.get("discord", {})
    if discord_cfg.get("client_id") and discord_cfg.get("client_secret"):
        discord_client = DiscordClient(
            event_queue=event_queue,
            client_id=discord_cfg["client_id"],
            client_secret=discord_cfg["client_secret"],
            bot_token=discord_cfg.get("bot_token", ""),
        )
        discord_client.load_token()
        app.set_discord_client(discord_client)

    spotify_cfg = config.get("spotify", {})
    if spotify_cfg.get("client_id") and spotify_cfg.get("client_secret"):
        spotify_client = SpotifyClient(
            event_queue=event_queue,
            client_id=spotify_cfg["client_id"],
            client_secret=spotify_cfg["client_secret"],
        )
        spotify_client.load_token()
        app.spotify_client = spotify_client

    steam_cfg = config.get("steam", {})
    if steam_cfg.get("api_key") and steam_cfg.get("steam_id"):
        app.steam_client = SteamClient(
            api_key=steam_cfg["api_key"],
            steam_id=steam_cfg["steam_id"],
        )

    zt = ZeroTierClient(event_queue)
    app.set_zt_client(zt)
    QTimer.singleShot(1500, lambda: asyncio.run_coroutine_threadsafe(zt.start(), epic_client._loop))

    sys.exit(qapp.exec())


if __name__ == "__main__":
    main()
