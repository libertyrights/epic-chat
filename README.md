# EpicChat

Multi-protocol gaming chat client — Epic Games friends + XMPP, IRC, Discord profiles, Spotify now-playing, Steam library compare, ZeroTier LAN party bridge, and OpenCode AI.

## Features

- **Epic Friends** — full friends list, presence, XMPP messaging via rebootpy
- **IRC** — multi-channel, NickServ auto-register, CTCP ping/version, DCC file transfers with resume
- **Discord** — OAuth2 profile viewing + connected accounts (Steam/PSN/XBL)
- **Spotify** — OAuth2 now-playing sync (15s polling)
- **Steam** — Web API owned games + library comparison between friends
- **ZeroTier** — LAN party bridging, console ARP scan (Xbox/PS/Switch), auto-discovers ZT IP for DCC
- **OpenCode AI** — built-in AI chat buddy via `opencode run`
- **Nextel Chirp** — Direct Connect-style chirp that auto-activates the recipient's chat window
- **File Sharing** — upload to 0x0.st ephemeral host, share link via IRC NOTICE or Epic message
- **Sounder Easter Eggs** — AOL-style `{S filename.wav}` commands (ahoy, lol, rickroll, bonk, doh, etc.)
- **Identd** — built-in RFC 1413 ident server for IRC (no tilde prefix)
- **Custom Sounds** — runtime WAV-generated notification chimes (no external audio files)
- **System Tray** — background operation with tray notifications
- **Dark Gaming Theme** — PyQt6 QSS with neon accents, gradient progress bars

## Download

Precompiled binary: [`bin/EpicChat.exe`](bin/EpicChat.exe)

## Requirements (source)

- Python 3.13+
- `pip install -r requirements.txt`

## Setup

1. Run `EpicChat.exe` or `python src/main.py`
2. Login to Epic Games via exchange code at epicgames.com/id/exchange
3. (Optional) Configure Discord/Spotify/Steam API keys in Settings (⚙)
4. (Optional) Connect IRC via Chat button in status bar
5. (Optional) Join a ZeroTier network for LAN party features

API keys are stored in `%APPDATA%/EpicChat/config.json`.

## Config

| Service | Key | Where to get it |
|---------|-----|----------------|
| Discord | `client_id`, `client_secret` | discord.com/developers/applications |
| Spotify | `client_id`, `client_secret` | developer.spotify.com/dashboard |
| Steam | `api_key`, `steam_id` | steamcommunity.com/dev/apikey |

## Build from source

```
pyinstaller EpicChat.spec
```

## Easter Eggs

Send `{S filename.wav}` in chat to trigger sounds on the recipient's client:

- `{S chirp.wav}` — Nextel Direct Connect chirp (auto-opens chat)
- `{S rickroll.wav}` — Never Gonna Give You Up intro
- `{S ahoy.wav}` — Pirate greeting
- `{S bonk.wav}` — Cartoon bonk
- `{S doh.wav}` — Groan
- `{S lol.wav}` — Giggle
- `{S welcome.wav}` — Ascending arpeggio
- `{S goodbye.wav}` — Descending slide
- `{S oops.wav}` — Mistake buzz
- `{S yeet.wav}` — Energy burst
- `{S woosh.wav}` — Comedy woosh
- `{S random.wav}` — Random pings

## Credits

**Brought to you by Liberty Rights Association — Protecting your rights and your wallet!**

**Author:** marktherusty

Free to use and modify with credit given to marktherusty and OpenCode.

Built with [OpenCode](https://opencode.ai) — the AI coding assistant that never charges API fees.

## License

MIT
