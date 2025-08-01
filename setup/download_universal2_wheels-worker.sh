#!/bin/bash
# Downloads a universal2 wheel for a single requirement.
# 
# Usage: download_universal2_wheels-worker.sh <REQUIREMENT>
# 
# Input environment variables:
# - $BEST_UNIVERSAL2_PLATFORM
# - $BEST_X86_64_PLATFORM
# - $BEST_ARM64_PLATFORM

# Parse inputs
REQUIREMENT="$1"
if [ -z "$REQUIREMENT" ]; then
    echo "*** Usage: $0 <REQUIREMENT>"
    exit 1
fi
if [ -z "$BEST_UNIVERSAL2_PLATFORM" ] || [ -z "$BEST_X86_64_PLATFORM" ] || [ -z "$BEST_ARM64_PLATFORM" ]; then
    echo "*** Missing required environment variables: BEST_UNIVERSAL2_PLATFORM, BEST_X86_64_PLATFORM, BEST_ARM64_PLATFORM"
    exit 1
fi

# Download best universal2 or pure Python wheel, if available
echo "  ${REQUIREMENT}"
pip download --only-binary=:all: --dest .uwheels --no-deps "$REQUIREMENT" --platform "$BEST_UNIVERSAL2_PLATFORM" > /dev/null 2>&1
if [ $? -ne 0 ]; then
    REQUIREMENT_DONE=0
    mkdir .uwheels/forge/$REQUIREMENT
    
    # Download best x86_64 wheel, or fallback to source package if not available
    pip download --only-binary=:all: --dest .uwheels/forge/$REQUIREMENT --no-deps "$REQUIREMENT" --platform "$BEST_X86_64_PLATFORM" > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        pip download --no-binary=:all: --dest .uwheels --no-deps "$REQUIREMENT" > /dev/null 2>&1
        if [ $? -ne 0 ]; then
            echo "*** No wheel available for $REQUIREMENT on $BEST_X86_64_PLATFORM. No source package either."
            rm -rf .uwheels/forge/$REQUIREMENT
            exit 1
        fi
        REQUIREMENT_DONE=1
    fi

    if [ $REQUIREMENT_DONE -eq 0 ]; then
        # Download best arm64 wheel
        pip download --only-binary=:all: --dest .uwheels/forge/$REQUIREMENT --no-deps "$REQUIREMENT" --platform "$BEST_ARM64_PLATFORM" > /dev/null 2>&1
        if [ $? -ne 0 ]; then
            echo "*** No wheel available for $REQUIREMENT on $BEST_ARM64_PLATFORM."
            rm -rf .uwheels/forge/$REQUIREMENT
            exit 1
        fi
        
        # Merge the x86_64 and arm64 wheels into a universal2 wheel
        delocate-merge -w .uwheels .uwheels/forge/$REQUIREMENT/*.whl
        if [ $? -ne 0 ]; then
            echo "*** Could not merge wheels for $REQUIREMENT."
            rm -rf .uwheels/forge/$REQUIREMENT
            exit 1
        fi
    fi
    
    rm -rf .uwheels/forge/$REQUIREMENT
fi
