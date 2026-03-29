#!/usr/bin/env bash
# install.sh — install zrktex for the current user or system-wide
#
# Usage:
#   bash install.sh            installs to ~/.local  (no sudo needed)
#   sudo bash install.sh       installs to /usr/local (system-wide, all users)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(realpath "$0")")" && pwd)"

# ── Install prefix ────────────────────────────────────────────────────────────
if [[ $EUID -eq 0 ]]; then
    PREFIX="/usr/local"
    PIP_FLAGS=""
    echo "Running as root — installing system-wide to $PREFIX"
else
    PREFIX="$HOME/.local"
    PIP_FLAGS="--user"
    echo "Running as user — installing to $PREFIX"
fi

DATA_DIR="$PREFIX/share/zrktex"
BIN_DIR="$PREFIX/bin"

# ── Python ────────────────────────────────────────────────────────────────────
PYTHON=""
for py in python3 python; do
    if command -v "$py" &>/dev/null && "$py" -c "import sys; assert sys.version_info >= (3,8)" 2>/dev/null; then
        PYTHON="$py"
        break
    fi
done

if [[ -z "$PYTHON" ]]; then
    echo "Error: Python 3.8+ not found." >&2
    if command -v apt-get &>/dev/null; then
        echo "  sudo apt-get install python3 python3-pip"
    elif command -v dnf &>/dev/null; then
        echo "  sudo dnf install python3 python3-pip"
    elif command -v pacman &>/dev/null; then
        echo "  sudo pacman -S python python-pip"
    fi
    exit 1
fi

echo "Using $($PYTHON --version)"

# ── GUI or TUI? ───────────────────────────────────────────────────────────────
echo ""
echo "Which mode do you want to install?"
echo "  1) GUI  — graphical editor with live PDF preview (needs tkinter)"
echo "  2) TUI  — terminal editor, vim-like (needs curses only)"
echo "  3) Both"
echo ""
read -rp "Choice [1]: " mode_choice
mode_choice="${mode_choice:-1}"

case "$mode_choice" in
    2) INSTALL_GUI=0; INSTALL_TUI=1 ;;
    3) INSTALL_GUI=1; INSTALL_TUI=1 ;;
    *) INSTALL_GUI=1; INSTALL_TUI=0 ;;
esac

# ── System packages ───────────────────────────────────────────────────────────
if [[ $INSTALL_GUI -eq 1 ]]; then
    echo ""
    if command -v apt-get &>/dev/null; then
        echo "Detected apt — installing system packages…"
        if [[ $EUID -eq 0 ]]; then
            apt-get install -y python3-tk python3-pip
        else
            echo "  (run with sudo to install python3-tk automatically)"
            echo "  Manual install if GUI fails:  sudo apt-get install python3-tk"
        fi
    elif command -v dnf &>/dev/null; then
        echo "Detected dnf — installing system packages…"
        if [[ $EUID -eq 0 ]]; then
            dnf install -y python3-tkinter python3-pip
        else
            echo "  Manual install if GUI fails:  sudo dnf install python3-tkinter"
        fi
    elif command -v pacman &>/dev/null; then
        echo "Detected pacman — installing system packages…"
        if [[ $EUID -eq 0 ]]; then
            pacman -S --noconfirm tk python-pip
        else
            echo "  Manual install if GUI fails:  sudo pacman -S tk"
        fi
    else
        echo "  Unknown distro — make sure python3-tk (tkinter) is installed for GUI mode."
    fi
fi

# ── Python packages ───────────────────────────────────────────────────────────
echo ""
echo "Installing Python dependencies…"

BASE_PKGS="pygments matplotlib numpy"

if [[ $INSTALL_GUI -eq 1 ]]; then
    "$PYTHON" -m pip install $PIP_FLAGS --upgrade $BASE_PKGS Pillow PyMuPDF
else
    "$PYTHON" -m pip install $PIP_FLAGS --upgrade $BASE_PKGS
fi

# ── Copy files ────────────────────────────────────────────────────────────────
echo ""
echo "Copying files to $DATA_DIR…"
mkdir -p "$DATA_DIR" "$BIN_DIR"
cp "$SCRIPT_DIR/zrktex.py" "$DATA_DIR/zrktex.py"

# ── Launcher ─────────────────────────────────────────────────────────────────
LAUNCHER="$BIN_DIR/zrktex"
echo "Installing launcher to $LAUNCHER…"

if [[ $INSTALL_GUI -eq 0 && $INSTALL_TUI -eq 1 ]]; then
    # TUI-only: bake --tui into the launcher so it's the default
    cat > "$LAUNCHER" << SCRIPT
#!/usr/bin/env bash
exec "$PYTHON" "$DATA_DIR/zrktex.py" --tui "\$@"
SCRIPT
else
    cat > "$LAUNCHER" << SCRIPT
#!/usr/bin/env bash
exec "$PYTHON" "$DATA_DIR/zrktex.py" "\$@"
SCRIPT
fi

chmod +x "$LAUNCHER"

# ── PATH check ────────────────────────────────────────────────────────────────
echo ""
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo "  $BIN_DIR is not in your PATH."
    echo ""
    if [[ "$PREFIX" == "$HOME/.local" ]]; then
        SHELL_RC=""
        if [[ -f "$HOME/.bashrc" ]]; then SHELL_RC="$HOME/.bashrc"
        elif [[ -f "$HOME/.zshrc" ]]; then SHELL_RC="$HOME/.zshrc"
        fi
        echo "Add this to ${SHELL_RC:-your shell rc file}:"
        echo ""
        echo '    export PATH="$HOME/.local/bin:$PATH"'
        echo ""
        if [[ -n "$SHELL_RC" ]]; then
            read -rp "Add it automatically to $SHELL_RC now? [y/N] " yn
            if [[ "$yn" =~ ^[Yy]$ ]]; then
                echo '' >> "$SHELL_RC"
                echo '# zrktex' >> "$SHELL_RC"
                echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_RC"
                echo "Done. Run:  source $SHELL_RC"
            fi
        fi
    fi
else
    echo "  $BIN_DIR is already in PATH."
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " zrktex installed!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
if [[ $INSTALL_GUI -eq 1 && $INSTALL_TUI -eq 1 ]]; then
    echo "  zrktex [file.tex]         open GUI"
    echo "  zrktex --tui [file.tex]   open TUI"
elif [[ $INSTALL_TUI -eq 1 ]]; then
    echo "  zrktex [file.tex]         open TUI (--tui is set by default)"
else
    echo "  zrktex [file.tex]         open GUI"
fi
echo ""
echo "To uninstall:"
echo "  rm -rf $DATA_DIR $LAUNCHER"
echo ""
