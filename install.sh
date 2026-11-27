#!/bin/bash
# Touch Remote for Marantz – install for the current user (no sudo needed).
# Marantz-Fernbedienung installieren (für den aktuellen Benutzer, ohne sudo).
# Linux with Python 3 and GTK 3 (e.g. Linux Mint, Ubuntu, Debian).
set -e
cd "$(dirname "$0")"
DEST="$HOME/.local/share/marantz-fernbedienung"

# Sprache wie das System / language like the system
case "${LANGUAGE:-${LC_ALL:-${LC_MESSAGES:-$LANG}}}" in
    de*) DE=1 ;;
    *)   DE= ;;
esac
say() { if [ -n "$DE" ]; then echo "$1"; else echo "$2"; fi; }

say "== Prüfe Voraussetzungen …" "== Checking requirements …"
if ! python3 -c "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk; import cairo; gi.require_foreign('cairo')" 2>/dev/null; then
    echo
    say "Es fehlen Bausteine. Bitte zuerst ausführen und danach dieses Skript erneut starten:" \
        "Some packages are missing. Please run this first, then start this script again:"
    echo "    sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0"
    exit 1
fi

say "== Kopiere Programm nach $DEST …" "== Copying program to $DEST …"
mkdir -p "$DEST"
cp app.py marantz.py upnp.py server.py i18n.py sprachbefehle.py voice.py mic-fix.sh icon.svg "$DEST/"

say "== Lege Startmenü-Eintrag an …" "== Creating menu entry …"
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/marantz.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Touch Remote for Marantz
Comment=Touch remote for Marantz AV receivers
Comment[de]=Fernbedienung für den Marantz-Receiver
Exec=/usr/bin/python3 $DEST/app.py
Icon=$DEST/icon.svg
Terminal=false
Categories=AudioVideo;Audio;
StartupNotify=true
EOF

say "== Richte Hintergrunddienst ein (Mediathek-Wiedergabe, nur lokal) …" \
    "== Setting up background service (library playback, local only) …"
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/marantz-web.service" <<EOF
[Unit]
Description=Touch Remote for Marantz (library playback, local only)
After=network-online.target

[Service]
ExecStart=/usr/bin/python3 $DEST/server.py
WorkingDirectory=$DEST
Restart=on-failure
RestartSec=5
StandardOutput=null
StandardError=journal
MemoryMax=80M

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now marantz-web.service
systemctl --user restart marantz-web.service

echo
say "Fertig! Im Startmenü nach „Touch Remote for Marantz“ suchen." "Done! Look for “Touch Remote for Marantz” in the start menu."
say "Receiver und Medienserver werden im Heimnetz automatisch gefunden." \
    "The receiver and media server are found automatically on your home network."
