#!/usr/bin/env python3
"""Marantz-Fernbedienung: Hintergrunddienst (nur auf diesem Rechner erreichbar).

- stellt eine kleine JSON-Schnittstelle für die App bereit (127.0.0.1:8080)
- verwaltet die Musik-Wiedergabe vom Medienserver mit Warteschlange
  (läuft weiter, auch wenn die App geschlossen ist)
"""
import json
import sys
import threading
import time
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import i18n
import marantz as m
import upnp

PORT = 8080
GRACE = 5          # s nach Start/Spulen, in denen "gestoppt" noch nicht gilt
STEP = 0.5         # s zwischen zwei Prüfungen beim Laden/Spulen
STOP_WAIT = 8      # s höchstens auf die Stopp-Bestätigung warten
START_WAIT = 10    # s höchstens warten, bis ein Titel läuft
HANG = 10          # s dauerhaftes Umschalten = Receiver hängt
SEEK_WAIT = 8      # s höchstens warten, bis der Receiver spulen kann
RETRY_701 = 1.5    # s Pause, wenn der Receiver einen Befehl ablehnt
QUIET = 10         # s Ruhe, wenn der Receiver nicht antwortet
HERE = Path(__file__).resolve().parent


_logged = {}


def log_error(where, e):
    """Fehler ins Journal; dieselbe Meldung höchstens 1× pro Minute (eMMC schonen)."""
    action = getattr(e, "action", "")
    text = f"Fehler bei {where}{' (' + action + ')' if action else ''}: {type(e).__name__}: {e}"
    if time.time() - _logged.get(text, 0) >= 60:
        if len(_logged) > 100:
            _logged.clear()
        _logged[text] = time.time()
        print(text, file=sys.stderr, flush=True)


def log_info(text):
    """Kurze Zeile ins Journal (Titelstart, Spulen, Ende) – wenige Schreibzugriffe."""
    print(text, file=sys.stderr, flush=True)


class Superseded(Exception):
    """Ein neuerer Wunsch (anderer Titel, Stopp) hat den laufenden Vorgang abgelöst."""


class PlayError(RuntimeError):
    """Verständliche Meldung für die App."""


STOPPED = ("STOPPED", "NO_MEDIA_PRESENT")


class Player:
    """Spielt eine Liste von Titeln nacheinander auf dem Receiver ab.

    Nur der eigene Thread (_run) spricht mit dem Receiver. Befehle aus der App
    merken bloß den Wunsch und kehren sofort zurück; der neueste Wunsch gewinnt.
    """

    def __init__(self):
        self.lock = threading.Condition(threading.RLock())
        self.queue, self.i = [], -1
        self.active = False        # Warteschlange läuft (lädt, spielt oder pausiert)
        self.last = {}             # state / elapsed für die Anzeige
        self.error, self.error_id = "", 0
        self.gen = 0               # zählt Titelwechsel und Stopp (bricht Älteres ab)
        self.want_load = self.want_stop = False
        self.want_ctl = None       # "pause" oder "play"
        self.want_seek = None      # Zielsekunde
        self.quiet_until = 0.0
        self._reset_track()
        threading.Thread(target=self._run, daemon=True).start()

    def _reset_track(self):
        self.peak = 0              # höchste gesehene Position (für "Titel zu Ende")
        self.own_dur = None        # Länge laut Receiver
        self.started = 0.0         # letzter Start / letztes Spulen
        self.hang_since = 0.0
        self.rescued = False       # höchstens ein Rettungsversuch pro Titel

    # ----- Wünsche (aus den HTTP-Anfragen, ohne Netzzugriff) -----
    def start(self, tracks, index):
        with self.lock:
            self.queue, self.i = tracks, index
            self._request_load()

    def _request_load(self, position=None, rescue=False):
        """Aktuellen Titel (neu) laden. Aufrufer hält self.lock."""
        self.gen += 1
        self._reset_track()
        self.rescued = rescue
        self.want_load, self.want_stop = True, False
        self.want_ctl, self.want_seek = None, position
        self.active, self.error, self.quiet_until = True, "", 0.0
        self.last = {"state": "TRANSITIONING", "elapsed": position or 0}
        self.lock.notify_all()

    def control(self, action, t=None):
        with self.lock:
            if not self.queue:
                return
            if action == "toggle":
                action = "pause" if self.active and self.last.get("state") == "PLAYING" else "play"
            if action == "stop":
                self.gen += 1
                self.want_load, self.want_ctl, self.want_seek = False, None, None
                self.want_stop, self.active = True, False
            elif action == "play" and not self.active:
                self._request_load()
            elif action in ("play", "pause"):
                self.want_ctl = action
                if not self.want_load:
                    self.last = dict(self.last, state="PLAYING" if action == "play"
                                     else "PAUSED_PLAYBACK")
            elif action == "next" and self.i + 1 < len(self.queue):
                self.i += 1
                self._request_load()
            elif action == "prev":
                if (self.last.get("elapsed") or 0) > 5 or self.i == 0:
                    self._request_seek(0)
                else:
                    self.i -= 1
                    self._request_load()
            elif action == "seek" and t is not None:
                self._request_seek(int(float(t)))
            self.lock.notify_all()

    def _request_seek(self, t):
        dur = self.queue[self.i].get("duration")
        if dur:
            t = min(t, int(dur) - 5)        # nicht ganz ans Titelende
        t = max(0, t)
        if not self.active:                 # gestoppt: Titel laden, dann spulen
            self._request_load(position=t)
        else:
            self.want_seek, self.error = t, ""
            self.last = dict(self.last, elapsed=t)

    # ----- Arbeits-Thread -----
    def _run(self):
        while True:
            try:
                self._step()
            except Superseded:
                pass
            except OSError as e:            # keine Antwort: nichts weiter senden
                log_error("Receiver antwortet nicht, sende nichts weiter", e)
                self.quiet_until = time.time() + QUIET
                self._fail("Receiver antwortet nicht")
            except PlayError as e:
                self._fail(str(e))
            except Exception as e:  # noqa: BLE001  (Thread darf nie abstürzen)
                log_error("Wiedergabe", e)
                self._fail(str(e), stop=False)

    def _step(self):
        with self.lock:
            if not (self.want_load or self.want_stop or self.want_ctl
                    or self.want_seek is not None):
                self.lock.wait(self._interval())
            gen = self.gen
            job = ("stop" if self.want_stop else "load" if self.want_load else
                   "ctl" if self.want_ctl else
                   "seek" if self.want_seek is not None else "poll")
            if job == "stop":
                self.want_stop = False
            elif job == "load":
                self.want_load = False
            elif job == "ctl":
                action, self.want_ctl = self.want_ctl, None
        if job == "stop":
            self._ensure_stopped(gen)
        elif job == "load":
            self._load(gen)
        elif job == "ctl":
            upnp.pause() if action == "pause" else upnp.play()
        elif job == "seek":
            self._seek(gen)
        elif self.active and time.time() >= self.quiet_until:
            self._poll(gen)

    def _interval(self):
        if not self.active:
            return 3
        dur = self.queue[self.i].get("duration") if 0 <= self.i < len(self.queue) else None
        near_end = dur and (self.last.get("elapsed") or 0) >= dur - 15
        if time.time() - self.started < GRACE:
            return 1
        if self.last.get("state") == "PAUSED_PLAYBACK":
            return 5            # Befehle aus der App wecken den Thread trotzdem sofort
        return 1 if near_end else 2

    def _check(self, gen):
        if gen != self.gen:
            raise Superseded

    def _fail(self, text, stop=True):
        """Fehler an die App melden; die Warteschlange bleibt erhalten."""
        with self.lock:
            self.error, self.error_id = text, self.error_id + 1
            self.want_ctl, self.want_seek = None, None
            if stop:
                self.active, self.want_load = False, False
                log_info(f"Wiedergabe angehalten: {text} (Titel {self.i + 1}/{len(self.queue)})")
            else:
                log_info(f"Meldung: {text}")

    def _wait(self, gen, seconds):
        with self.lock:
            self.lock.wait_for(lambda: gen != self.gen, seconds)
        self._check(gen)

    def _ensure_stopped(self, gen):
        """Bei Bedarf einmal stoppen und warten, bis der Receiver es bestätigt."""
        state = upnp.transport_state()
        if state in STOPPED:
            return True
        self._check(gen)
        try:
            upnp.stop()
        except RuntimeError as e:
            log_error("Stoppen", e)
        end = time.time() + STOP_WAIT
        while time.time() < end:
            state = upnp.transport_state()
            if state in STOPPED:
                return True
            self._wait(gen, STEP)
        log_info(f"Stopp nicht bestätigt (Zustand {state})")
        return False

    def _load(self, gen):
        """Der eine Weg für jeden Titelwechsel: stoppen, übergeben, abspielen, prüfen."""
        with self.lock:
            self._check(gen)
            t, nr = self.queue[self.i], f"{self.i + 1}/{len(self.queue)}"
        for attempt in (1, 2):
            begin = time.time()
            try:
                if not self._ensure_stopped(gen):
                    continue
                self._check(gen)
                upnp.set_uri(t["uri"], t["didl"])
                self._check(gen)
                upnp.play()
                if self._wait_running(gen, t):
                    log_info(f"Titel {nr} läuft nach {time.time() - begin:.1f} s (Versuch {attempt})")
                    self._set_next(gen)
                    return
                log_info(f"Titel {nr} läuft nicht an (Versuch {attempt})")
            except RuntimeError as e:
                log_error(f"Titelstart (Versuch {attempt})", e)
                self._wait(gen, RETRY_701)
        try:
            self._ensure_stopped(gen)       # Receiver nicht hängen lassen
        except RuntimeError as e:
            log_error("Stoppen", e)
        self._check(gen)
        raise PlayError("Titel lässt sich nicht starten")

    def _wait_running(self, gen, track):
        end = time.time() + START_WAIT
        while time.time() < end:
            self._wait(gen, STEP)
            s = upnp.state()
            if s["state"] == "PLAYING" and s["uri"] in ("", track["uri"]) and s["elapsed"]:
                with self.lock:
                    self._check(gen)
                    self.started = time.time()
                    self._remember(s)
                return True
        return False

    def _set_next(self, gen):
        with self.lock:
            self._check(gen)
            n = self.queue[self.i + 1] if self.i + 1 < len(self.queue) else None
        if n:
            try:
                upnp.set_next(n["uri"], n["didl"])  # lückenloser Übergang
            except RuntimeError as e:
                log_error("nächstem Titel vormerken", e)

    def _seek(self, gen):
        begin = time.time()
        end = begin + SEEK_WAIT
        refused = 0
        while True:
            s = upnp.state()
            self._check(gen)
            if s["state"] in ("PLAYING", "PAUSED_PLAYBACK"):
                with self.lock:
                    t = self.want_seek              # immer das neueste Ziel
                if t is None:
                    return
                if s["duration"]:                   # Receiver schätzt die Länge selbst
                    t_send = max(0, min(t, s["duration"] - 5))
                else:
                    t_send = t
                try:
                    upnp.seek(t_send)
                    break
                except RuntimeError as e:
                    log_error(f"Spulen (Zustand {s['state']}, Ziel {t_send} s)", e)
                    if "711" in str(e):
                        return self._fail("Diese Stelle kann nicht angesprungen werden", False)
                    if "701" not in str(e):
                        raise
                    refused += 1
                    if refused > 1:
                        return self._fail("Receiver ist nicht bereit zum Spulen", False)
                    self._wait(gen, RETRY_701)
            elif time.time() >= end:
                return self._fail("Receiver ist nicht bereit zum Spulen", False)
            else:
                self._wait(gen, STEP)
        with self.lock:
            self._check(gen)
            if self.want_seek == t:                 # sonst folgt gleich das neuere Ziel
                self.want_seek = None
            self.started, self.peak, self.hang_since = time.time(), t_send, 0.0
            self.last = {"state": s["state"], "elapsed": t_send}
        log_info(f"Gespult zu {t_send} s (Dauer {time.time() - begin:.1f} s)")

    def _remember(self, s):
        if s["state"] == "PLAYING":
            self.peak = max(self.peak, s["elapsed"] or 0)
            self.own_dur = s["duration"] or self.own_dur
        elapsed = s["elapsed"]
        if s["state"] == "TRANSITIONING":           # Position ist dabei unzuverlässig
            elapsed = self.last.get("elapsed")
        if self.want_seek is not None:
            elapsed = self.want_seek
        self.last = {"state": s["state"], "elapsed": elapsed}

    def _poll(self, gen):
        s = upnp.state()
        next_track = False
        with self.lock:
            self._check(gen)
            now, state, uri = time.time(), s["state"], s["uri"]
            cur = self.queue[self.i]
            n = self.queue[self.i + 1] if self.i + 1 < len(self.queue) else None
            if n and uri == n["uri"] and state not in STOPPED:
                self.i += 1                         # Receiver ist lückenlos weitergegangen
                self._reset_track()
                self.started = now
                log_info(f"Titel {self.i + 1}/{len(self.queue)} (lückenlos)")
                self._remember(s)
                next_track = True
            elif uri and uri != cur["uri"]:
                if now - self.started > GRACE:
                    self._end("anderer Titel am Receiver", s)
            elif state == "TRANSITIONING":
                self.hang_since = self.hang_since or now
                if now - self.hang_since >= HANG:
                    if self.rescued:
                        raise PlayError("Titel lässt sich nicht starten")
                    log_info(f"Receiver hängt bei {self.peak} s, lade Titel neu")
                    return self._request_load(self.peak if self.peak > 5 else None, rescue=True)
                self._remember(s)
            elif state in STOPPED:
                if now - self.started <= GRACE:
                    return
                durs = [d for d in (cur.get("duration"), self.own_dur) if d]
                if durs and self.peak >= min(durs) - 8:     # Titel war zu Ende
                    if n:
                        self.i += 1
                        self._request_load()
                    else:
                        self._end("Ende der Liste", s)
                else:       # z. B. Eingang gewechselt – dann NICHT zurückholen
                    self._end("am Receiver gestoppt", s)
            else:
                self.hang_since = 0.0
                self._remember(s)
        if next_track:
            self._set_next(gen)

    def _end(self, reason, s):
        self.active = False
        log_info(f"Wiedergabe beendet: {reason} (Titel {self.i + 1}/{len(self.queue)}, Zustand "
                 f"{s['state']}, bis {self.peak} s, Länge Plex "
                 f"{self.queue[self.i].get('duration')} s, Receiver {self.own_dur} s)")

    def _probe(self, track):
        """Eigener kurzer Thread: genaue Angaben aus der Datei lesen (bremst nichts)."""
        try:
            info = upnp.file_info(track["uri"], track.get("format", ""), track.get("kbps") or 0,
                                  track.get("size") or 0, track.get("duration") or 0)
        except Exception as e:  # noqa: BLE001  (dann bleiben die Angaben des Servers)
            log_error("Dateiangaben lesen", e)
            return
        with self.lock:
            track.update(info)

    def status(self):
        with self.lock:             # wird nie während eines Netzzugriffs gehalten
            t = self.queue[self.i] if 0 <= self.i < len(self.queue) else None
            if t and not t.get("probed"):       # nur der laufende Titel, je einmal
                t["probed"] = True
                threading.Thread(target=self._probe, args=(t,), daemon=True).start()
            st = self.last.get("state", "") if self.active else "STOPPED"
            # Länge aus Plex (genau); der Receiver schätzt sie bei manchen MP3s falsch
            dur = (t or {}).get("duration") or self.own_dur
            el = self.last.get("elapsed") if self.active else 0
            return {
                "active": self.active, "state": st,
                "id": t and t["id"], "title": t and t["title"], "artist": t and t.get("artist"),
                "album": t and t.get("album"), "art": t and t.get("art"),
                "format": t and t.get("format"), "kbps": t and t.get("kbps"),
                "rate": t and t.get("rate"), "bits": t and t.get("bits"),
                "avg": t and t.get("avg"),
                "elapsed": min(el or 0, dur) if dur else el, "duration": dur,
                "index": self.i + 1, "count": len(self.queue),
                "error": self.error, "error_id": self.error_id,
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
                        for a in upnp.browse_all(folder["id"], 20000) if a["kind"] == "folder"]
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


PLAY_MAX = 2000     # höchstens so viele Einträge in die Warteschlange (Speicher)
PLAY_BEFORE = 200   # davon liegen bei sehr großen Ordnern so viele vor dem angetippten Titel


def folder_tracks(parent, item=None, pos=0):
    """Titel eines Ordners und Nummer des gewünschten. pos = Zeile in der Liste der App;
    bei sehr großen Ordnern beginnt die Warteschlange kurz davor."""
    start = pos - PLAY_BEFORE if pos >= PLAY_MAX - PLAY_BEFORE else 0
    tracks = [i for i in upnp.browse_all(parent, PLAY_MAX, start) if i["kind"] == "track"]
    if item is None:
        return tracks, 0
    idx = next((n for n, t in enumerate(tracks) if t["id"] == item), None)
    if idx is None and tracks:          # nie stillschweigend einen anderen Titel abspielen
        raise LookupError("Titel nicht gefunden")
    return tracks, idx or 0


def public(item):
    """Für die Oberfläche: ohne lange Interna (Adresse, DIDL)."""
    return {k: v for k, v in item.items() if k not in ("didl", "uri")}


class Handler(BaseHTTPRequestHandler):
    timeout = 10        # s; stumme Verbindungen nicht ewig offen halten

    def log_message(self, *args):  # keine Logs → schont den eMMC-Speicher
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass                            # App wurde inzwischen geschlossen

    def _foreign_request(self):
        """True, wenn die Anfrage nicht von der App oder dem Startbildschirm stammt.

        Beide schicken den eigenen Kopf X-Marantz. Webseiten dürfen ihn nicht setzen, und auch
        Adressen aus dem Heimnetz (Cover, Plex-Suche, Weiterleitungen) tragen ihn nicht.
        Die Host-Prüfung hält Seiten ab, die ihren Namen auf 127.0.0.1 umbiegen."""
        port = self.server.server_port
        return (self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}")
                or self.headers.get("X-Marantz") != "1"
                or self.headers.get("Origin") is not None
                or self.headers.get("Sec-Fetch-Site") is not None)

    def do_GET(self):
        if self._foreign_request():
            return self._json({"error": "Zugriff nicht erlaubt"}, 403)
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
                count = max(1, min(200, int(q.get("count", 200))))     # 0 hieße „alles“
                r = upnp.browse(q.get("id", "0"), int(q.get("start", 0)), count)
                self._json({"items": [public(i) for i in r["items"]], "total": r["total"],
                            "open": r["open"]})
            elif u.path == "/api/servers":                  # Medienserver zur Auswahl
                found = upnp.servers()
                self._json({"items": found, "total": len(found), "open": False})
            elif u.path == "/api/server":
                try:
                    upnp.select_server(q.get("id", ""))
                except LookupError as e:
                    return self._json({"error": str(e), "source": "plex"}, 404)
                _artists.update(t=0.0, list=[])             # gehörte zum alten Server
                self._json({"ok": True})
            elif u.path == "/api/play":
                try:
                    tracks, idx = folder_tracks(q["parent"], q.get("item"),
                                                max(0, int(q.get("pos", 0))))
                except LookupError as e:
                    return self._json({"error": str(e), "source": "plex"}, 404)
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
            log_error(u.path, e)
            receiver = u.path in ("/api/status", "/api/group", "/api/settings",
                                  "/api/cmd", "/api/vol", "/api/scene")
            source = getattr(e, "source", "receiver" if receiver and isinstance(e, OSError)
                             else "dienst")
            text = str(e)
            if source == "receiver" and isinstance(e, OSError):
                text = "Receiver antwortet nicht"
            self._json({"error": text, "source": source}, 502)


if __name__ == "__main__":
    print(f"Marantz-Fernbedienung läuft auf Port {PORT}")
    # Nur lokal: von anderen Geräten im Netz ist der Dienst nicht erreichbar
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
