#!/usr/bin/env bash
# 
# Installs Crystal and places an icon for it on the desktop.
# 

# Look for pipx
PIPX_PATH=$(which pipx)
if [ $? -ne 0 ]; then
    # Look for python3
    PYTHON_PATH=$(which python3)
    if [ $? -ne 0 ]; then
        echo '*** "python3" not found. Please install it and try again.'
        exit 1
    fi
    
    # Ensure python3 is not in a Poetry virtualenv
    if [[ "$PYTHON_PATH" == *"/pypoetry/"* ]]; then
        echo '*** Must run this script outside of a Poetry shell. Run "exit" and try again.'
        exit 1
    fi
    
    # Try to install pipx
    echo "Installing pipx..."
    $PYTHON_PATH -m pip install --user pipx
    if [ $? -ne 0 ]; then
        echo '*** Failed to install "pipx". Please install it manually and try again.'
        exit 1
    fi
    # Extend PATH with likely location of pipx, which might not already be on PATH
    export PATH="$PATH:$HOME/.local/bin"
    PIPX_PATH=$(which pipx)
    if [ $? -ne 0 ]; then
        echo '*** Could not find "pipx" in PATH'
        exit 1
    fi
fi

# Ensure pipx is not in a Poetry virtualenv
if [[ "$PIPX_PATH" == *"/pypoetry/"* ]]; then
    echo '*** Must run this script outside of a Poetry shell. Run "exit" and try again.'
    exit 1
fi

# Install Crystal to ~/.local/bin with pipx
echo "Installing crystal..."
$PIPX_PATH install --force ..
if [ $? -ne 0 ]; then
    echo '*** Failed to install "crystal"'
    exit 1
fi
CRYSTAL_PATH=$(which crystal)
if [ $? -ne 0 ]; then
    echo '*** Could not find installed "crystal" in PATH'
    exit 1
fi

# Install Crystal to desktop environment
$CRYSTAL_PATH --install-to-desktop
