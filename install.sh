#!/bin/bash

# A beautiful, automated installer for hypr-session

echo -e "\033[1;34m=======================================\033[0m"
echo -e "\033[1;36m    Installing hypr-session...         \033[0m"
echo -e "\033[1;34m=======================================\033[0m"

# 1. Verify pipx is installed
if ! command -v pipx &> /dev/null; then
    echo -e "\033[1;31m[ERROR] pipx is not installed.\033[0m"
    echo "Please install it first (e.g., 'sudo pacman -S python-pipx' or 'sudo apt install pipx')"
    exit 1
fi

# 2. Ensure the user's pipx binary path is in their config
pipx ensurepath > /dev/null 2>&1

# 3. Install the package globally
echo -e "\n\033[1;33m[1/2] Downloading and compiling package...\033[0m"
pipx install git+https://github.com/krishiv2489/hypr-session.git --force

# 4. Run the Python auto-injector using the absolute path (prevents "command not found" on fresh installs)
echo -e "\n\033[1;33m[2/2] Injecting hooks into hyprland.conf...\033[0m"
~/.local/bin/hypr-session install-hooks

echo -e "\n\033[1;32m✅ Installation Complete! hypr-session is now active.\033[0m"
echo "You can manually test it by typing: hypr-session status"