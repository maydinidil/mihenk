#!/bin/sh
# Usage: packaging/macos/make_dmg.sh 0.0.1
set -eu
version="$1"
hdiutil create -volname "mihenk" -srcfolder "dist/mihenk.app" -ov -format UDZO \
  "dist/mihenk-${version}-macos-arm64.dmg"
