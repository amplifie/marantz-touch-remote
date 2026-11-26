"""Sprache: Deutsch oder Englisch – automatisch nach der Systemsprache.

Deutsch, wenn das System auf Deutsch steht (LANGUAGE / LC_ALL / LC_MESSAGES / LANG),
sonst Englisch. Fest einstellen: in ~/.config/marantz/config.json
    "language": "de"   oder   "en"   (Standard: "auto")

Die Texte im Programm sind deutsch; _() liefert im englischen Modus die Übersetzung.
Texte mit Platzhaltern sind Vorlagen: _("Lautstärke {}").format(45)
"""
import json
import os

CONFIG_FILE = os.path.expanduser("~/.config/marantz/config.json")


def detect() -> str:
    try:
        with open(CONFIG_FILE) as f:
            choice = str(json.load(f).get("language", "auto")).lower()
        if choice in ("de", "en"):
            return choice
    except (OSError, ValueError, AttributeError):
        pass
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var, "")
        if val:
            return "de" if val.lower().startswith("de") else "en"
    return "en"


LANG = detect()
DEC = "," if LANG == "de" else "."     # Dezimalzeichen

EN = {
    # --- Navigation, Leisten ---
    "Bedienung": "Control", "Klang & Pegel": "Sound & Levels", "Mediathek": "Library",
    "SZENEN": "SCENES", "SPRECHEN": "SPEAK", "LAUTSTÄRKE": "VOLUME", "Lautstärke": "Volume",
    "Stumm": "Mute", "Ton an": "Unmute", "STUMM": "MUTED", "verbinde …": "connecting …",
    "EINGANG WÄHLEN": "SELECT INPUT", "EINGANG": "INPUT", "Eingang": "Input",
    "KLANGMODUS": "SURROUND MODE", "Klangmodus": "Surround mode",
    "Eingeschaltet": "On", "Standby": "Standby", "Receiver ist ausgeschaltet": "Receiver is off",
    "Keine Verbindung": "No connection", "Receiver unter %s nicht erreichbar": "Receiver at %s not reachable",
    "Receiver-Fehler: {}": "Receiver error: {}", "Plex-Fehler: {}": "Plex error: {}",
    "Fehler im Hintergrunddienst: {}": "Background service error: {}", "Fehler: {}": "Error: {}",
    "Hintergrunddienst antwortet nicht": "Background service not responding",
    "Zugriff nicht erlaubt": "Access not allowed",
    "TASTATUR": "KEYBOARD",
    "Leertaste": "Space",
    "Wiedergabe / Pause": "Play / pause",
    "10 Sekunden zurück / vor": "10 seconds back / forward",
    "Nächster / voriger Titel / Stopp": "Next / previous track / stop",
    "Bedienung, Klang & Pegel, EQ, Mediathek": "Control, Sound & Levels, EQ, Library",
    "Eingang wählen, dann Ziffer": "Choose input, then digit",
    "Strg + 1 – 3": "Ctrl + 1 – 3",
    "Szene starten": "Start scene",
    "Receiver ein / aus": "Receiver on / off",
    "Einen Schritt zurück": "One step back",
    "Strg + M": "Ctrl + M",
    "Strg + Q": "Ctrl + Q",
    "Vollbild an / aus": "Full screen on / off",
    "Diese Hilfe": "This help",
    "Schließen": "Close",
    "Tastaturkürzel": "Keyboard shortcuts",
    "Zum Ein-/Ausschalten noch einmal P drücken": "Press P again to switch on / off",
    "Knopf oder Regler auswählen": "Select button or slider",
    "Auswahl auslösen": "Activate selection",
    "In Listen und Menüs: auswählen": "In lists and menus: select",
    "Rücktaste": "Backspace",
    "Zurück (Mediathek, Fernsehmenü)": "Back (library, TV menu)",
    "Titel nicht gefunden": "Track not found",
    "keine Antwort": "no response",
    "Antwort aus dem Netz ist zu groß": "Network reply is too large",
    "Titel lässt sich nicht starten": "Track does not start",
    "Receiver ist nicht bereit zum Spulen": "Receiver is not ready to seek",
    "Receiver antwortet nicht": "Receiver is not responding",
    "Diese Stelle kann nicht angesprungen werden": "Cannot seek to this position",
    # --- Sound Mode / Modi / Eingänge (aus marantz.py) ---
    "Film": "Movie", "Musik": "Music", "Spiel": "Game", "Pure": "Pure",
    "Mediaserver": "Media Server", "Internetradio": "Internet Radio", "Favoriten": "Favorites",
    "USB / iPod": "USB / iPod", "Eingang bleibt": "Input unchanged",
    "Filmabend": "Movie Night", "Alles aus": "All Off",
    # --- Klang & Pegel ---
    "AUDYSSEY": "AUDYSSEY", "Referenzpegel-Offset": "Reference level offset",
    "Leicht": "Light", "Mittel": "Medium", "Stark": "Heavy", "Ein": "On", "Aus": "Off",
    "In Direct und Pure Direct schaltet der Receiver Audyssey und Cinema EQ ab.":
        "In Direct and Pure Direct the receiver switches Audyssey and Cinema EQ off.",
    "PEGEL": "LEVELS", "Subwoofer-Pegel": "Subwoofer level", "Schnellanpassung": "Quick adjust",
    "Front links": "Front left", "Front rechts": "Front right", "Center": "Center",
    "Subwoofer": "Subwoofer", "Surround links": "Surround left", "Surround rechts": "Surround right",
    "Höhe vorne links": "Front height left", "Höhe vorne rechts": "Front height right",
    "Höhe hinten links": "Rear height left", "Höhe hinten rechts": "Rear height right",
    # --- EQ ---
    "KLANGREGELUNG": "TONE CONTROL", "Bass / Höhen": "Bass / Treble", "Bass": "Bass",
    "Höhen": "Treble", "GRAFIK-EQ": "GRAPHIC EQ", "Grafik-EQ": "Graphic EQ",
    "Wirkt nur, wenn Dynamic EQ aus ist und nicht in Direct / Pure Direct.":
        "Only works when Dynamic EQ is off and not in Direct / Pure Direct.",
    "Lautsprecher": "Speakers", "Front": "Front", "Surround": "Surround",
    "Höhe v.": "Height F", "Höhe h.": "Height R", "Alle auf 0": "All to 0",
    "Sicher? Nochmal": "Sure? Tap again",
    "Wirkt nur bei MultEQ „Aus“ (Seite Klang & Pegel). Änderungen werden nach kurzem "
    "Loslassen automatisch im Receiver gespeichert.":
        "Only works with MultEQ “Off” (Sound & Levels page). Changes are saved to the "
        "receiver automatically shortly after you let go.",
    "lädt …": "loading …", "speichere …": "saving …", "Gespeichert ✓": "Saved ✓",
    "Receiver hat andere Werte gemeldet": "Receiver reported different values",
    "Nicht erreichbar: {}": "Not reachable: {}", "Fehler: {}": "Error: {}",
    # --- Mediathek ---
    "‹  Zurück": "‹  Back", "Bibliothek": "Library", "‹  Bibliothek": "‹  Library",
    "Jetzt läuft": "Now Playing", "Zum Spulen auf den Balken tippen": "Tap the bar to seek",
    "{} Einträge": "{} items", "1 Eintrag": "1 item", "leer": "empty",
    "nicht abspielbar": "not playable", "Pause · ": "Paused · ", "Gestoppt · ": "Stopped · ",
    "lädt … · ": "loading … · ", "Titel {} von {}": "Track {} of {}",
    # --- Szenen ---
    "Szene": "Scene", "Szene {}": "Scene {}", "Szene „{}“ wird eingestellt …": "Setting scene “{}” …",
    "Szenen bearbeiten": "Edit scenes", "Name der Szene": "Scene name",
    "Aktuellen Zustand übernehmen": "Use current settings", "Was soll passieren?": "What should happen?",
    "Einschalten & einstellen": "Turn on & set up", "Ausschalten (Standby)": "Turn off (standby)",
    "unverändert": "unchanged", "Abbrechen": "Cancel", "Speichern": "Save",
    "Der Receiver ist aus – bitte erst einschalten und einstellen.":
        "The receiver is off – please turn it on and set it up first.",
    "Aktueller Zustand übernommen": "Current settings applied", "Szenen gespeichert": "Scenes saved",
    # --- Eingangsleiste ---
    "Eingänge in der Leiste": "Inputs in the bar",
    "Bis zu {} Eingänge antippen – in der Reihenfolge, in der sie erscheinen sollen. "
    "Nochmal tippen entfernt.":
        "Tap up to {} inputs – in the order they should appear. Tap again to remove.",
    "Höchstens {} Eingänge – erst einen anderen abwählen.":
        "At most {} inputs – deselect another one first.",
    "Bitte mindestens einen Eingang wählen.": "Please select at least one input.",
    "Eingangsleiste gespeichert": "Input bar saved",
    # --- Setup-Menü am Fernseher ---
    "Einstellungsmenü am Fernseher": "Setup menu on the TV", "Web-Oberfläche": "Web interface",
    "Das Menü des Receivers erscheint auf dem Fernseher. Mit den Pfeilen bewegen, mit OK "
    "auswählen. Pfeile gedrückt halten = weiter.":
        "The receiver's menu appears on the TV. Move with the arrows, select with OK. "
        "Hold an arrow to repeat.",
    "Option": "Option", "Menü schließen": "Close menu", "MENÜ": "MENU", "App beenden": "Quit app", "Minimieren": "Minimize", "Schließen & zurück zu {}": "Close & back to {}",
    # --- Lautstärke-Warnungen ---
    "Achtung: Ab 80 wird es sehr laut.\nFür mehr einfach noch einmal drücken oder neu am Ring "
    "ansetzen.":
        "Caution: above 80 it gets very loud.\nFor more, just press again or start a new turn "
        "on the ring.",
    "Sehr laut ({}) – bitte Ohren und Lautsprecher schonen.":
        "Very loud ({}) – please protect your ears and speakers.",
    "Lautstärke {}": "Volume {}", "Lautstärke gerade unbekannt.": "Volume currently unknown.",
    # --- Sprachsteuerung ---
    "Sprachsteuerung wird geladen …": "Loading voice control …", "🎤  Ich höre zu …": "🎤  Listening …",
    "Sprachsteuerung: {}": "Voice control: {}",
    "Nichts verstanden – bitte noch einmal.": "Didn't catch that – please try again.",
    "{}\nDas habe ich leider nicht verstanden.": "{}\nSorry, I didn't understand that.",
    "{}\n→ Ausschalten": "{}\n→ Turning off", "{}\n→ {}": "{}\n→ {}",
    "Pause": "Pause", "Weiter": "Resume", "Stopp": "Stop", "Nächster Titel": "Next track",
    "Vorheriger Titel": "Previous track", "{}\nSuche in der Mediathek …": "{}\nSearching the library …",
    "Mediathek nicht erreichbar:\n{}": "Library not reachable:\n{}",
    "„{}“\nKünstler „{}“ nicht gefunden.": "“{}”\nArtist “{}” not found.",
    "„{}“\n→ Spiele {}": "“{}”\n→ Playing {}", " (zufällig)": " (shuffled)",
    "Einschalten": "Turn on", "Eingang TV Audio": "Input TV Audio", "Eingang Game": "Input Game",
    "Eingang Mediaserver": "Input Media Server", "Szene Musik": "Scene Music",
    # --- Fehlermeldungen aus marantz.py / upnp.py / server.py ---
    "Marantz-Receiver im Netz nicht gefunden": "Marantz receiver not found on the network",
    "Plex-Server nicht gefunden": "Plex server not found",
    "Künstlerliste in Plex nicht gefunden": "Artist list not found in Plex",
}


def _(text: str) -> str:
    """Übersetzen (nur im englischen Modus)."""
    if LANG == "en" and isinstance(text, str):
        return EN.get(text, text)
    return text


def tr_lang(text: str, lang: str) -> str:
    """Übersetzen für eine bestimmte Sprache (z. B. für die Handy-Webseite)."""
    return EN.get(text, text) if lang == "en" else text
