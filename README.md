# Touch Remote for Marantz

🇩🇪 [Deutsche Version](README.de.md)

**🐧 Linux only** – not for Windows, macOS, Android or iOS.

A touch remote for Marantz AV receivers (built and tested with the **SR7010**) –
as a lightweight Linux app (Python + GTK3).
Originally made for a Microsoft Surface 3 running Linux Mint XFCE, but it runs on any Linux with GTK3.

> Unofficial hobby project – not affiliated with Marantz / Sound United.
> “Marantz” is a trademark of its respective owner.
>
> Built and tested with the SR7010 only; other models may work only partly.
> It changes volume and sound settings on your receiver – **use at your own risk**.

![Control](docs/en-control.png)

## Features

- **Control:** power, volume as a matte black metal dial (its ring glows while you turn it), mute,
  sound mode buttons (Movie / Music / Game / Pure) and surround modes (Auto, Stereo, Direct,
  Pure Direct, Dolby, DTS, Neural:X, Multi Ch Stereo); the receiver model is detected automatically
- **Customizable (✎):** three scene buttons with your own names – input, surround mode and volume
  via “Use current settings” – and an input bar with up to 5 inputs.
  All receiver inputs are also available from the header.
  Stored in `~/.config/marantz/config.json`
- **Volume strip** on the right, within thumb reach: tap or hold “+” and “−”,
  or swipe vertically; fill level and number stay in sync with the dial
- **Volume safety:** maximum 90, soft stop with a warning at 80;
  swiping on the strip already stops at 60, above that it only goes step by step with “+”
- **Sound & Levels:** Audyssey MultEQ, Dynamic EQ + reference level, Dynamic Volume, Cinema EQ,
  subwoofer level, channel levels of all speakers (±0.5 / ±3 dB)
- **EQ:** bass/treble and a **9-band graphic EQ** per speaker group
- **Library:** browses a Plex server via UPnP and plays directly on the receiver –
  with cover art, seeking, queue and gapless playback (keeps playing in the background service)
- **Setup menu on the TV** via an on-screen D-pad
- **English and German** – chosen automatically from the system language
- Receiver and Plex server are **found automatically** on the home network (SSDP / ARP)
- Optional **offline voice control** (German) with [Vosk](https://alphacephei.com/vosk/)

| EQ | Sound & Levels |
|---|---|
| ![EQ](docs/en-eq.png) | ![Sound & Levels](docs/en-sound.png) |

## Download

**[⬇ Download the latest release](https://github.com/amplifie/touch-remote-for-marantz/releases/latest/download/touch-remote-for-marantz.tar.gz)** (Linux only) –
all versions are listed under [Releases](https://github.com/amplifie/touch-remote-for-marantz/releases).

```bash
tar xzf touch-remote-for-marantz.tar.gz
cd touch-remote-for-marantz
./install.sh
```

## Installation

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0   # if not installed yet
./install.sh
```

Then start **“Touch Remote for Marantz”** from the menu. The script installs for the current user only
(to `~/.local/share/marantz-fernbedienung`) and sets up the background service
`marantz-web` (systemd user service). Remove with `./uninstall.sh`.

**Language:** automatic (German if the system is set to German, otherwise English).
To change it, tap the 🌐 globe at the top right (Auto · Deutsch · English) – or set `"language"` in `~/.config/marantz/config.json`.

**Voice control (optional, German only for now):** put the Vosk library into
`~/.local/share/marantz-voice/lib` and the model `vosk-model-small-de-0.15` into
`~/.local/share/marantz-voice/model` – then the 🎤 button appears.
`mic-fix.sh` enables the built-in digital microphone of the Surface 3 (rt5645).

## How it works

| File | Purpose |
|---|---|
| `marantz.py` | Receiver control (HTTP commands, status XML, telnet queries, graphic EQ via the setup web page), command whitelist |
| `upnp.py` | Plex library (UPnP ContentDirectory) and the receiver as a renderer (AVTransport) |
| `server.py` | Background service (local only): JSON API for the app, playback queue |
| `app.py` | GTK3 touch interface |
| `i18n.py` | English / German translations |
| `voice.py`, `sprachbefehle.py` | Offline speech recognition and command parsing (German) |

Python standard library + GTK/Cairo only – no other dependencies.
Only commands from a fixed list are ever sent to the receiver.

## License

MIT – see [LICENSE](LICENSE).
