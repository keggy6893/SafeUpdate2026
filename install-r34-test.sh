#!/bin/sh
set -eu

BASE="https://raw.githubusercontent.com/keggy6893/SafeUpdate2026/r34-dev"
META_URL="$BASE/latest-r34-test.json"
TMP="/tmp/safeupdate2026-r34-test.$$"
PLUGIN_DIR="/usr/lib/enigma2/python/Plugins/Extensions/SafeUpdate2026"
HELPER="/usr/bin/safeupdate-recover"
ROLLBACK="/tmp/safeupdate2026-before-r34-test"
HELPER_OLD="/tmp/safeupdate-recover.before-r34-test"

cleanup() {
    rm -rf "$TMP" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo '[SafeUpdate2026] r34 Crash-Recovery Testinstaller'
mkdir -p "$TMP"
wget -qO "$TMP/latest.json" "$META_URL"

VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$TMP/latest.json")"
DOWNLOAD="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["download"])' "$TMP/latest.json")"
EXPECTED_SHA="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sha256"])' "$TMP/latest.json")"

printf '[SafeUpdate2026] Version: %s\n' "$VERSION"
wget -qO "$TMP/package.zip" "$DOWNLOAD"
ACTUAL_SHA="$(sha256sum "$TMP/package.zip" | awk '{print $1}')"
[ "$ACTUAL_SHA" = "$EXPECTED_SHA" ] || {
    echo '[SafeUpdate2026] ABBRUCH: SHA256-Prüfung fehlgeschlagen.' >&2
    exit 1
}
echo '[SafeUpdate2026] SHA256: OK'

unzip -q "$TMP/package.zip" -d "$TMP/unpacked"
SOURCE="$TMP/unpacked/SafeUpdate2026"
[ -f "$SOURCE/plugin.py" ] || { echo 'plugin.py fehlt' >&2; exit 1; }
[ -f "$SOURCE/safeupdate-recover" ] || { echo 'Recovery-Helfer fehlt' >&2; exit 1; }

python3 -m py_compile "$SOURCE/plugin.py" "$SOURCE/safeupdate-recover"
echo '[SafeUpdate2026] Python-Syntax: OK'

rm -rf "$ROLLBACK"
if [ -d "$PLUGIN_DIR" ]; then
    cp -a "$PLUGIN_DIR" "$ROLLBACK"
fi
rm -f "$HELPER_OLD"
if [ -f "$HELPER" ]; then
    cp -a "$HELPER" "$HELPER_OLD"
fi

rm -rf "$PLUGIN_DIR"
cp -a "$SOURCE" "$PLUGIN_DIR"
cp -a "$SOURCE/safeupdate-recover" "$HELPER"
chmod 0755 "$HELPER"

if ! python3 -m py_compile "$PLUGIN_DIR/plugin.py" "$HELPER"; then
    echo '[SafeUpdate2026] Installation fehlgeschlagen – Rollback.' >&2
    rm -rf "$PLUGIN_DIR"
    [ -d "$ROLLBACK" ] && cp -a "$ROLLBACK" "$PLUGIN_DIR"
    rm -f "$HELPER"
    [ -f "$HELPER_OLD" ] && cp -a "$HELPER_OLD" "$HELPER"
    exit 1
fi

echo '[SafeUpdate2026] r34-dev1 installiert.'
echo '[SafeUpdate2026] Recovery-Befehl: safeupdate-recover'
echo '[SafeUpdate2026] Enigma2 wird neu gestartet ...'
init 4
sleep 3
init 3
