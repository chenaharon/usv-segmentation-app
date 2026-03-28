#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v pyinstaller &>/dev/null; then
  echo "pip install pyinstaller" >&2
  exit 1
fi
pyinstaller --noconfirm SegmentationAppPortable.spec
echo "Done. See dist/"
