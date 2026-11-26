#!/bin/bash
# Marantz-Fernbedienung wieder entfernen.
systemctl --user disable --now marantz-web.service 2>/dev/null
rm -f "$HOME/.config/systemd/user/marantz-web.service"
systemctl --user daemon-reload
rm -f "$HOME/.local/share/applications/marantz.desktop"
rm -rf "$HOME/.local/share/marantz-fernbedienung"
rm -rf "$HOME/.config/marantz"
echo "Marantz-Fernbedienung entfernt."
