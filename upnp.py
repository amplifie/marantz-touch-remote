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
        raw = urllib.request.urlopen(req, timeout=timeout).read()
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "ignore")
        code = re.search(r"<errorCode>(\d+)", txt)
        desc = re.search(r"<errorDescription>([^<]*)", txt)
        raise RuntimeError(f"UPnP-Fehler {code.group(1) if code else e.code}: "
                           f"{desc.group(1) if desc else ''}") from None
    root = ET.fromstring(raw)
    resp = root.find(".//{%s}%sResponse" % (service, action))
    return {child.tag.split("}")[-1]: (child.text or "") for child in (resp if resp is not None else [])}


# ---------- Plex finden ----------
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
            if loc and loc.group(1).decode() not in locations:
                locations.append(loc.group(1).decode())
    finally:
        s.close()
    for loc in locations:
        try:
            desc = urllib.request.urlopen(loc, timeout=3).read().decode("utf-8", "ignore")
        except OSError:
            continue
        if "plex" not in desc.lower():
            continue
        m_ = re.search(r"<serviceType>" + re.escape(CD) + r"</serviceType>.*?<controlURL>([^<]+)",
                       desc, re.S)
        if m_:
            return urllib.parse.urljoin(loc, m_.group(1))
    raise RuntimeError("Plex-Server nicht gefunden")


def plex_ctrl(refresh: bool = False) -> str:
    if _plex["ctrl"] and not refresh:
        return _plex["ctrl"]
    if not refresh:
        try:
            with open(PLEX_FILE) as f:
                _plex["ctrl"] = f.read().strip()
                return _plex["ctrl"]
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
            res = el.find("didl:res", NS)
            if res is not None:
                entry["uri"] = (res.text or "").strip()
                entry["duration"] = _secs(res.get("duration", ""))
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
    except Exception as e:
        e.source = "plex"           # für die Fehlermeldung in der App
        raise
    return {"items": _parse_didl(r.get("Result", "")), "total": int(r.get("TotalMatches") or 0)}


def browse_all(object_id: str, limit: int = 2000) -> list:
    items, start = [], 0
    while start < limit:
        r = browse(object_id, start, 200)
        items += r["items"]
        start += len(r["items"])
        if not r["items"] or start >= r["total"]:
            break
    return items


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
