#!/usr/bin/env bash
# Installs the mania2mp4 command, an app menu entry and a Dolphin right-click action.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
MENUS="$HOME/.local/share/kio/servicemenus"
mkdir -p "$BIN" "$APPS" "$MENUS"

cat > "$BIN/mania2mp4" <<SH
#!/usr/bin/env bash
PYTHONPATH="$SRC\${PYTHONPATH:+:\$PYTHONPATH}" exec python3 -m mania2mp4 "\$@"
SH
chmod +x "$BIN/mania2mp4"

cat > "$APPS/mania2mp4.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=osu!mania Replay to MP4
Comment=Render an osu!mania replay as a video
Exec=$BIN/mania2mp4 --gui %F
Icon=video-x-generic
Terminal=false
Categories=AudioVideo;Video;
DESK

cat > "$MENUS/mania2mp4.desktop" <<MENU
[Desktop Entry]
Type=Service
MimeType=application/x-osu-replay;
Actions=render;
X-KDE-Priority=TopLevel

[Desktop Action render]
Name=Convert to MP4
Icon=video-x-generic
Exec=$BIN/mania2mp4 --gui %F
MENU
chmod +x "$MENUS/mania2mp4.desktop"

update-desktop-database "$APPS" 2>/dev/null || true
echo "Installed. Run 'mania2mp4 --help' or right-click an .osr file in Dolphin."
