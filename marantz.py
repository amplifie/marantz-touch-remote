"""Gemeinsamer Baustein: spricht mit dem Marantz SR7010.

Befehle gehen per HTTP raus (formiPhoneAppDirect = gleiche Befehle wie Telnet).
Den Grundzustand liefert eine XML-Seite des Receivers; Audyssey- und
Kanalpegel-Werte gibt es nur über Telnet (Port 23) – dort wird kurz
verbunden, abgefragt und wieder getrennt.
"""
import html
import os
import re
import socket
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

RECEIVER = ""   # wird automatisch im Heimnetz gesucht und in ~/.config/marantz/receiver gemerkt
MARANTZ_MAC_PREFIX = "00:06:78"   # Hersteller-Kennung (D&M Holdings = Marantz/Denon)
SAVE_FILE = os.path.expanduser("~/.config/marantz/receiver")
SEARCH_PAUSE = 20  # höchstens alle 20 s neu suchen
MAX_VOL = 90  # Obergrenze Hauptlautstärke (Anzeige-Skala 0–98)
LOUD = 80     # ab hier "sehr laut": sanfter Stopp + Hinweis

# Pegel-Skala des Receivers: 50 = 0 dB, 38 = −12 dB, 62 = +12 dB
LEVEL_MIN, LEVEL_MAX = 38.0, 62.0

CHANNELS = [  # (Code, Anzeigename)
    ("FL", "Front links"), ("FR", "Front rechts"), ("C", "Center"),
    ("SW", "Subwoofer"), ("SL", "Surround links"), ("SR", "Surround rechts"),
    ("FHL", "Höhe vorne links"), ("FHR", "Höhe vorne rechts"),
    ("RHL", "Höhe hinten links"), ("RHR", "Höhe hinten rechts"),
]

INPUTS = [("SITV", "TV Audio"), ("SIGAME", "Game"), ("SISERVER", "Mediaserver")]

MODES = [("MSDOLBY DIGITAL", "Dolby / Atmos", "dolby"), ("MSSTEREO", "Stereo", "stereo"),
         ("MSDIRECT", "Direct", "direct"), ("MSPURE DIRECT", "Pure Direct", "pure"),
         ("MSAUTO", "Auto", "auto")]

# Szenen: Liste von (Befehl, Wartezeit danach in Sekunden)
SCENES = {
    "film": [("ZMON", 0), ("SITV", 1.5), ("MSDOLBY DIGITAL", 1.0), ("MV55", 0)],
    "musik": [("ZMON", 0), ("SISERVER", 1.5), ("MSDIRECT", 1.0), ("MV40", 0)],
    "aus": [("ZMOFF", 0)],
}

_CH = "|".join(c for c, _ in CHANNELS)
ALLOWED = re.compile(
    r"^(ZMON|ZMOFF|PWON|PWSTANDBY|MUON|MUOFF|MVUP|MVDOWN|MV\d{2,3}|"
    r"SI(TV|GAME|SERVER|BD|DVD|BT|IRADIO|USB/IPOD|SAT/CBL|MPLAY|AUX1|AUX2|CD|PHONO|TUNER|FAVORITES|NET)|"
    r"MS(STEREO|AUTO|DIRECT|PURE DIRECT|DOLBY DIGITAL|MOVIE|MUSIC|GAME)|"
    r"PSMULTEQ:(AUDYSSEY|BYP\.LR|FLAT|OFF)|PSDYNEQ (ON|OFF)|PSREFLEV (0|5|10|15)|"
    r"PSDYNVOL (OFF|LIT|MED|HEV)|PSCINEMA EQ\.(ON|OFF)|"
    r"PSSWL (ON|OFF|UP|DOWN|\d{2,3})|"
    r"PSTONE CTRL (ON|OFF)|PSBAS (UP|DOWN|4[4-9]|5[0-6])|PSTRE (UP|DOWN|4[4-9]|5[0-6])|PSGEQ (ON|OFF)|"
    r"CV(" + _CH + r") (UP|DOWN|\d{2,3})|"
    r"NS9[0-4A-EXY]|"
    r"MNMEN (ON|OFF)|MNCUP|MNCDN|MNCLT|MNCRT|MNENT|MNRTN|MNOPT|MNINF)$")  # Setup-Menü am TV  # Netzwerk-Menü: Cursor, Enter, Seiten, Wiedergabe

_status_lock = threading.Lock()
_telnet_lock = threading.Lock()
_cache = {"t": 0.0, "data": None}
_search_lock = threading.Lock()
_last_search = 0.0

try:  # zuletzt gefundene Adresse merken
    with open(SAVE_FILE) as f:
        _saved = f.read().strip()
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", _saved):
        RECEIVER = _saved
except OSError:
    pass


# ---------- Receiver im Netz finden ----------
def _is_marantz(ip: str) -> bool:
    try:
        raw = urllib.request.urlopen(
            f"http://{ip}/goform/formMainZone_MainZoneXml.xml", timeout=2).read()
        return b"MARANTZ" in raw.upper()
    except Exception:  # noqa: BLE001
        return False


def _ssdp_candidates() -> list:
    """Geräte im Netz fragen, wer UPnP spricht (der Receiver antwortet darauf)."""
    found = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(0.5)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        msg = ('M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n'
               'MAN: "ssdp:discover"\r\nMX: 2\r\nST: upnp:rootdevice\r\n\r\n').encode()
        for _ in range(2):
            s.sendto(msg, ("239.255.255.250", 1900))
        end = time.time() + 3
        while time.time() < end:
            try:
                data, addr = s.recvfrom(4096)
            except socket.timeout:
                continue
            if addr[0] in found:
                continue
            # Marantz/Denon-Geräte zuerst prüfen
            if b"KnOS" in data or b"marantz" in data.lower():
                found.insert(0, addr[0])
            else:
                found.append(addr[0])
    finally:
        s.close()
    return found


def _arp_candidates() -> list:
    """Geräte mit Marantz-Hersteller-Kennung aus der Nachbarschaftstabelle."""
    out = []
    try:
        with open("/proc/net/arp") as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if len(parts) >= 4 and parts[3].lower().startswith(MARANTZ_MAC_PREFIX):
                    out.append(parts[0])
    except OSError:
        pass
    return out


def find_receiver() -> bool:
    """Receiver neu suchen. True, wenn er (evtl. unter neuer Adresse) gefunden wurde."""
    global RECEIVER, _last_search
    with _search_lock:
        if time.time() - _last_search < SEARCH_PAUSE:
            return False
        _last_search = time.time()
        candidates = _arp_candidates() + _ssdp_candidates()
        for ip in dict.fromkeys(candidates):  # Reihenfolge behalten, doppelte weg
            if _is_marantz(ip):
                if ip != RECEIVER:
                    RECEIVER = ip
                    try:
                        os.makedirs(os.path.dirname(SAVE_FILE), exist_ok=True)
                        with open(SAVE_FILE, "w") as f:
                            f.write(ip + "\n")
                    except OSError:
                        pass
                    return True
                return False  # gleiche Adresse – Receiver war nur kurz weg
        return False


def _ensure_receiver() -> None:
    if not RECEIVER:
        find_receiver()
        if not RECEIVER:
            raise OSError("Marantz-Receiver im Netz nicht gefunden")


def _get(path: str, timeout: float = 4) -> bytes:
    """HTTP-Abruf beim Receiver; ist er nicht erreichbar, wird er einmal gesucht."""
    _ensure_receiver()
    try:
        return urllib.request.urlopen(f"http://{RECEIVER}{path}", timeout=timeout).read()
    except OSError:
        if find_receiver():
            return urllib.request.urlopen(f"http://{RECEIVER}{path}", timeout=timeout).read()
        raise


# ---------- Hilfen für die Pegel-Skala ----------
def parse_level(s: str) -> float:
    """'50' → 50.0, '435' → 43.5"""
    return int(s) / 10 if len(s) == 3 else float(int(s))


def fmt_level(v: float) -> str:
    """50.0 → '50', 43.5 → '435'"""
    v = max(LEVEL_MIN, min(LEVEL_MAX, round(v * 2) / 2))
    return "%02d" % v if v == int(v) else "%03d" % round(v * 10)


def level_db(v: float) -> str:
    """Anzeige als dB-Text, z. B. 43.5 → '−6,5 dB'"""
    d = v - 50
    txt = ("%+.1f" % d).replace(".", ",").replace("-", "−")
    return "0 dB" if d == 0 else txt.replace(",0", "") + " dB"


# ---------- Befehle ----------
def send(cmd: str) -> None:
    if not ALLOWED.match(cmd):
        raise ValueError("Befehl nicht erlaubt: " + cmd)
    if cmd.startswith("MV") and cmd[2:].isdigit():
        cmd = "MV%02d" % min(int(cmd[2:]), MAX_VOL)
    _get("/goform/formiPhoneAppDirect.xml?" + urllib.parse.quote(cmd))
    _cache["t"] = 0  # Status beim nächsten Abruf frisch holen


def change_volume(delta: int) -> int:
    """Lautstärke ändern. Sanfter Stopp bei LOUD: über 80 nur, wenn man schon bei 80 ist."""
    cur = int(round(status()["volume"] or 0))
    new = max(0, min(MAX_VOL, cur + delta))
    if cur < LOUD < new:
        new = LOUD
    send("MV%02d" % new)
    return new


def run_scene(name: str) -> None:
    steps = SCENES[name]
    was_off = not status()["power"]
    for i, (cmd, wait) in enumerate(steps):
        send(cmd)
        if i == 0 and was_off and cmd == "ZMON":
            time.sleep(4)  # Receiver braucht nach dem Einschalten etwas
        time.sleep(wait)


# ---------- Mediaserver-Menü (Netzwerk-Quellen) ----------
# NS90 hoch · NS91 runter · NS92 zurück · NS93 rechts · NS94 Enter
# NS9X Seite vor · NS9Y Seite zurück · NS9A Play · NS9B Pause · NS9C Stop · NS9D Weiter · NS9E Zurück
def net_status() -> dict:
    """Was der Receiver gerade im Netzwerk-Menü anzeigt (Titel, 7 Zeilen, Cursor, Position)."""
    root = ET.fromstring(_get("/goform/formNetAudio_StatusXml.xml"))
    lines = [html.unescape((v.text or "").strip()) for v in root.findall("szLine/value")]
    flags = [(v.text or "0").strip() for v in root.findall("chFlag/value")]
    lines += [""] * (10 - len(lines))
    cursor = next((i for i in range(1, 8) if i < len(flags) and flags[i] == "8"), None)
    pos = re.search(r"\[\s*(\d+)\s*/\s*(\d+)\s*\]", lines[8])
    return {
        "title": lines[0],
        "items": lines[1:8],
        "cursor": cursor,                     # 1–7 oder None (z. B. Wiedergabe-Anzeige)
        "pos": int(pos.group(1)) if pos else None,
        "total": int(pos.group(2)) if pos else None,
        "extra": lines[8] if not pos else "",
    }


def net_select(row: int) -> None:
    """Zeile 1–7 antippen: Cursor dorthin bewegen und öffnen/abspielen."""
    st = net_status()
    cur = st["cursor"]
    if cur is None or not st["items"][row - 1]:
        return
    step = "NS91" if row > cur else "NS90"
    for _ in range(abs(row - cur)):
        send(step)
        time.sleep(0.25)
    time.sleep(0.2)
    send("NS94")
    # Wurde ein Titel gewählt, startet der Receiver manchmal nur pausiert.
    # Dann prüfen, ob die Zeit läuft – wenn nicht, Play senden.
    time.sleep(2.5)
    if net_status()["title"] == "Now Playing":
        a = now_playing().get("elapsed")
        time.sleep(1.5)
        b = now_playing().get("elapsed")
        if a is not None and a == b:
            send("NS9A")


# ---------- Grafik-EQ (über die Einstellungs-Webseite des Receivers) ----------
# Getestet 2026-11-26: Gruppe umschalten (Übernehmen = aus) ändert nichts, Übernehmen = "Set" setzt Werte.
GEQ_PAGE = "/SETUP/AUDIO/GRAPHICEQ"
GEQ_BANDS = ["63", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"]
GEQ_MIN, GEQ_MAX = -20.0, 6.0
_geq_lock = threading.Lock()


def _geq_page() -> dict:
    t = _get(GEQ_PAGE + "/d_audio.asp", timeout=8).decode("utf-8", "ignore")
    grp = re.search(r"name='listGEQAdjustEQ'(.*?)</select>", t, re.S | re.I).group(1)
    groups = re.findall(r"value='(\w+)'[^>]*>([^<]+)<", grp)
    sel = re.search(r"value='(\w+)' selected", grp).group(1)
    sp = re.search(r"name='listGEQSpSelection'.*?value='(\w+)' selected", t, re.S).group(1)
    on = re.search(r"name='radioGraphicEQ' value='(\w+)'[^>]*checked", t).group(1)
    vals = dict(re.findall(r"name='textGEQ(\w+)' value='([-0-9.]+)'", t))
    hidden = dict(re.findall(r"name='(set(?:PureDirectOn|SetupLock))' value='(\w+)'", t))
    return {"group": sel, "groups": groups, "sp": sp, "on": on == "ON",
            "vals": {b: float(vals[b]) for b in GEQ_BANDS}, "hidden": hidden}


def _geq_post(st: dict, group: str, vals: dict, apply: bool) -> None:
    form = {"setPureDirectOn": st["hidden"].get("setPureDirectOn", "OFF"),
            "setSetupLock": st["hidden"].get("setSetupLock", "OFF"),
            "radioGraphicEQ": "ON" if st["on"] else "OFF", "listGEQSpSelection": st["sp"],
            "listGEQAdjustEQ": group,
            **{f"textGEQ{b}": "%.1f" % max(GEQ_MIN, min(GEQ_MAX, round(vals[b] * 2) / 2))
               for b in GEQ_BANDS},
            "setAdjustEQ": "Set" if apply else "off", "setGEQCurveCopy": "off",
            "setGEQSetDefaults": "off"}
    data = urllib.parse.urlencode(form).encode()
    urllib.request.urlopen(f"http://{RECEIVER}{GEQ_PAGE}/s_audio.asp", data=data, timeout=8).read()
    time.sleep(0.8)


def geq_read(group: str = None) -> dict:
    """Werte einer Lautsprecher-Gruppe lesen (FRO, CEN, SUR, FRH, RHE)."""
    if group and group not in GEQ_GROUPS:
        raise ValueError("Ungültige EQ-Gruppe")
    with _geq_lock:
        st = _geq_page()
        if group and group != st["group"]:
            _geq_post(st, group, st["vals"], apply=False)   # nur Auswahl umschalten
            st = _geq_page()
        st.pop("hidden", None)
        return st


GEQ_GROUPS = ("FRO", "CEN", "SUR", "FRH", "RHE")


def geq_set(group: str, vals: dict) -> dict:
    """9 Bänder einer Gruppe setzen (dB, −20…+6, 0,5er-Schritte)."""
    if group not in GEQ_GROUPS or set(vals) != set(GEQ_BANDS):
        raise ValueError("Ungültige EQ-Gruppe oder Bänder")
    with _geq_lock:
        st = _geq_page()
        if group != st["group"]:
            _geq_post(st, group, st["vals"], apply=False)
            st = _geq_page()
        _geq_post(st, group, vals, apply=True)
        st = _geq_page()
        st.pop("hidden", None)
        return st


# ---------- Alle Eingänge ----------
# Feste deutsche Namen für Quellen ohne eigenen Namen im Receiver
SOURCE_NAMES = {"TV": "TV Audio", "BD": "Blu-ray", "DVD": "DVD", "SAT/CBL": "CBL/SAT",
                "MPLAY": "Media Player", "GAME": "Game", "AUX1": "AUX1", "AUX2": "AUX2", "CD": "CD",
                "PHONO": "Phono", "TUNER": "Tuner", "BT": "Bluetooth", "USB/IPOD": "USB / iPod",
                "IRADIO": "Internetradio", "FAVORITES": "Favoriten", "SERVER": "Mediaserver"}
SOURCE_ORDER = ["TV", "BD", "DVD", "SAT/CBL", "MPLAY", "GAME", "SERVER", "IRADIO", "FAVORITES",
                "BT", "USB/IPOD", "TUNER", "CD", "PHONO", "AUX1", "AUX2"]
_sources = {"t": 0.0, "list": None}


def sources() -> list:
    """Alle benutzten Eingänge als [(Befehl, Name)] – Namen so, wie sie im Receiver heißen."""
    if _sources["list"] and time.time() - _sources["t"] < 600:
        return _sources["list"]
    raw = _telnet(["SSFUN ?", "SSSOD ?"], b"SSSODSERVER", wait=3)
    names, used = {}, set()
    for line in raw.split("\r"):
        line = line.strip()
        if line.startswith("SSFUN"):
            code, _, name = line[5:].partition(" ")
            if name.strip():
                names[code] = name.strip()
        elif line.startswith("SSSOD") and line.endswith(" USE"):
            used.add(line[5:-4])
    if not used:
        used = set(SOURCE_ORDER)
    out = [("SI" + c, names.get(c, SOURCE_NAMES.get(c, c))) for c in SOURCE_ORDER if c in used]
    _sources.update(t=time.time(), list=out)
    return out


# ---------- Jetzt läuft ----------
def _telnet(queries: list, until: bytes, wait: float = 2.5) -> str:
    """Kurz per Telnet verbinden, Fragen stellen, Antworten sammeln."""
    _ensure_receiver()
    with _telnet_lock:
        s = socket.create_connection((RECEIVER, 23), timeout=3)
        buf = b""
        try:
            for q in queries:
                s.sendall(q.encode() + b"\r")
                time.sleep(0.1)
            s.settimeout(0.4)
            end = time.time() + wait
            while time.time() < end:
                try:
                    d = s.recv(4096)
                except socket.timeout:
                    if until in buf:
                        break
                    continue
                if not d:
                    break
                buf += d
        finally:
            s.close()
    return buf.decode("utf-8", errors="ignore")


def _secs(t: str):
    parts = [int(x) for x in t.split(":")]
    v = 0
    for p_ in parts:
        v = v * 60 + p_
    return v


def now_playing() -> dict:
    """Abspielzeit, Tonformat und Titelnummer (über Telnet, Bildschirm-Zeilen NSE)."""
    raw = _telnet(["NSE"], b"NSE8")
    out = {"elapsed": None, "quality": "", "track": None, "tracks": None}
    for line in raw.split("\r"):
        if not line.startswith("NSE") or len(line) < 4:
            continue
        n, text = line[3], line[4:].lstrip("\x00\x01\x02\x03\x08").strip()
        if n == "3" and re.search(r"\d+(\.\d+)?\s*kHz", text):
            out["quality"] = text
        elif n == "5":
            m_ = re.search(r"(\d+:\d{2}(?::\d{2})?)", text)
            if m_:
                out["elapsed"] = _secs(m_.group(1))
        elif n == "8":
            m_ = re.search(r"\[\s*(\d+)\s*/\s*(\d+)\s*\]", text)
            if m_:
                out["track"], out["tracks"] = int(m_.group(1)), int(m_.group(2))
    return out


def track_duration():
    """Länge des aktuellen Titels in Sekunden (über UPnP), sonst None."""
    body = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            '<u:GetPositionInfo xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">'
            '<InstanceID>0</InstanceID></u:GetPositionInfo></s:Body></s:Envelope>').encode()
    req = urllib.request.Request(
        f"http://{RECEIVER}:8080/AVTransport/ctrl", data=body,
        headers={"Content-Type": 'text/xml; charset="utf-8"',
                 "SOAPACTION": '"urn:schemas-upnp-org:service:AVTransport:1#GetPositionInfo"'})
    raw = urllib.request.urlopen(req, timeout=3).read().decode("utf-8", "ignore")
    m_ = re.search(r"<TrackDuration>(\d+:\d{2}:\d{2})</TrackDuration>", raw)
    if not m_:
        return None
    d = _secs(m_.group(1))
    return d or None


def cover_art() -> bytes:
    """Albumcover als JPEG (leer, wenn keins da ist)."""
    try:
        return _get("/NetAudio/art.asp-jpg?%d" % int(time.time()), timeout=4)
    except Exception:  # noqa: BLE001
        return b""


# ---------- Zustand lesen ----------
def status() -> dict:
    """Grundzustand (höchstens 1× pro Sekunde wirklich beim Receiver)."""
    with _status_lock:
        if _cache["data"] and time.time() - _cache["t"] < 1.0:
            return _cache["data"]
        raw = _get("/goform/formMainZone_MainZoneXml.xml")
        root = ET.fromstring(raw)

        def val(tag):
            el = root.find(f"{tag}/value")
            return (el.text or "").strip() if el is not None else ""

        try:
            vol = round(float(val("MasterVolume")) + 80, 1)  # relativ → Anzeige-Skala
        except ValueError:
            vol = None
        inp = val("InputFuncSelect")
        # Beim Mediaserver meldet der Receiver "Online Music" und nur im Feld
        # NetFuncSelect "SERVER" – daraus machen wir einen klaren Namen.
        if val("NetFuncSelect").upper() == "SERVER" and inp.lower().replace(" ", "") in (
                "onlinemusic", "network", "net", "mediaserver", "server"):
            inp = "Mediaserver"
        data = {
            "power": val("ZonePower") == "ON",
            "input": inp,
            "surround": val("selectSurround"),
            "volume": vol,
            "mute": val("Mute").lower() == "on",
        }
        _cache.update(t=time.time(), data=data)
        return data


def mode_key(surround: str) -> str:
    s = (surround or "").lower()
    if "pure" in s: return "pure"
    if "direct" in s: return "direct"
    if "dolby" in s or "atmos" in s: return "dolby"
    if "stereo" in s: return "stereo"
    if "auto" in s: return "auto"
    return ""


def settings() -> dict:
    """Audyssey- und Pegel-Werte über Telnet abfragen."""
    queries = ["PSMULTEQ: ?", "PSDYNEQ ?", "PSREFLEV ?", "PSDYNVOL ?",
               "PSCINEMA EQ. ?", "PSSWL ?", "PSTONE CTRL ?", "PSBAS ?", "PSTRE ?", "PSGEQ ?", "CV?"]
    _ensure_receiver()
    with _telnet_lock:
        for attempt in range(2):
            try:
                s = socket.create_connection((RECEIVER, 23), timeout=3)
                break
            except OSError:
                if attempt:
                    raise
                if not find_receiver():
                    time.sleep(1)  # Telnet erlaubt nur eine Verbindung – kurz warten
        buf = b""
        try:
            for q in queries:
                s.sendall(q.encode() + b"\r")
                time.sleep(0.15)
            s.settimeout(0.6)
            end = time.time() + 3
            while time.time() < end:
                try:
                    d = s.recv(4096)
                except socket.timeout:
                    if b"CVEND" in buf:
                        break
                    continue
                if not d:
                    break
                buf += d
        finally:
            s.close()

    out = {"multeq": "", "dyneq": None, "reflev": None, "dynvol": "",
           "cinemaeq": None, "swl_on": None, "levels": {}}
    for line in buf.decode(errors="ignore").split("\r"):
        line = line.strip()
        if line.startswith("PSMULTEQ:"):
            out["multeq"] = line[9:]
        elif line.startswith("PSDYNEQ "):
            out["dyneq"] = line[8:] == "ON"
        elif line.startswith("PSREFLEV "):
            out["reflev"] = line[9:]
        elif line.startswith("PSDYNVOL "):
            out["dynvol"] = line[9:]
        elif line.startswith("PSCINEMA EQ."):
            out["cinemaeq"] = line[12:] == "ON"
        elif line.startswith("PSTONE CTRL "):
            out["tone"] = line.endswith("ON")
        elif re.match(r"^PSBAS \d{2}$", line):
            out["bass"] = int(line[6:])
        elif re.match(r"^PSTRE \d{2}$", line):
            out["treble"] = int(line[6:])
        elif line in ("PSGEQ ON", "PSGEQ OFF"):
            out["geq"] = line == "PSGEQ ON"
        elif line in ("PSSWL ON", "PSSWL OFF"):
            out["swl_on"] = line == "PSSWL ON"
        elif re.match(r"^PSSWL \d{2,3}$", line):
            out["swl"] = parse_level(line[6:])
        elif line.startswith("CV") and line != "CVEND":
            m = re.match(r"^CV([A-Z]+) (\d{2,3})$", line)
            if m:
                out["levels"][m.group(1)] = parse_level(m.group(2))
    return out
