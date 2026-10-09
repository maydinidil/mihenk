#!/bin/sh
# Usage: packaging/macos/make_dmg.sh 0.0.1
set -eu
version="$1"
# The volume is built from a staging folder that holds the app and a link to /Applications, so the
# mounted disk shows mihenk.app next to the folder to drag it onto. With -srcfolder pointing at the
# bundle itself, its contents would land at the root of the volume instead.
staging="$(mktemp -d "${TMPDIR:-/tmp}/mihenk-dmg.XXXXXX")"
trap 'rm -rf "$staging"' EXIT
ditto "dist/mihenk.app" "$staging/mihenk.app"
ln -s /Applications "$staging/Applications"
hdiutil create -volname "mihenk" -srcfolder "$staging" -ov -format UDZO \
  "dist/mihenk-${version}-macos-arm64.dmg"
