#!/usr/bin/env bash
# Install Daily Checklist as a desktop application.
# Run: ./install.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_PATH="$SCRIPT_DIR/daily_checklist.py"
DESKTOP_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$DESKTOP_DIR/daily-checklist.desktop"

# Ensure the Python script is executable
chmod +x "$APP_PATH"

# Check for PyQt5
if ! python3 -c "from PyQt5.QtWidgets import QApplication" 2>/dev/null; then
    echo "PyQt5 not found. Installing..."
    pip3 install --user PyQt5
fi

# Create .desktop file with the correct absolute path
mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Daily Checklist
Comment=Calendar-based daily task checklist
Exec=python3 $APP_PATH
Icon=org.gnome.Calendar
Terminal=false
Categories=Utility;Office;
StartupWMClass=daily-checklist
EOF

chmod +x "$DESKTOP_FILE"

echo "Installed! You can now:"
echo "  1. Find 'Daily Checklist' in your application menu"
echo "  2. Or run directly:  python3 $APP_PATH"
