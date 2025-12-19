#!/bin/bash
# setup/install.sh

# --- Colors for output ---
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Starting installation for Magic Proxy...${NC}"

# --- 1. Check for Poetry ---
if ! command -v poetry &> /dev/null
then
    echo "Poetry could not be found. Installing Poetry..."
    # Using the recommended installer
    curl -sSL https://install.python-poetry.org | python3 -
    # Add poetry to PATH for the current session
    export PATH="$HOME/.local/bin:$PATH"
    echo -e "${GREEN}Poetry installed successfully.${NC}"
else
    echo "Poetry is already installed."
fi

# --- 2. Install Dependencies ---
echo -e "${YELLOW}Installing project dependencies using Poetry...${NC}"
poetry install

echo -e "${GREEN}Installation complete.${NC}"
