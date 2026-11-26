#!/bin/bash
# Baut das Installationspaket ~/marantz-fernbedienung.tar.gz aus dem aktuellen Stand.
set -e
cd "$(dirname "$0")"
TMP=$(mktemp -d)
mkdir "$TMP/marantz-fernbedienung"
cp app.py marantz.py upnp.py server.py i18n.py sprachbefehle.py voice.py mic-fix.sh index.html icon.svg install.sh uninstall.sh LIESMICH.txt README.md \
   "$TMP/marantz-fernbedienung/"
chmod +x "$TMP/marantz-fernbedienung/"*.sh
tar czf "$HOME/marantz-fernbedienung.tar.gz" -C "$TMP" marantz-fernbedienung
rm -rf "$TMP"
echo "Paket erstellt: $HOME/marantz-fernbedienung.tar.gz ($(du -h "$HOME/marantz-fernbedienung.tar.gz" | cut -f1))"
