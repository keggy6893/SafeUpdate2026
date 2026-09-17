#!/bin/sh
set -u

BASE_URL="https://raw.githubusercontent.com/keggy6893/SafeUpdate2026/main"
META_URL="$BASE_URL/latest.json"
TMPDIR="/tmp/safeupdate2026-install"
ZIPFILE="$TMPDIR/SafeUpdate2026.zip"
EXTRACT="$TMPDIR/extract"
PLUGIN_DIR="/usr/lib/enigma2/python/Plugins/Extensions/SafeUpdate2026"
BACKUP_DIR="/usr/lib/enigma2/python/Plugins/Extensions/SafeUpdate2026.before-install"

say() { echo "[SafeUpdate2026] $*"; }
fail() { say "FEHLER: $*"; exit 1; }

fetch() {
    url="$1"
    out="$2"
    if command -v wget >/dev/null 2>&1; then
        wget -q -O "$out" "$url"
    elif command -v curl >/dev/null 2>&1; then
        curl -fsSL "$url" -o "$out"
    else
        return 127
    fi
}

command -v python3 >/dev/null 2>&1 || fail "python3 fehlt."
command -v wget >/dev/null 2>&1 || command -v curl >/dev/null 2>&1 || fail "weder wget noch curl vorhanden."

rm -rf "$TMPDIR"
mkdir -p "$EXTRACT" || fail "Temp-Verzeichnis konnte nicht erstellt werden."

say "Lade Versionsinformationen..."
fetch "$META_URL" "$TMPDIR/latest.json" || fail "latest.json konnte nicht geladen werden."

VERSION=$(python3 -c 'import json; print(json.load(open("/tmp/safeupdate2026-install/latest.json"))["version"])') || fail "Version konnte nicht gelesen werden."
DOWNLOAD=$(python3 -c 'import json; print(json.load(open("/tmp/safeupdate2026-install/latest.json"))["download"])') || fail "Download-URL konnte nicht gelesen werden."
EXPECTED=$(python3 -c 'import json; print(json.load(open("/tmp/safeupdate2026-install/latest.json"))["sha256"])') || fail "SHA256 konnte nicht gelesen werden."

say "Version: $VERSION"
say "Lade Plugin..."
fetch "$DOWNLOAD" "$ZIPFILE" || fail "Plugin-ZIP konnte nicht geladen werden."

ACTUAL=$(python3 -c 'import hashlib; print(hashlib.sha256(open("/tmp/safeupdate2026-install/SafeUpdate2026.zip","rb").read()).hexdigest())') || fail "SHA256-Pruefung fehlgeschlagen."
[ "$ACTUAL" = "$EXPECTED" ] || fail "SHA256 stimmt nicht. Installation abgebrochen."
say "SHA256: OK"

say "Entpacke Plugin..."
if command -v unzip >/dev/null 2>&1; then
    unzip -q -o "$ZIPFILE" -d "$EXTRACT" || fail "Entpacken fehlgeschlagen."
else
    python3 -m zipfile -e "$ZIPFILE" "$EXTRACT" || fail "Entpacken fehlgeschlagen."
fi

[ -f "$EXTRACT/SafeUpdate2026/plugin.py" ] || fail "plugin.py fehlt im Paket."
python3 -m py_compile "$EXTRACT/SafeUpdate2026/plugin.py" || fail "Python-Syntaxpruefung des Downloads fehlgeschlagen."
say "Python-Syntax: OK"

rm -rf "$BACKUP_DIR"
if [ -d "$PLUGIN_DIR" ]; then
    say "Sichere vorhandene Installation..."
    cp -a "$PLUGIN_DIR" "$BACKUP_DIR" || fail "Backup der alten Installation fehlgeschlagen."
fi

say "Installiere SafeUpdate2026..."
rm -rf "$PLUGIN_DIR"
if ! cp -a "$EXTRACT/SafeUpdate2026" "$PLUGIN_DIR"; then
    say "Installation fehlgeschlagen - versuche Rollback..."
    rm -rf "$PLUGIN_DIR"
    [ -d "$BACKUP_DIR" ] && cp -a "$BACKUP_DIR" "$PLUGIN_DIR"
    fail "Installation fehlgeschlagen."
fi

if ! python3 -m py_compile "$PLUGIN_DIR/plugin.py"; then
    say "Installierte Datei ist fehlerhaft - Rollback..."
    rm -rf "$PLUGIN_DIR"
    [ -d "$BACKUP_DIR" ] && cp -a "$BACKUP_DIR" "$PLUGIN_DIR"
    fail "Syntaxpruefung nach Installation fehlgeschlagen."
fi

sync
rm -rf "$TMPDIR"
say "SafeUpdate2026 $VERSION wurde erfolgreich installiert."
say "Enigma2 wird neu gestartet..."
init 4
sleep 3
init 3
