#!/bin/sh
set -u

BASE_URL="https://raw.githubusercontent.com/keggy6893/SafeUpdate2026/r33-dev"
META_URL="$BASE_URL/latest-r33-test.json"
TMPDIR="/tmp/safeupdate2026-r33-test-install"
ZIPFILE="$TMPDIR/package.zip"
EXTRACT="$TMPDIR/extract"
PLUGIN_DIR="/usr/lib/enigma2/python/Plugins/Extensions/SafeUpdate2026"
BACKUP_DIR="/tmp/safeupdate2026-before-r33-test"
LEGACY_BACKUP_DIR="/usr/lib/enigma2/python/Plugins/Extensions/SafeUpdate2026.before-install"

say() { echo "[SafeUpdate2026 r33 TEST] $*"; }
fail() { say "FEHLER: $*"; exit 1; }

fetch() {
    url="$1"; out="$2"
    if command -v wget >/dev/null 2>&1; then
        wget -q -O "$out" "$url"
    elif command -v curl >/dev/null 2>&1; then
        curl -fsSL "$url" -o "$out"
    else
        return 127
    fi
}

json_value() {
    key="$1"
    python3 - "$TMPDIR/latest.json" "$key" <<'PY'
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
    data = json.load(f)
print(data[sys.argv[2]])
PY
}

sha256_file() {
    python3 - "$1" <<'PY'
import hashlib, sys
h = hashlib.sha256()
with open(sys.argv[1], "rb") as f:
    for block in iter(lambda: f.read(1024 * 1024), b""):
        h.update(block)
print(h.hexdigest())
PY
}

syntax_check() {
    python3 - "$1" <<'PY'
import sys
p = sys.argv[1]
with open(p, "rb") as f:
    compile(f.read(), p, "exec")
PY
}

extract_zip() {
    if command -v unzip >/dev/null 2>&1; then
        unzip -q -o "$ZIPFILE" -d "$EXTRACT"
    else
        python3 -m zipfile -e "$ZIPFILE" "$EXTRACT"
    fi
}

command -v python3 >/dev/null 2>&1 || fail "python3 fehlt."
command -v wget >/dev/null 2>&1 || command -v curl >/dev/null 2>&1 || fail "weder wget noch curl vorhanden."

rm -rf "$TMPDIR" "$BACKUP_DIR" "$LEGACY_BACKUP_DIR"
mkdir -p "$EXTRACT" || fail "Temp-Verzeichnis konnte nicht erstellt werden."

say "Lade r33-Testinformationen..."
fetch "$META_URL" "$TMPDIR/latest.json" || fail "Test-Manifest konnte nicht geladen werden."
VERSION=$(json_value version) || fail "Version konnte nicht gelesen werden."
MODE=$(json_value mode) || fail "Installationsmodus konnte nicht gelesen werden."
[ "$MODE" = "full" ] || fail "Unerwarteter Installationsmodus: $MODE"
DOWNLOAD=$(json_value download) || fail "Download-URL konnte nicht gelesen werden."
EXPECTED=$(json_value sha256) || fail "SHA256 konnte nicht gelesen werden."
say "Version: $VERSION"

say "Lade Testpaket..."
fetch "$DOWNLOAD" "$ZIPFILE" || fail "Testpaket konnte nicht geladen werden."
ACTUAL=$(sha256_file "$ZIPFILE") || fail "SHA256-Pruefung fehlgeschlagen."
[ "$ACTUAL" = "$EXPECTED" ] || fail "SHA256 stimmt nicht. Installation abgebrochen."
say "SHA256: OK"

say "Entpacke Testpaket..."
extract_zip || fail "Entpacken fehlgeschlagen."
PACKAGE_DIR="$EXTRACT/SafeUpdate2026"
[ -d "$PACKAGE_DIR" ] || fail "SafeUpdate2026-Verzeichnis fehlt."
[ -f "$PACKAGE_DIR/plugin.py" ] || fail "plugin.py fehlt."
[ -f "$PACKAGE_DIR/__init__.py" ] || fail "__init__.py fehlt."
syntax_check "$PACKAGE_DIR/plugin.py" || fail "Python-Syntaxpruefung fehlgeschlagen."
say "Python-Syntax: OK"

rm -rf "$PACKAGE_DIR/__pycache__"
find "$PACKAGE_DIR" -name '*.pyc' -delete 2>/dev/null || true

if [ -d "$PLUGIN_DIR" ]; then
    say "Sichere vorhandene Installation..."
    cp -a "$PLUGIN_DIR" "$BACKUP_DIR" || fail "Backup der alten Installation fehlgeschlagen."
fi

say "Installiere $VERSION..."
rm -rf "$PLUGIN_DIR"
if ! cp -a "$PACKAGE_DIR" "$PLUGIN_DIR"; then
    say "Installation fehlgeschlagen - Rollback..."
    rm -rf "$PLUGIN_DIR"
    [ -d "$BACKUP_DIR" ] && cp -a "$BACKUP_DIR" "$PLUGIN_DIR"
    fail "Installation fehlgeschlagen."
fi

if ! syntax_check "$PLUGIN_DIR/plugin.py"; then
    say "Installierte Datei ist fehlerhaft - Rollback..."
    rm -rf "$PLUGIN_DIR"
    [ -d "$BACKUP_DIR" ] && cp -a "$BACKUP_DIR" "$PLUGIN_DIR"
    fail "Syntaxpruefung nach Installation fehlgeschlagen."
fi

rm -rf "$BACKUP_DIR" "$LEGACY_BACKUP_DIR" "$TMPDIR"
sync
say "$VERSION wurde erfolgreich installiert."
say "Enigma2 wird neu gestartet..."
init 4
sleep 3
init 3
