#!/usr/bin/env bash
set -euo pipefail

APP_NAME="USV Segmentation (v1.0.2) - Portable"
APP_BUNDLE="dist/${APP_NAME}.app"
DMG_NAME="USV Segmentation Setup (v1.0.2).dmg"

echo "==> Installing build dependencies"
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt pyinstaller

echo "==> Cleaning previous portable output"
rm -rf build dist "dist_installer_macos"

echo "==> Building macOS .app (onedir)"
pyinstaller "SegmentationAppPortable.spec" --noconfirm --clean

if [[ ! -d "${APP_BUNDLE}" ]]; then
  echo "Build failed: ${APP_BUNDLE} was not produced." >&2
  exit 1
fi

echo "==> Build complete: ${APP_BUNDLE}"

echo "==> Creating installer-like DMG"
mkdir -p dist_installer_macos
rm -f "dist_installer_macos/${DMG_NAME}"
hdiutil create \
  -volname "${APP_NAME}" \
  -srcfolder "${APP_BUNDLE}" \
  -ov \
  -format UDZO \
  "dist_installer_macos/${DMG_NAME}"

echo "==> DMG ready: dist_installer_macos/${DMG_NAME}"
echo "Optional: codesign and notarize .app/.dmg before external distribution."
