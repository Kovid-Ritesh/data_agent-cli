#!/bin/sh
# dagent-installer.sh — DataAgent CLI Installer for macOS / Linux
# Sets up the installation directory, downloads the binary, and guides PATH configuration.

set -e

echo "======================================================================="
echo "               Welcome to the DataAgent CLI Installer (v1.0.0)"
echo "======================================================================="
echo ""

INSTALL_DIR="$HOME/.dagent/bin"
EXE_PATH="$INSTALL_DIR/dagent"
LOCAL_URL="http://localhost:8000/download/dagent"
FALLBACK_URL="https://github.com/Kovid-Ritesh/data_agent-cli/releases/latest/download/dagent"

echo "[1/3] Creating installation directory..."
mkdir -p "$INSTALL_DIR"
echo "  Created directory: $INSTALL_DIR"
echo ""

echo "[2/3] Downloading dagent binary..."
if [ -f "$EXE_PATH" ]; then
    rm -f "$EXE_PATH"
fi

# Try local server download first
echo "  Attempting download from local server ($LOCAL_URL)..."
if curl -s -L -f -o "$EXE_PATH" "$LOCAL_URL"; then
    echo "  ✓ Downloaded from local server."
else
    echo "  Local server download unavailable. Attempting fallback URL ($FALLBACK_URL)..."
    if curl -s -L -f -o "$EXE_PATH" "$FALLBACK_URL"; then
        echo "  ✓ Downloaded from fallback URL."
    else
        echo "  [ERROR] Could not download dagent binary."
        echo "  Please ensure the server is running or download manually."
        exit 1
    fi
fi

chmod +x "$EXE_PATH"
echo "  ✓ Made binary executable."
echo ""

echo "[3/3] Checking PATH environment variable..."
case :$PATH: in
    *:$INSTALL_DIR:*)
        echo "  ✓ DataAgent bin directory is already in your PATH."
        ;;
    *)
        echo "  ⚠ DataAgent bin directory is NOT in your PATH."
        echo ""
        echo "  Please add the following line to your ~/.bashrc or ~/.zshrc file:"
        echo "    export PATH=\"\$PATH:\$HOME/.dagent/bin\""
        echo ""
        echo "  To do this immediately, run:"
        echo "    echo 'export PATH=\"\$PATH:\$HOME/.dagent/bin\"' >> ~/.zshrc"
        echo "    source ~/.zshrc"
        ;;
esac

echo ""
echo "======================================================================="
echo "                       Installation Complete!"
echo "======================================================================="
echo ""
echo "Please restart your terminal session or source your profile config."
echo "Then, run: dagent"
echo "======================================================================="
