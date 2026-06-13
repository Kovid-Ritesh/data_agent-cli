#!/bin/sh
# install.sh — DataAgent CLI installer for macOS / Linux

set -e

INSTALL_DIR="$HOME/.dagent/bin"
EXE_PATH="$INSTALL_DIR/dagent"
DOWNLOAD_URL="https://github.com/your-username/dataagent-cli/releases/latest/download/dagent"

echo "Installing DataAgent CLI..."

mkdir -p "$INSTALL_DIR"

if [ -f "$EXE_PATH" ]; then
    rm -f "$EXE_PATH"
fi

echo "Downloading dagent from $DOWNLOAD_URL..."
if curl -s -L -f -o "$EXE_PATH" "$DOWNLOAD_URL"; then
    chmod +x "$EXE_PATH"
    echo "✓ Downloaded dagent successfully."
else
    echo "⚠ Download could not complete (e.g. if release is not published yet)."
    echo "You can manually copy your built 'dagent' binary to: $EXE_PATH"
fi

# Suggest adding to path
case :$PATH: in
    *:$INSTALL_DIR:*) ;;
    *) 
        echo ""
        echo "Please add the installation directory to your PATH."
        echo "Add the following line to your ~/.bashrc or ~/.zshrc:"
        echo "  export PATH=\"\$PATH:\$HOME/.dagent/bin\""
        ;;
esac

echo ""
echo "✓ DataAgent v1.0.0 installation sequence completed!"
echo "Please restart your terminal shell or reload configuration, then run 'dagent'."
