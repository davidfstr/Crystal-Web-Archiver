#!/bin/bash
# Verify that a macOS .app bundle contains all universal2 binaries.
# 
# Usage: verify_universal2.sh <APP_PATH>

set -e

APP_PATH="$1"
APP_NAME=$(basename "$APP_PATH")

# Find all binary files
BINARIES=$(find "$APP_PATH" -type f \( -name "*.so" -o -name "*.dylib" -o -perm +111 \) ! -name "*.sh" ! -name "*.pem" 2>/dev/null || true)
if [ -z "$BINARIES" ]; then
    echo "WARNING: No binaries found to check"
    exit 1
fi

# Identify any non-universal2 binaries
NON_UNIVERSAL2_BINARIES=""
for binary in $BINARIES; do
    # Get relative path for cleaner output
    REL_PATH="${binary#$APP_PATH/}"
    
    # Check what architectures the binary supports
    ARCH_INFO=$(file "$binary" 2>/dev/null || echo "")
    if [[ "$ARCH_INFO" == *"x86_64"* ]] && [[ "$ARCH_INFO" == *"arm64"* ]]; then
        :  # universal2; do nothing
    elif [[ "$ARCH_INFO" == *"x86_64"* ]]; then
        NON_UNIVERSAL2_BINARIES="$NON_UNIVERSAL2_BINARIES$REL_PATH - x86_64 only\n"
    elif [[ "$ARCH_INFO" == *"arm64"* ]]; then
        NON_UNIVERSAL2_BINARIES="$NON_UNIVERSAL2_BINARIES$REL_PATH - arm64 only\n"
    elif [ -n "$ARCH_INFO" ]; then
        NON_UNIVERSAL2_BINARIES="$NON_UNIVERSAL2_BINARIES$REL_PATH - unknown architecture\n"
    fi
done

if [ -n "$NON_UNIVERSAL2_BINARIES" ]; then
    echo "Non-universal binaries found:"
    echo -e "$NON_UNIVERSAL2_BINARIES"
    echo "*** $APP_NAME is NOT fully universal2"
    exit 1
fi
