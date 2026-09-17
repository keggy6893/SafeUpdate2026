#!/bin/sh
set -u

BASE_URL="https://raw.githubusercontent.com/keggy6893/SafeUpdate2026/main"
META_URL="$BASE_URL/latest.json"
TMPDIR="/tmp/safeupdate2026-install"
ZIPFILE="$TMPDIR/base.zip"
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

json_value() {
    key="$1"
    python3 - "$TMPDIR/latest.json" "$key" <<'PY'
import json, sys
with open(sys.argv[1], 'r') as f:
    data = json.load(f)
value = data[sys.argv[2]]
if isinstance(value, (dict, list)):
    raise SystemExit(2)
print(value)
PY
}

sha256_file() {
    python3 - "$1" <<'PY'
import hashlib, sys
h = hashlib.sha256()
with open(sys.argv[1], 'rb') as f:
    while True:
        b = f.read(1024 * 1024)
        if not b:
            break
        h.update(b)
print(h.hexdigest())
PY
}

syntax_check() {
    python3 - "$1" <<'PY'
import sys
p = sys.argv[1]
with open(p, 'rb') as f:
    source = f.read()
compile(source, p, 'exec')
PY
}

command -v python3 >/dev/null 2>&1 || fail "python3 fehlt."
command -v wget >/dev/null 2>&1 || command -v curl >/dev/null 2>&1 || fail "weder wget noch curl vorhanden."

rm -rf "$TMPDIR"
mkdir -p "$EXTRACT" || fail "Temp-Verzeichnis konnte nicht erstellt werden."

say "Lade Versionsinformationen..."
fetch "$META_URL" "$TMPDIR/latest.json" || fail "latest.json konnte nicht geladen werden."

VERSION=$(json_value version) || fail "Version konnte nicht gelesen werden."
MODE=$(json_value mode) || fail "Installationsmodus konnte nicht gelesen werden."

say "Version: $VERSION"

if [ "$MODE" = "delta" ]; then
    BASE_DOWNLOAD=$(json_value base_download) || fail "Basis-Download konnte nicht gelesen werden."
    BASE_EXPECTED=$(json_value base_sha256) || fail "Basis-SHA256 konnte nicht gelesen werden."
    PLUGIN_EXPECTED=$(json_value plugin_sha256) || fail "Plugin-SHA256 konnte nicht gelesen werden."
    OVERLAY_DOWNLOAD=$(json_value overlay_download) || fail "Overlay-Download konnte nicht gelesen werden."
    OVERLAY_EXPECTED=$(json_value overlay_sha256) || fail "Overlay-SHA256 konnte nicht gelesen werden."

    say "Lade gepruefte Basis..."
    fetch "$BASE_DOWNLOAD" "$ZIPFILE" || fail "Basis-ZIP konnte nicht geladen werden."
    BASE_ACTUAL=$(sha256_file "$ZIPFILE") || fail "Basis-SHA256-Pruefung fehlgeschlagen."
    [ "$BASE_ACTUAL" = "$BASE_EXPECTED" ] || fail "Basis-SHA256 stimmt nicht. Installation abgebrochen."
    say "Basis-SHA256: OK"

    say "Entpacke Basis..."
    if command -v unzip >/dev/null 2>&1; then
        unzip -q -o "$ZIPFILE" -d "$EXTRACT" || fail "Entpacken fehlgeschlagen."
    else
        python3 -m zipfile -e "$ZIPFILE" "$EXTRACT" || fail "Entpacken fehlgeschlagen."
    fi

    [ -f "$EXTRACT/SafeUpdate2026/background.png" ] || fail "background.png fehlt in der Basis."
    [ -f "$EXTRACT/SafeUpdate2026/__init__.py" ] || fail "__init__.py fehlt in der Basis."

    say "Lade r25 Plugin-Code..."
    python3 - "$TMPDIR/latest.json" > "$TMPDIR/parts.txt" <<'PY' || fail "Plugin-Teile konnten nicht gelesen werden."
import json, sys
with open(sys.argv[1], 'r') as f:
    data = json.load(f)
for url in data['plugin_parts']:
    print(url)
PY

    : > "$EXTRACT/SafeUpdate2026/plugin.py" || fail "plugin.py konnte nicht vorbereitet werden."
    PARTNO=0
    while IFS= read -r URL; do
        [ -n "$URL" ] || continue
        PART="$TMPDIR/plugin.part.$PARTNO"
        fetch "$URL" "$PART" || fail "Plugin-Teil $PARTNO konnte nicht geladen werden."
        cat "$PART" >> "$EXTRACT/SafeUpdate2026/plugin.py" || fail "Plugin-Teil $PARTNO konnte nicht zusammengesetzt werden."
        PARTNO=$((PARTNO + 1))
    done < "$TMPDIR/parts.txt"
    [ "$PARTNO" -gt 0 ] || fail "Keine Plugin-Teile gefunden."

    PLUGIN_ACTUAL=$(sha256_file "$EXTRACT/SafeUpdate2026/plugin.py") || fail "Plugin-SHA256-Pruefung fehlgeschlagen."
    [ "$PLUGIN_ACTUAL" = "$PLUGIN_EXPECTED" ] || fail "Plugin-SHA256 stimmt nicht. Installation abgebrochen."
    say "Plugin-SHA256: OK"

    say "Lade r25 Oberflaechen-Fix..."
    fetch "$OVERLAY_DOWNLOAD" "$EXTRACT/SafeUpdate2026/r25_overlay.png" || fail "r25 Overlay konnte nicht geladen werden."
    OVERLAY_ACTUAL=$(sha256_file "$EXTRACT/SafeUpdate2026/r25_overlay.png") || fail "Overlay-SHA256-Pruefung fehlgeschlagen."
    [ "$OVERLAY_ACTUAL" = "$OVERLAY_EXPECTED" ] || fail "Overlay-SHA256 stimmt nicht. Installation abgebrochen."
    say "Overlay-SHA256: OK"
else
    fail "Unbekannter Installationsmodus: $MODE"
fi

[ -f "$EXTRACT/SafeUpdate2026/plugin.py" ] || fail "plugin.py fehlt."
syntax_check "$EXTRACT/SafeUpdate2026/plugin.py" || fail "Python-Syntaxpruefung des Downloads fehlgeschlagen."
say "Python-Syntax: OK"

# Keine Build-/Runtime-Caches aus dem Staging uebernehmen.
rm -rf "$EXTRACT/SafeUpdate2026/__pycache__"
find "$EXTRACT/SafeUpdate2026" -name '*.pyc' -delete 2>/dev/null || true

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

if ! syntax_check "$PLUGIN_DIR/plugin.py"; then
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
