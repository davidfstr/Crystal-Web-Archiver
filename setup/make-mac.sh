#!/bin/sh

VERSION=`python -c 'import sys; sys.path.append("../src"); import crystal; print(crystal.__version__)'`

rm -rf build dist dist-mac

# Build .app
echo "Building .app..."
if [ "$1" != "--app-only" ]; then
    GRAPH_OPT=""
else
    # --graph: Generates a GraphViz .dot file in the build directory that shows
    #          the calculated module dependency graph
    GRAPH_OPT="--graph"
fi
python setup.py py2app $GRAPH_OPT > py2app.stdout.log 2> py2app.stderr.log
if [ $? -ne 0 ]; then
    echo "ERROR: py2app build failed. Aborting. See py2app.stderr.log and py2app.stdout.log for details."
    exit 1
fi

# Slim .app
echo "Slimming .app..."
rm -r dist/Crystal.app/Contents/Resources/lib/python3.*/wx/locale/*

# Codesign if signing certificate is available in the keychain and environment variables are set
if [ -n "$CERTIFICATE_NAME" ] && security find-identity -v -p codesigning | grep -q "$CERTIFICATE_NAME"; then
    if [ -z "$APPLE_ID" ] || [ -z "$APPLE_TEAM_ID" ] || [ -z "$APPLE_APP_SPECIFIC_PASSWORD" ]; then
        echo "ERROR: Codesigning environment variables not set. Aborting."
        exit 1
    fi
    
    APP_PATH="dist/Crystal.app"
    
    # Sign all .so and .dylib files in the app bundle
    echo "Signing all .so and .dylib files in the app bundle..."
    find "$APP_PATH" -type f \( -name "*.so" -o -name "*.dylib" \) -exec sh -c '
        codesign --force --options runtime --timestamp --sign "$CERTIFICATE_NAME" "$0" > /dev/null 2>&1 || exit 255
    ' {} \;
    CODESIGN_EXIT_CODE=$?
    if [ $CODESIGN_EXIT_CODE -ne 0 ]; then
        echo "ERROR: codesign failed for at least one .so or .dylib file. Aborting."
        exit 1
    fi
    
    # Codesign the .app
    echo "Codesigning .app..."
    codesign --deep --force --options runtime --timestamp --sign "$CERTIFICATE_NAME" "$APP_PATH" > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        echo "ERROR: Codesign failed. Aborting."
        exit 1
    fi
    
    # Notarize the .app
    echo "Notarizing .app..."
    ditto -c -k --sequesterRsrc --keepParent "$APP_PATH" "$APP_PATH.zip"
    NOTARY_OUT=$(mktemp)
    xcrun notarytool submit "$APP_PATH.zip" \
        --apple-id "$APPLE_ID" \
        --team-id "$APPLE_TEAM_ID" \
        --password "$APPLE_APP_SPECIFIC_PASSWORD" \
        --wait | tee "$NOTARY_OUT"
    NOTARY_SUBMIT_EXIT_CODE=$?
    NOTARY_ID=$(grep -Eo 'id: [a-f0-9\-]+' "$NOTARY_OUT" | head -1 | awk '{print $2}')
    if [ -n "$NOTARY_ID" ]; then
        # Only show notarization log if requested via CI input
        if [ "${SHOW_NOTARIZATION_LOG:-false}" = "true" ]; then
            echo "Fetching notarization log for submission ID: $NOTARY_ID"
            xcrun notarytool log "$NOTARY_ID" \
                --apple-id "$APPLE_ID" \
                --team-id "$APPLE_TEAM_ID" \
                --password "$APPLE_APP_SPECIFIC_PASSWORD"
        fi
    fi
    if [ $NOTARY_SUBMIT_EXIT_CODE -ne 0 ]; then
        echo "ERROR: Notarization failed. Aborting."
        exit 1
    fi
    rm "$APP_PATH.zip"
    
    # Staple the ticket
    echo "Stapling notarization ticket..."
    xcrun stapler staple "$APP_PATH"
    if [ $? -ne 0 ]; then
        echo "ERROR: Stapling failed. Aborting."
        exit 1
    fi
fi

# Build .dmg
mkdir dist-mac
if [ "$1" != "--app-only" ]; then
    echo 'Building disk image... (skip with --app-only option)'
    # -format UDBZ: Use bzip2 compression, which produces smaller images
    #               than zlib compression (UDZO), even with zlib-level=9
    hdiutil create -srcfolder dist -volname "Crystal" -format UDBZ dist-mac/crystal-mac-$VERSION.dmg
fi

