#!/bin/bash
# Baut das Installationspaket ~/touch-remote-for-marantz.tar.gz aus dem aktuellen Stand.
set -e
cd "$(dirname "$0")"
TMP=$(mktemp -d)
mkdir "$TMP/touch-remote-for-marantz"
cp app.py marantz.py upnp.py server.py i18n.py sprachbefehle.py voice.py mic-fix.sh icon.svg install.sh uninstall.sh LIESMICH.txt README.md README.de.md LICENSE \
   "$TMP/touch-remote-for-marantz/"
chmod +x "$TMP/touch-remote-for-marantz/"*.sh
tar czf "$HOME/touch-remote-for-marantz.tar.gz" -C "$TMP" touch-remote-for-marantz
rm -rf "$TMP"
echo "Paket erstellt: $HOME/touch-remote-for-marantz.tar.gz ($(du -h "$HOME/touch-remote-for-marantz.tar.gz" | cut -f1))"
