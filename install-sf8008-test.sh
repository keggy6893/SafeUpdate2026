#!/bin/sh
set -eu

BASE="https://raw.githubusercontent.com/keggy6893/SafeUpdate2026/local-sf8008-test"
META_URL="$BASE/latest-sf8008-test.json"
TMP="/tmp/safeupdate2026-sf8008-test.$$"
ROLLBACK="/tmp/safeupdate2026-before-sf8008-test"

cleanup() {
    rm -rf "$TMP" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

printf '%s\n' '[SafeUpdate2026] Octagon SF8008 Hardware-Testinstaller'

CMDLINE="$(cat /proc/cmdline 2>/dev/null || true)"
case " $CMDLINE " in
    *" MACHINEBUILD=sf8008 "*) : ;;
    *)
        echo '[SafeUpdate2026] ABBRUCH: Diese Testversion ist ausschließlich für MACHINEBUILD=sf8008.' >&2
        exit 1
        ;;
esac
case " $CMDLINE " in
    *" OEM=octagon "*) : ;;
    *)
        echo '[SafeUpdate2026] ABBRUCH: OEM=octagon wurde nicht erkannt.' >&2
        exit 1
        ;;
esac

mkdir -p "$TMP"
wget -qO "$TMP/latest.json" "$META_URL"

VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$TMP/latest.json")"
DOWNLOAD="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["download"])' "$TMP/latest.json")"
EXPECTED_SHA="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sha256"])' "$TMP/latest.json")"
PLUGIN_DIR="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["plugin_dir"])' "$TMP/latest.json")"

printf '[SafeUpdate2026] Version: %s\n' "$VERSION"
wget -qO "$TMP/package.zip" "$DOWNLOAD"
ACTUAL_SHA="$(sha256sum "$TMP/package.zip" | awk '{print $1}')"
if [ "$ACTUAL_SHA" != "$EXPECTED_SHA" ]; then
    echo '[SafeUpdate2026] ABBRUCH: SHA256-Prüfung fehlgeschlagen.' >&2
    exit 1
fi
echo '[SafeUpdate2026] SHA256: OK'

unzip -q "$TMP/package.zip" -d "$TMP/unpacked"
SOURCE="$TMP/unpacked/SafeUpdate2026"
if [ ! -f "$SOURCE/plugin.py" ]; then
    echo '[SafeUpdate2026] ABBRUCH: plugin.py fehlt im Paket.' >&2
    exit 1
fi
python3 -m py_compile "$SOURCE/plugin.py"
echo '[SafeUpdate2026] Python-Syntax: OK'

rm -rf "$ROLLBACK"
if [ -d "$PLUGIN_DIR" ]; then
    cp -a "$PLUGIN_DIR" "$ROLLBACK"
    echo '[SafeUpdate2026] Vorheriger Pluginstand unter /tmp gesichert.'
fi

rm -rf "$PLUGIN_DIR"
mkdir -p "$(dirname "$PLUGIN_DIR")"
cp -a "$SOURCE" "$PLUGIN_DIR"

if ! python3 -m py_compile "$PLUGIN_DIR/plugin.py"; then
    echo '[SafeUpdate2026] Installation fehlgeschlagen – stelle vorherigen Stand wieder her.' >&2
    rm -rf "$PLUGIN_DIR"
    if [ -d "$ROLLBACK" ]; then
        cp -a "$ROLLBACK" "$PLUGIN_DIR"
    fi
    exit 1
fi

echo '[SafeUpdate2026] SF8008-Teststand installiert.'
echo '[SafeUpdate2026] Enigma2 wird neu gestartet ...'
init 4
sleep 3
init 3
