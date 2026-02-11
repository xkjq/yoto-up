#!/bin/bash
# Create macOS DMG from PyInstaller output
set -e

APP_NAME="Yoto-UP"
DMG_NAME="YotoUP.dmg"
DIST_DIR="dist"

# Create a temporary directory for DMG contents
mkdir -p "${DIST_DIR}/dmg"
cp -r "${DIST_DIR}/${APP_NAME}.app" "${DIST_DIR}/dmg/"

# Create DMG
hdiutil create -volname "${APP_NAME}" -srcfolder "${DIST_DIR}/dmg" -ov -format UDZO "${DIST_DIR}/${DMG_NAME}"

# Cleanup
rm -rf "${DIST_DIR}/dmg"

echo "DMG created: ${DIST_DIR}/${DMG_NAME}"
