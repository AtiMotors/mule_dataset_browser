#!/bin/bash
set -e

REPO_URL="${REPO_URL:-https://github.com/AtiMotors/mule_dataset_browser}"
BINARY_NAME="browse_data"
DEFAULT_INSTALL_DIR="/usr/local/bin"

echo "Installing $BINARY_NAME..."

echo "Checking prerequisites..."
command -v git >/dev/null 2>&1 || {
    echo "Error: git not found"
    exit 1
}
command -v ssh >/dev/null 2>&1 || {
    echo "Error: ssh not found. SSH mode will not work."
}
command -v rsync >/dev/null 2>&1 || {
    echo "Error: rsync not found. Downloading datasets (Fetch) will not work."
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

detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        case "$ID" in
            ubuntu | debian | linuxmint | pop)
                echo "ubuntu"
                ;;
            *)
                echo "other"
                ;;
        esac
    elif [ "$(uname)" = "Darwin" ]; then
        echo "macos"
    else
        echo "other"
    fi
}

OS=$(detect_os)

if [ "$OS" = "ubuntu" ]; then
    if apt list --installed 2>/dev/null | grep -q "^python3-textual/"; then
        echo "Using system python3-textual"
    elif command -v apt >/dev/null 2>&1 && [ "$(id -u)" -eq 0 ]; then
        apt install -y python3-textual 2>/dev/null || pip install textual --quiet
    elif command -v apt >/dev/null 2>&1; then
        echo "Trying to install python3-textual (may require sudo)..."
        sudo apt install -y python3-textual 2>/dev/null || pip install textual --quiet
    else
        pip install textual --quiet
    fi
elif [ "$OS" = "macos" ]; then
    pip install textual --quiet 2>/dev/null || pip3 install textual --quiet
else
    pip install textual --quiet 2>/dev/null || pip3 install textual --quiet
fi

if [ ! -f "$BINARY_NAME" ]; then
    echo "Error: Binary '$BINARY_NAME' not found in repository"
    rm -rf "$TEMP_DIR"
    exit 1
fi

INSTALL_DIR="/usr/local/bin"

echo ""
echo "Installing to $INSTALL_DIR (requires sudo)..."
sudo -v

echo "sudo cp $BINARY_NAME $INSTALL_DIR/"
sudo cp "$BINARY_NAME" "$INSTALL_DIR/"
echo "sudo chmod +x $INSTALL_DIR/$BINARY_NAME"
sudo chmod +x "$INSTALL_DIR/$BINARY_NAME"

rm -rf "$TEMP_DIR"

echo ""
echo "Installed to: $INSTALL_DIR/$BINARY_NAME"

PATH_LINE="export PATH=\"\$PATH:$INSTALL_DIR\""
if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
    echo ""
    echo "WARNING: $INSTALL_DIR is not in your PATH"
    echo "Add this to your ~/.bashrc or ~/.zshrc:"
    echo "  $PATH_LINE"
fi

echo ""
echo "Done! Run '$BINARY_NAME' to start."
