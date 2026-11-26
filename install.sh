#!/bin/bash
# Marantz-Fernbedienung installieren (für den aktuellen Benutzer, ohne sudo).
# Läuft auf Linux mit Python 3 und GTK 3 (z. B. Linux Mint, Ubuntu, Debian).
set -e
cd "$(dirname "$0")"
DEST="$HOME/.local/share/marantz-fernbedienung"

echo "== Prüfe Voraussetzungen …"
if ! python3 -c "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk; import cairo; gi.require_foreign('cairo')" 2>/dev/null; then
    echo
    echo "Es fehlen Bausteine. Bitte zuerst ausführen und danach dieses Skript erneut starten:"
    echo "    sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0"
    exit 1
fi

echo "== Kopiere Programm nach $DEST …"
mkdir -p "$DEST"
cp app.py marantz.py upnp.py server.py sprachbefehle.py voice.py mic-fix.sh index.html icon.svg "$DEST/"

echo "== Lege Startmenü-Eintrag an …"
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/marantz.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Marantz
Comment=Fernbedienung für den Marantz-Receiver
Exec=/usr/bin/python3 $DEST/app.py
Icon=$DEST/icon.svg
Terminal=false
Categories=AudioVideo;Audio;
StartupNotify=true
EOF

echo "== Richte Hintergrunddienst ein (Mediathek + Handy-Webseite, Port 8080) …"
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/marantz-web.service" <<EOF
[Unit]
Description=Marantz-Fernbedienung (Mediathek-Wiedergabe und Webseite, Port 8080)
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
echo "Fertig! Im Startmenü nach „Marantz“ suchen."
echo "Receiver und Plex-Server werden im Heimnetz automatisch gefunden."
echo "Handy-Webseite: http://<IP-dieses-Rechners>:8080  (evtl. Firewall-Port 8080 freigeben)"
