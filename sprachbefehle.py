"""Sprachbefehle verstehen: erkannter Text → Aktion für die Marantz-App.

Die Erkennung (Vosk) liefert kleingeschriebenen Text ohne Satzzeichen, Zahlen
als Wörter („fünfundfünfzig“). Hier wird daraus ein Befehl.
"""
import difflib
import re

EINER = {"null": 0, "ein": 1, "eins": 1, "eine": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5,
         "sechs": 6, "sieben": 7, "acht": 8, "neun": 9}
ZEHNER_SONDER = {"zehn": 10, "elf": 11, "zwölf": 12, "dreizehn": 13, "vierzehn": 14,
                 "fünfzehn": 15, "sechzehn": 16, "siebzehn": 17, "achtzehn": 18, "neunzehn": 19}
ZEHNER = {"zwanzig": 20, "dreißig": 30, "dreissig": 30, "vierzig": 40, "fünfzig": 50,
          "sechzig": 60, "siebzig": 70, "achtzig": 80, "neunzig": 90}


def zahl(wort: str):
    """Deutsches Zahlwort (0–99) oder Ziffern → int, sonst None."""
    w = wort.strip().lower().replace(" ", "")
    if w.isdigit():
        return int(w)
    if w in EINER:
        return EINER[w]
    if w in ZEHNER_SONDER:
        return ZEHNER_SONDER[w]
    if w in ZEHNER:
        return ZEHNER[w]
    if "und" in w:
        e, _, z = w.partition("und")
        if e in EINER and z in ZEHNER:
            return EINER[e] + ZEHNER[z]
    return None


def finde_zahl(text: str):
    # zuerst über mehrere Wörter („fünf und fünfzig“)
    m = re.search(r"(\w+)\s+und\s+(\w+(?:zig|ßig|ssig))", text)
    if m and zahl(m.group(1) + "und" + m.group(2)) is not None:
        return zahl(m.group(1) + "und" + m.group(2))
    for wort in text.split():
        n = zahl(wort)
        if n is not None:
            return n
    return None


def _norm(s: str) -> str:
    s = s.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9 ]", "", s).strip()


def finde_kuenstler(name: str, kuenstler: list):
    """Unscharfer Abgleich mit der Plex-Künstlerliste. kuenstler = [{"id","title"}]."""
    if not name or not kuenstler:
        return None
    n = _norm(name)
    beste, wert = None, 0.0
    for k in kuenstler:
        t = _norm(k["title"])
        if not t:
            continue
        r = difflib.SequenceMatcher(None, n, t).ratio()
        # „the cranberries“ ↔ „cranberries“ usw.
        if t.startswith("the ") and difflib.SequenceMatcher(None, n, t[4:]).ratio() > r:
            r = difflib.SequenceMatcher(None, n, t[4:]).ratio()
        if r > wert:
            beste, wert = k, r
    return beste if wert >= 0.6 else None


def verstehe(text: str) -> dict:
    """Gibt {"aktion": ..., ...} zurück. aktion=None → nicht verstanden."""
    t = " " + text.lower().strip() + " "
    hat = lambda *ws: any(f" {w} " in t or (w.endswith("*") and f" {w[:-1]}" in t) for w in ws)

    # --- Musik aus der Mediathek ---
    m = re.match(r"\s*(?:bitte\s+)?(?:spiele?|spiel mal|spiele mal|abspielen|hör|höre)\s+(.*)", t)
    if m:
        rest = m.group(1).strip()
        zufall = bool(re.search(r"\b(zufällig|durcheinander|gemischt|shuffle)\b", rest))
        rest = re.sub(r"\b(zufällig|durcheinander|gemischt|shuffle|bitte|mal|etwas|was)\b", " ", rest)
        rest = re.sub(r"^\s*(musik|lieder|songs|titel|alles)?\s*(von|vom)?\s*", "", rest).strip()
        if rest:
            return {"aktion": "kuenstler", "name": rest, "zufall": zufall}

    # --- Wiedergabe ---
    if hat("pause", "anhalten"):
        return {"aktion": "ctl", "wert": "pause"}
    if hat("stopp", "stop", "stoppen", "beenden"):
        return {"aktion": "ctl", "wert": "stop"}
    if hat("nächster", "nächstes", "nächste", "überspringen", "skip"):
        return {"aktion": "ctl", "wert": "next"}
    if hat("vorheriger", "vorheriges", "vorherige", "zurück"):
        return {"aktion": "ctl", "wert": "prev"}
    if hat("weiter", "fortsetzen", "abspielen", "play"):
        return {"aktion": "ctl", "wert": "play"}

    # --- Lautstärke ---
    if hat("lautstärke", "auf") and finde_zahl(t) is not None:
        return {"aktion": "lautstaerke", "wert": finde_zahl(t)}
    if hat("stumm", "ruhe", "ton aus"):
        return {"aktion": "cmd", "wert": "MUON", "text": "Stumm"}
    if hat("ton an", "ton wieder an", "laut") and not hat("lauter"):
        return {"aktion": "cmd", "wert": "MUOFF", "text": "Ton an"}
    if hat("lauter"):
        return {"aktion": "schritt", "wert": 10 if hat("viel", "deutlich") else 5}
    if hat("leiser"):
        return {"aktion": "schritt", "wert": -10 if hat("viel", "deutlich") else -5}

    # --- Szenen / Ein-Aus ---
    if hat("filmabend", "film", "kino"):
        return {"aktion": "szene", "wert": "film", "text": "Filmabend"}
    if hat("alles aus", "ausschalten", "ausmachen", "schlafen", "gute nacht") or t.strip() == "aus":
        return {"aktion": "szene", "wert": "aus", "text": "Alles aus"}
    if hat("einschalten", "anschalten", "anmachen") or t.strip() == "an":
        return {"aktion": "cmd", "wert": "ZMON", "text": "Einschalten"}

    # --- Eingänge ---
    if hat("fernseher", "fernsehen", "tv", "t v", "tee vau", "fernseh*"):
        return {"aktion": "cmd", "wert": "SITV", "text": "Eingang TV Audio"}
    if hat("game", "konsole", "spielkonsole", "playstation", "xbox", "spiel*"):
        return {"aktion": "cmd", "wert": "SIGAME", "text": "Eingang Game"}
    if hat("mediaserver", "media server", "medien*", "server", "mediathek"):
        return {"aktion": "cmd", "wert": "SISERVER", "text": "Eingang Mediaserver"}
    if hat("musik"):
        return {"aktion": "szene", "wert": "musik", "text": "Szene Musik"}

    return {"aktion": None}
