#!/bin/bash
set -e

REPO_URL="${REPO_URL:-https://github.com/AtiMotors/mule_dataset_browser}"
BINARY_NAME="browse_data"
DEFAULT_INSTALL_DIR="$HOME/.local/bin"

echo "Installing $BINARY_NAME..."

echo "Checking prerequisites..."
command -v python3 >/dev/null 2>&1 || {
    echo "Error: python3 not found"
    exit 1
}
command -v pip >/dev/null 2>&1 || {
    echo "Error: pip not found"
    exit 1
}

echo "Cloning repository..."
TEMP_DIR=$(mktemp -d)
git clone --depth 1 "$REPO_URL" "$TEMP_DIR" 2>/dev/null || {
    echo "Error: Failed to clone repository"
    rm -rf "$TEMP_DIR"
    exit 1
}

cd "$TEMP_DIR"

echo "Installing dependencies..."
pip install -r requirements.txt --quiet 2>/dev/null || pip install textual --quiet

if [ ! -f "$BINARY_NAME" ]; then
    echo "Error: Binary '$BINARY_NAME' not found in repository"
    rm -rf "$TEMP_DIR"
    exit 1
fi

echo -n "Enter install path [$DEFAULT_INSTALL_DIR]: "
read -r INSTALL_DIR
INSTALL_DIR="${INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"

mkdir -p "$INSTALL_DIR"

cp "$BINARY_NAME" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/$BINARY_NAME"

rm -rf "$TEMP_DIR"

echo ""
echo "Installed to: $INSTALL_DIR/$BINARY_NAME"

PATH_LINE="export PATH=\"\$PATH:$INSTALL_DIR\""
if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
    echo ""
    echo "WARNING: $INSTALL_DIR is not in your PATH"
    echo "Add this to your ~/.bashrc or ~/.zshrc:"
    echo "  $PATH_LINE"
    echo ""
    echo "Or add to PATH now? (y/n)"
    read -r ADD_TO_PATH
    if [ "$ADD_TO_PATH" = "y" ] || [ "$ADD_TO_PATH" = "Y" ]; then
        export PATH="$PATH:$INSTALL_DIR"
        if [ -n "$BASH_VERSION" ]; then
            echo "$PATH_LINE" >>~/.bashrc
        elif [ -n "$ZSH_VERSION" ]; then
            echo "$PATH_LINE" >>~/.zshrc
        fi
        echo "Added to PATH in shell config"
    fi
fi

echo ""
echo "Done! Run '$BINARY_NAME' to start."

