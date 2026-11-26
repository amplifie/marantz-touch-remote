#!/usr/bin/env python3
"""Marantz-Fernbedienung: Hintergrunddienst (nur auf diesem Rechner erreichbar).

- stellt eine kleine JSON-Schnittstelle für die App bereit (127.0.0.1:8080)
- verwaltet die Musik-Wiedergabe aus der Plex-Bibliothek mit Warteschlange
  (läuft weiter, auch wenn die App geschlossen ist)
"""
import json
import threading
import time
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import i18n
import marantz as m
import upnp

PORT = 8080
HERE = Path(__file__).resolve().parent


class Player:
    """Spielt eine Liste von Titeln nacheinander auf dem Receiver ab."""

    def __init__(self):
        self.lock = threading.RLock()
        self.queue, self.i = [], -1
        self.active = False        # Warteschlange läuft (spielt oder pausiert)
        self.user_stop = False
        self.started = 0.0
        self.last = {}
        self.error = ""
        threading.Thread(target=self._loop, daemon=True).start()

    # ----- Steuerung -----
    def start(self, tracks, index):
        with self.lock:
            self.queue, self.i = tracks, index
            self._play_current()

    def _play_current(self):
        t = self.queue[self.i]
        upnp.set_uri(t["uri"], t["didl"])
        upnp.play()
        self.active, self.user_stop, self.started = True, False, time.time()
        self.last = {"state": "PLAYING", "elapsed": 0, "uri": t["uri"]}
        self._set_next()

    def _set_next(self):
        if self.i + 1 < len(self.queue):
            n = self.queue[self.i + 1]
            try:
                upnp.set_next(n["uri"], n["didl"])  # lückenloser Übergang, falls unterstützt
            except Exception:  # noqa: BLE001
                pass

    def control(self, action, t=None):
        with self.lock:
            if action == "pause":
                upnp.pause()
            elif action == "play":
                if self.active:
                    upnp.play()
                elif self.queue:
                    self._play_current()
            elif action == "toggle":
                if self.last.get("state") == "PLAYING":
                    upnp.pause()
                else:
                    self.control("play")
            elif action == "stop":
                self.user_stop, self.active = True, False
                upnp.stop()
            elif action == "next":
                if self.i + 1 < len(self.queue):
                    self.i += 1
                    self._play_current()
            elif action == "prev":
                if (self.last.get("elapsed") or 0) > 5 or self.i == 0:
                    upnp.seek(0)
                else:
                    self.i -= 1
                    self._play_current()
            elif action == "seek" and t is not None:
                upnp.seek(int(float(t)))   # wiederholt bei Bedarf selbst (upnp._avt)

    # ----- Beobachten (läuft im Hintergrund) -----
    def _loop(self):
        while True:
            time.sleep(1 if self.active else 3)
            if not self.active:
                continue
            try:
                s = upnp.state()
            except Exception as e:  # noqa: BLE001
                self.error = str(e)
                continue
            self.error = ""
            with self.lock:
                self._handle(s)
                self.last = s

    def _handle(self, s):
        q, i = self.queue, self.i
        # Receiver ist selbst zum nächsten Titel gewechselt (lückenlos)
        if s["uri"] and i + 1 < len(q) and s["uri"] == q[i + 1]["uri"]:
            self.i += 1
            self._set_next()
            return
        if s["state"] == "STOPPED" and not self.user_stop and time.time() - self.started > 5:
            prev = self.last
            dur = prev.get("duration") or (q[i].get("duration") if 0 <= i < len(q) else None)
            ended = prev.get("state") == "PLAYING" and dur and (prev.get("elapsed") or 0) >= dur - 4
            if ended and i + 1 < len(q):
                self.i += 1
                self._play_current()       # Titel zu Ende → nächsten starten
            else:
                self.active = False        # Ende der Liste oder anderswo gestoppt
                # (z. B. Eingang am Receiver gewechselt) – dann NICHT zurückholen

    def status(self):
        with self.lock:
            t = self.queue[self.i] if 0 <= self.i < len(self.queue) else None
            st = self.last.get("state", "") if self.active else "STOPPED"
            # Länge aus Plex (genau); der Receiver schätzt sie bei manchen MP3s falsch
            dur = (t or {}).get("duration") or self.last.get("duration")
            el = self.last.get("elapsed") if self.active else 0
            return {
                "active": self.active, "state": st,
                "id": t and t["id"], "title": t and t["title"], "artist": t and t.get("artist"),
                "album": t and t.get("album"), "art": t and t.get("art"),
                "elapsed": min(el or 0, dur) if dur else el, "duration": dur,
                "index": self.i + 1, "count": len(self.queue), "error": self.error,
            }


player = Player()
_artists = {"t": 0.0, "list": []}


def artists():
    """Alle Künstler aus Plex (für Sprachbefehle), 30 Minuten zwischengespeichert."""
    if _artists["list"] and time.time() - _artists["t"] < 1800:
        return _artists["list"]
    def find(oid, title):
        return next((i for i in upnp.browse(oid)["items"] if i["title"].lower() == title.lower()), None)
    music = find("0", "Music")
    folder = None
    for lib in upnp.browse(music["id"])["items"] if music else []:
        if lib["kind"] == "folder":
            folder = find(lib["id"], "All Artists")
            if folder:
                break
    if not folder:
        raise RuntimeError("Künstlerliste in Plex nicht gefunden")
    _artists["list"] = [{"id": a["id"], "title": a["title"]}
                        for a in upnp.browse_all(folder["id"]) if a["kind"] == "folder"]
    _artists["t"] = time.time()
    return _artists["list"]


def artist_tracks(artist_id, limit=400):
    """Alle Titel eines Künstlers (über seine Alben)."""
    tracks = []
    for sub in upnp.browse_all(artist_id):
        if sub["kind"] == "track":
            tracks.append(sub)
        elif sub["kind"] == "folder":
            tracks += [t for t in upnp.browse_all(sub["id"]) if t["kind"] == "track"]
        if len(tracks) >= limit:
            break
    return tracks[:limit]


def public(item):
    """Für die Oberfläche: ohne lange Interna (Adresse, DIDL)."""
    return {k: v for k, v in item.items() if k not in ("didl", "uri")}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keine Logs → schont den eMMC-Speicher
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            if u.path == "/api/status":
                self._json(m.status())
            elif u.path == "/api/group":
                self._json({"group": m.sound_group(q.get("s", ""))})
            elif u.path == "/api/settings":
                self._json(m.settings())
            elif u.path == "/api/cmd":
                cmd = q.get("c", "")
                if not m.ALLOWED.match(cmd):
                    return self._json({"error": "Befehl nicht erlaubt"}, 400)
                m.send(cmd)
                self._json({"ok": True})
            elif u.path == "/api/vol":
                new = m.change_volume(int(q.get("d", "0")))
                self._json({"ok": True, "volume": new, "loud": new >= m.LOUD})
            elif u.path == "/api/config":
                cfg = m.load_config()
                lang = "de" if q.get("lang") == "de" else "en"
                t = lambda x: i18n.tr_lang(x, lang)
                norm = lambda x: x.lower().replace(" ", "")
                self._json({
                    "profiles": [{"name": t(p.get("name", "")), "sub": t(m.profile_subtitle(p))}
                                 for p in cfg["profiles"]],
                    "inputs": [{"cmd": c, "name": t(m.source_name(c)),
                                "match": [norm(m.source_name(c)),
                                          norm(i18n.tr_lang(m.source_name(c), "en"))]}
                               for c in cfg["inputs"]],
                    "modes": [{"cmd": c, "name": t(n), "key": k} for c, n, k in m.MODES],
                    "groups": [{"cmd": c, "name": t(n)} for c, n in m.MODE_GROUPS],
                })
            elif u.path == "/api/scene":
                profiles = m.load_config()["profiles"]
                try:
                    n = int(q.get("n", ""))
                except ValueError:
                    n = -1
                if not 0 <= n < len(profiles):          # keine negativen/zu großen Nummern
                    return self._json({"error": "Unbekannte Szene"}, 400)
                p = profiles[n]
                m.run_profile(p)
                self._json({"ok": True})
            # ----- Musik-Bibliothek & Wiedergabe -----
            elif u.path == "/api/lib":
                r = upnp.browse(q.get("id", "0"), int(q.get("start", 0)), int(q.get("count", 200)))
                self._json({"items": [public(i) for i in r["items"]], "total": r["total"]})
            elif u.path == "/api/play":
                tracks = [i for i in upnp.browse_all(q["parent"]) if i["kind"] == "track"]
                idx = next((n for n, t in enumerate(tracks) if t["id"] == q.get("item")), 0)
                if not tracks:
                    return self._json({"error": "Keine abspielbaren Titel"}, 400)
                player.start(tracks, idx)
                self._json({"ok": True})
            elif u.path == "/api/artists":
                self._json(artists())
            elif u.path == "/api/play_artist":
                tracks = artist_tracks(q["id"])
                if not tracks:
                    return self._json({"error": "Keine Titel gefunden"}, 400)
                if q.get("shuffle"):
                    import random
                    random.shuffle(tracks)
                player.start(tracks, 0)
                self._json({"ok": True, "count": len(tracks)})
            elif u.path == "/api/player":
                self._json(player.status())
            elif u.path == "/api/ctl":
                a = q.get("a", "")
                if a not in ("pause", "play", "toggle", "stop", "next", "prev", "seek"):
                    return self._json({"error": "Unbekannte Aktion"}, 400)
                player.control(a, q.get("t"))
                self._json({"ok": True})
            else:
                self.send_error(404)
        except Exception as e:  # Receiver/Plex nicht erreichbar o. Ä.
            self._json({"error": str(e)}, 502)


if __name__ == "__main__":
    print(f"Marantz-Fernbedienung läuft auf Port {PORT}")
    # Nur lokal: von anderen Geräten im Netz ist der Dienst nicht erreichbar
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
