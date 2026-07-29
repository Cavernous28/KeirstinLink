#!/bin/bash
# Install KeirstinLink Python backend on Linux (Bazzite, Fedora, Arch, etc.)
# Run: bash install-keirstinlink-linux.sh

set -e

REPO_DIR="$HOME/KeirstinLink"
DATA_DIR="$HOME/.local/share/KeirstinLink/data"

echo "=== KeirstinLink Linux Install ==="

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "python3 not found. Install it first."
    exit 1
fi

# Clone or update repo
if [ -d "$REPO_DIR" ]; then
    echo "Updating existing KeirstinLink repo at $REPO_DIR..."
    cd "$REPO_DIR" && git pull
else
    echo "Cloning KeirstinLink to $REPO_DIR..."
    git clone https://github.com/Cavernous28/KeirstinLink.git "$REPO_DIR"
fi

# Install Python dependencies
cd "$REPO_DIR/src-python"
python3 -m pip install --user -r requirements.txt

# Create data directory
mkdir -p "$DATA_DIR"

# Create default sync folders
mkdir -p "$HOME/KeirstinLinkSync"
mkdir -p "$HOME/KeirstinLinkMaster"

echo ""
echo "Install complete."
echo "Start KeirstinLink with: $REPO_DIR/linux/keirstinlink-launch.sh"
