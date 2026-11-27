"""UPnP-Baustein: Plex-Bibliothek durchsuchen (ContentDirectory) und den
Receiver als Abspielgerät steuern (AVTransport). Nur Python-Standardbibliothek.
"""
import html
import os
import re
import socket
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

import marantz as m

NS = {
    "didl": "urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "upnp": "urn:schemas-upnp-org:metadata-1-0/upnp/",
}
CD = "urn:schemas-upnp-org:service:ContentDirectory:1"
AVT = "urn:schemas-upnp-org:service:AVTransport:1"
PLEX_FILE = os.path.expanduser("~/.config/marantz/plex")

_plex = {"ctrl": None}
MAX_SOAP = 8 * 1024 * 1024   # eine Seite mit 200 Titeln hat nur einige hundert KB


# ---------- SOAP ----------
def soap(url: str, service: str, action: str, args: dict, timeout: float = 6) -> dict:
    body = "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in args.items())
    env = ('<?xml version="1.0" encoding="utf-8"?>'
           '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
           's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
           f'<u:{action} xmlns:u="{service}">{body}</u:{action}></s:Body></s:Envelope>')
    req = urllib.request.Request(url, data=env.encode("utf-8"), headers={
        "Content-Type": 'text/xml; charset="utf-8"', "SOAPACTION": f'"{service}#{action}"'})
    try:
        raw = m.read_limited(urllib.request.urlopen(req, timeout=timeout), MAX_SOAP)
    except urllib.error.HTTPError as e:
        txt = e.read(65536).decode("utf-8", "ignore")
        code = re.search(r"<errorCode>(\d+)", txt)
        desc = re.search(r"<errorDescription>([^<]*)", txt)
        raise RuntimeError(f"UPnP-Fehler {code.group(1) if code else e.code}: "
                           f"{desc.group(1) if desc else ''}") from None
    root = ET.fromstring(raw)
    resp = root.find(".//{%s}%sResponse" % (service, action))
    return {child.tag.split("}")[-1]: (child.text or "") for child in (resp if resp is not None else [])}


# ---------- Plex finden ----------
def _is_web(url: str) -> bool:
    """Nur normale Webadressen öffnen (nie file:, ftp: …) – sie kommen aus dem Netz."""
    return url.lower().startswith(("http://", "https://"))


def _find_plex() -> str:
    """Plex-Server per SSDP suchen, Steuer-Adresse seines ContentDirectory zurückgeben."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0.5)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    msg = ('M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\n'
           f'MX: 2\r\nST: {CD}\r\n\r\n').encode()
    locations = []
    try:
        for _ in range(2):
            s.sendto(msg, ("239.255.255.250", 1900))
        end = time.time() + 3
        while time.time() < end:
            try:
                data, _a = s.recvfrom(4096)
            except socket.timeout:
                continue
            loc = re.search(rb"(?im)^location:\s*(\S+)", data)
            if loc:
                address = loc.group(1).decode("utf-8", "ignore")
                if address not in locations:
                    locations.append(address)
    finally:
        s.close()
    for loc in filter(_is_web, locations):
        try:
            desc = m.read_limited(urllib.request.urlopen(loc, timeout=3)).decode("utf-8", "ignore")
            if "plex" not in desc.lower():
                continue
            m_ = re.search(r"<serviceType>" + re.escape(CD) + r"</serviceType>.*?<controlURL>([^<]+)",
                           desc, re.S)
            ctrl = urllib.parse.urljoin(loc, m_.group(1)) if m_ else ""
        except Exception:  # noqa: BLE001  (kaputte Adresse oder Antwort: nächstes Gerät)
            continue
        if _is_web(ctrl):
            return ctrl
    raise RuntimeError("Plex-Server nicht gefunden")


def plex_ctrl(refresh: bool = False) -> str:
    if _plex["ctrl"] and not refresh:
        return _plex["ctrl"]
    if not refresh:
        try:
            with open(PLEX_FILE) as f:
                saved = f.read().strip()
            if _is_web(saved):
                _plex["ctrl"] = saved
                return saved
        except OSError:
            pass
    _plex["ctrl"] = _find_plex()
    try:
        os.makedirs(os.path.dirname(PLEX_FILE), exist_ok=True)
        with open(PLEX_FILE, "w") as f:
            f.write(_plex["ctrl"] + "\n")
    except OSError:
        pass
    return _plex["ctrl"]


# ---------- Bibliothek ----------
def _secs(t: str):
    if not t:
        return None
    try:
        parts = [float(x) for x in t.split(":")]
    except ValueError:
        return None
    v = 0.0
    for p in parts:
        v = v * 60 + p
    return int(v)


_FORMATS = {"audio/mpeg": "MP3", "audio/mp3": "MP3", "audio/flac": "FLAC", "audio/x-flac": "FLAC",
            "audio/wav": "WAV", "audio/x-wav": "WAV", "audio/l16": "PCM", "audio/x-ms-wma": "WMA",
            "audio/ogg": "OGG", "audio/aac": "AAC", "audio/mp4": "M4A", "audio/x-m4a": "M4A"}


def _bytes_per_s(res, value: int) -> float:
    """"bitrate" ist laut UPnP Byte pro Sekunde; manche Server (MiniDLNA) melden Bit pro
    Sekunde. Nennt der Server Größe und Länge, zeigt der Vergleich, was gemeint ist."""
    size, secs = res.get("size", ""), _secs(res.get("duration", ""))
    if value and secs and re.fullmatch(r"[0-9]{1,15}", size) and int(size):
        real = int(size) / secs
        # näher an "Bit" als an "Byte"? (Grenze beim geometrischen Mittel von 1 und 8)
        if value / real > 8 ** 0.5:
            return value / 8
    return value


def _audio_info(res, uri: str) -> dict:
    """Format, Bitrate (kbit/s) und Abtastrate (Hz) laut Server; Unbekanntes bleibt leer."""
    def number(name):
        v = res.get(name, "")
        return int(v) if re.fullmatch(r"[0-9]{1,9}", v) else 0
    proto = res.get("protocolInfo", "").split(":", 3) + ["", "", "", ""]
    mime = proto[2].split(";")[0].lower()
    ext = os.path.splitext(urllib.parse.urlparse(uri).path)[1][1:].lower()
    fmt = _FORMATS.get(mime) or (ext.upper() if ext.isalnum() and len(ext) <= 5 else "")
    if ext == "wav":
        fmt = "WAV"
    elif fmt == "M4A" and "DLNA.ORG_PN=AAC" in proto[3]:
        fmt = "AAC"
    # UPnP gibt "bitrate" in Byte pro Sekunde an. Bei WAV meldet Plex eine falsche
    # Abtastrate (48 statt 44,1 kHz, an echten Dateien geprüft) – dort weglassen.
    return {"format": fmt, "kbps": round(_bytes_per_s(res, number("bitrate")) * 8 / 1000),
            "rate": 0 if fmt in ("WAV", "PCM") else number("sampleFrequency")}


# ---------- Angaben direkt aus der Datei ----------
HEAD = 16 * 1024        # so viel wird höchstens am Stück gelesen
_MP3_KBPS = {True: (32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),   # MPEG 1
             False: (8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)}      # MPEG 2/2.5
_MP3_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}


def _read_part(uri: str, start: int) -> bytes:
    # Ohne festes Ende: kleine Dateien lehnt mancher Server sonst ab (MiniDLNA: 416).
    # Gelesen wird trotzdem nur HEAD; am Dateianfang ganz ohne Teil-Abruf.
    req = urllib.request.Request(uri, headers={"Range": f"bytes={start}-"} if start else {})
    with urllib.request.urlopen(req, timeout=5) as r:
        if start and r.status != 206:       # Server kann nicht mittendrin anfangen
            return b""
        return r.read(HEAD)


def _flac_info(d: bytes) -> dict:
    if d[:4] != b"fLaC" or len(d) < 26 or d[4] & 0x7F:     # erster Block: STREAMINFO
        return {}
    v = int.from_bytes(d[18:26], "big")
    rate, bits = v >> 44, ((v >> 36) & 31) + 1
    # FLAC schwankt immer: die Bitrate ist ein Durchschnitt
    return {"rate": rate, "bits": bits, "avg": True} if rate else {}


def _wav_info(d: bytes) -> dict:
    if d[:4] != b"RIFF" or d[8:12] != b"WAVE":
        return {}
    pos = 12
    while pos + 8 <= len(d):
        size = int.from_bytes(d[pos + 4:pos + 8], "little")
        if d[pos:pos + 4] == b"fmt " and size >= 16 and pos + 24 <= len(d):
            rate = int.from_bytes(d[pos + 12:pos + 16], "little")
            per_s = int.from_bytes(d[pos + 16:pos + 20], "little")
            bits = int.from_bytes(d[pos + 22:pos + 24], "little")
            return {"rate": rate, "bits": bits, "kbps": round(per_s * 8 / 1000),
                    "avg": False} if rate and per_s else {}
        pos += 8 + size + (size & 1)
    return {}


def _mp3_frame(d: bytes, i: int):
    """(Länge in Byte, kbit/s, Hz) eines MP3-Rahmens ab Stelle i, sonst None."""
    if i + 4 > len(d) or d[i] != 0xFF or d[i + 1] & 0xE6 != 0xE2:       # nur Layer III
        return None
    version, b, r = (d[i + 1] >> 3) & 3, d[i + 2] >> 4, (d[i + 2] >> 2) & 3
    if version == 1 or not 0 < b < 15 or r == 3:
        return None
    kbps, rate = _MP3_KBPS[version == 3][b - 1], _MP3_RATES[version][r]
    size = (144 if version == 3 else 72) * kbps * 1000 // rate + ((d[i + 2] >> 1) & 1)
    return size, kbps, rate


def _mp3_info(d: bytes, listed_kbps: int) -> dict:
    for i in range(len(d) - 4):
        f = _mp3_frame(d, i)
        if not f or not _mp3_frame(d, i + f[0]):    # zweiter Rahmen schützt vor Zufallstreffern
            continue
        head = d[i + 4:i + 44]
        if b"Xing" in head or b"VBRI" in head:      # wechselnde Bitrate
            avg = True
        elif b"Info" in head:                       # feste Bitrate
            avg = False
        else:   # ohne Hinweis: weicht der Gesamtwert vom ersten Rahmen ab, wechselt sie
            avg = bool(listed_kbps) and abs(listed_kbps - f[1]) > max(3, f[1] * 0.03)
        out = {"rate": f[2], "avg": avg}
        if not listed_kbps and not avg:
            out["kbps"] = f[1]
        return out
    return {}


def file_info(uri: str, fmt: str, listed_kbps: int = 0) -> dict:
    """Liest den Dateianfang: Abtastrate, Bittiefe und ob die Bitrate ein Durchschnitt ist.
    Leeres Ergebnis = nicht lesbar oder anderes Format, dann gelten die Server-Angaben."""
    if fmt not in ("MP3", "FLAC", "WAV") or not _is_web(uri):
        return {}
    d = _read_part(uri, 0)
    if fmt == "WAV":
        return _wav_info(d)
    if d[:3] == b"ID3" and len(d) >= 10:      # Infoblock (oft mit Cover) überspringen
        size = 10 + sum((d[6 + n] & 0x7F) << (21 - 7 * n) for n in range(4))
        if d[5] & 0x10:
            size += 10
        d = _read_part(uri, size)
    return _flac_info(d) if fmt == "FLAC" else _mp3_info(d, listed_kbps)


def _parse_didl(didl: str) -> list:
    root = ET.fromstring(didl)
    out = []
    for el in root:
        tag = el.tag.split("}")[-1]
        cls = el.findtext("upnp:class", "", NS)
        entry = {
            "id": el.get("id"),
            "title": el.findtext("dc:title", "", NS),
            "kind": "folder" if tag == "container" else "track",
            "count": el.get("childCount"),
            "art": el.findtext("upnp:albumArtURI", "", NS),
        }
        if tag == "item":
            if not cls.startswith("object.item.audioItem"):
                entry["kind"] = "other"   # Video/Foto: nicht abspielbar
            entry["artist"] = (el.findtext("upnp:artist", "", NS) or el.findtext("dc:creator", "", NS))
            entry["album"] = el.findtext("upnp:album", "", NS)
            # erste Fassung, die kein Bild/Video ist (manche Server nennen zuerst das Cover)
            res = next((r for r in el.findall("didl:res", NS)
                        if not re.match(r"[^:]*:[^:]*:(image|video|text)/",
                                        r.get("protocolInfo", ""), re.I)), None)
            if res is not None:
                entry["uri"] = (res.text or "").strip()
                entry["duration"] = _secs(res.get("duration", ""))
                entry.update(_audio_info(res, entry["uri"]))
            if not entry.get("uri"):
                entry["kind"] = "other"   # ohne Adresse: nicht abspielbar
            # Metadaten für den Receiver (einzelnes Item als eigenes DIDL-Dokument)
            entry["didl"] = ('<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
                             'xmlns:dc="http://purl.org/dc/elements/1.1/" '
                             'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
                             + ET.tostring(el, encoding="unicode") + "</DIDL-Lite>")
        out.append(entry)
    return out


def browse(object_id: str = "0", start: int = 0, count: int = 200) -> dict:
    args = {"ObjectID": object_id, "BrowseFlag": "BrowseDirectChildren", "Filter": "*",
            "StartingIndex": start, "RequestedCount": count, "SortCriteria": ""}
    try:
        try:
            r = soap(plex_ctrl(), CD, "Browse", args)
        except (OSError, RuntimeError):
            r = soap(plex_ctrl(refresh=True), CD, "Browse", args)  # Plex evtl. umgezogen
        items = _parse_didl(r.get("Result", ""))
        total = int(r.get("TotalMatches") or 0)
    except Exception as e:
        e.source = "plex"           # für die Fehlermeldung in der App
        raise
    more = total <= 0 and bool(items)       # 0 trotz Einträgen = Gesamtzahl unbekannt
    if total <= 0:
        total = start + len(items) + more   # +1: es kann noch weitergehen
    return {"items": items, "total": total, "open": more}


def browse_all(object_id: str, limit: int = 2000, start: int = 0) -> list:
    """Bis zu limit Einträge ab Position start."""
    items, end, first = [], start + limit, None
    while start < end:
        r = browse(object_id, start, 200)
        if r["items"]:
            if r["items"][0]["id"] == first:    # Server blättert nicht weiter
                break
            first = r["items"][0]["id"]
        items += r["items"]
        start += len(r["items"])
        if not r["items"] or start >= r["total"]:
            break
    return items[:limit]


# ---------- Receiver als Abspielgerät ----------
def _avt(action: str, **args) -> dict:
    try:
        return _avt_call(action, **args)
    except Exception as e:
        e.source = "receiver"       # für die Fehlermeldung in der App
        e.action = action
        raise


def _avt_call(action: str, **args) -> dict:
    # keine blinden Wiederholungen: Warten/Wiederholen entscheidet der Player (server.py)
    m._ensure_receiver()
    a = {"InstanceID": 0}
    a.update(args)
    try:
        return soap(f"http://{m.RECEIVER}:8080/AVTransport/ctrl", AVT, action, a)
    except OSError:
        if m.find_receiver():           # nur wenn sich die Adresse geändert hat
            return soap(f"http://{m.RECEIVER}:8080/AVTransport/ctrl", AVT, action, a)
        raise


def set_uri(uri: str, didl: str = "") -> None:
    _avt("SetAVTransportURI", CurrentURI=uri, CurrentURIMetaData=didl)


def set_next(uri: str, didl: str = "") -> None:
    _avt("SetNextAVTransportURI", NextURI=uri, NextURIMetaData=didl)


def play() -> None:
    _avt("Play", Speed=1)


def pause() -> None:
    _avt("Pause")


def stop() -> None:
    _avt("Stop")


def seek(seconds: int) -> None:
    h, rest = divmod(max(0, int(seconds)), 3600)
    mi, se = divmod(rest, 60)
    _avt("Seek", Unit="REL_TIME", Target=f"{h}:{mi:02d}:{se:02d}")


def transport_state() -> str:
    return _avt("GetTransportInfo").get("CurrentTransportState", "")


def state() -> dict:
    t = _avt("GetTransportInfo")
    p = _avt("GetPositionInfo")
    return {"state": t.get("CurrentTransportState", ""),
            "uri": html.unescape(p.get("TrackURI", "")),
            "elapsed": _secs(p.get("RelTime", "")),
            "duration": _secs(p.get("TrackDuration", ""))}
