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
$PIPX_PATH install ..
if [ $? -ne 0 ]; then
    echo '*** Failed to install "crystal"'
    exit 1
fi
CRYSTAL_PATH=$(which crystal)
if [ $? -ne 0 ]; then
    echo '*** Could not find installed "crystal" in PATH'
    exit 1
fi

# Locate Crystal's site-packages
CRYSTAL_PYTHON_PATH=$(dirname $(realpath $CRYSTAL_PATH))/python3
CRYSTAL_SITEPACKAGES_PATH=$(dirname $(dirname $($CRYSTAL_PYTHON_PATH -c 'import crystal; print(crystal.__file__)')))
if [ $? -ne 0 ]; then
    echo '*** Could not find site-packages for "crystal"'
    exit 1
fi

# Locate app icon
APPICON_PATH=$CRYSTAL_SITEPACKAGES_PATH/crystal/resources/appicon.png
if [ ! -f "$APPICON_PATH" ]; then
    echo "*** Could not find app icon at: $APPICON_PATH"
    exit 1
fi

# Build .desktop file
# NOTE: Cannot build to ./dist because . might be on a network drive
#       and upcoming sed commands will fail to "preserve permissions"
#       when working with a file on a network drive
cp media/crystal.desktop /tmp/crystal.desktop
sed -i -e "s|__CRYSTAL_PATH__|$CRYSTAL_PATH|g" /tmp/crystal.desktop
sed -i -e "s|__APPICON_PATH__|$APPICON_PATH|g" /tmp/crystal.desktop

# Install .desktop file to ~/.local/share/applications
# 
# NOTE: Only .desktop files opened from this directory will show their
#       icon in the dock correctly.
mv /tmp/crystal.desktop "$HOME/.local/share/applications/crystal.desktop"

# Install symlink to .desktop file to desktop
DESKTOP_FILE_PATH="$HOME/Desktop/crystal.desktop"
ln -s "$HOME/.local/share/applications/crystal.desktop" "$DESKTOP_FILE_PATH"

# Mark .desktop symlink on desktop as "Allow Launching"
# https://askubuntu.com/questions/1218954/desktop-files-allow-launching-set-this-via-cli
gio set "$DESKTOP_FILE_PATH" metadata::trusted true
chmod a+x "$DESKTOP_FILE_PATH"
