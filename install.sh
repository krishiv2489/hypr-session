#!/bin/bash

# A beautiful, automated installer for hypr-session

echo -e "\033[1;34m=======================================\033[0m"
echo -e "\033[1;36m    Installing hypr-session...         \033[0m"
echo -e "\033[1;34m=======================================\033[0m"

# 1. Verify hyprctl is installed
if ! command -v hyprctl &> /dev/null; then
    echo -e "\033[1;31m[ERROR] hyprctl is not found.\033[0m"
    echo "This tool requires Hyprland to be installed and running."
    exit 1
fi

# 2. Verify pipx is installed
if ! command -v pipx &> /dev/null; then
    echo -e "\033[1;31m[ERROR] pipx is not installed.\033[0m"
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        case $ID in
            arch|manjaro|endeavouros|artix)
                echo "Please install it: sudo pacman -S python-pipx"
                ;;
            ubuntu|debian|pop)
                echo "Please install it: sudo apt install pipx"
                ;;
            fedora)
                echo "Please install it: sudo dnf install pipx"
                ;;
            *)
                echo "Please install 'pipx' using your package manager."
                ;;
        esac
    else
        echo "Please install 'pipx' using your package manager."
    fi
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