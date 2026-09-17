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
with open(sys.argv[1], "r", encoding="utf-8") as f:
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
with open(sys.argv[1], "rb") as f:
    for block in iter(lambda: f.read(1024 * 1024), b""):
        h.update(block)
print(h.hexdigest())
PY
}

verify_git_blob() {
    file="$1"
    expected="$2"
    python3 - "$file" "$expected" <<'PY'
import hashlib, sys
p, expected = sys.argv[1], sys.argv[2].lower()
data = open(p, "rb").read()
actual = hashlib.sha1(("blob %d\0" % len(data)).encode("ascii") + data).hexdigest()
if actual != expected:
    print("erwartet:", expected)
    print("erhalten:", actual)
    raise SystemExit(1)
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

rm -rf "$TMPDIR"
mkdir -p "$EXTRACT" || fail "Temp-Verzeichnis konnte nicht erstellt werden."

say "Lade Versionsinformationen..."
fetch "$META_URL" "$TMPDIR/latest.json" || fail "latest.json konnte nicht geladen werden."
VERSION=$(json_value version) || fail "Version konnte nicht gelesen werden."
MODE=$(json_value mode 2>/dev/null || echo "full")
say "Version: $VERSION"

if [ "$MODE" = "r26_delta" ]; then
    BASE_DOWNLOAD=$(json_value base_download) || fail "Basis-Download konnte nicht gelesen werden."
    BASE_EXPECTED=$(json_value base_sha256) || fail "Basis-SHA256 konnte nicht gelesen werden."
    PLUGIN_URL=$(json_value plugin_payload) || fail "Plugin-Payload konnte nicht gelesen werden."
    PLUGIN_BLOB=$(json_value plugin_blob_sha1) || fail "Plugin-Blob-SHA konnte nicht gelesen werden."
    GENERIC_URL=$(json_value generic_payload) || fail "Grafik-Payload konnte nicht gelesen werden."
    GENERIC_BLOB=$(json_value generic_blob_sha1) || fail "Grafik-Blob-SHA konnte nicht gelesen werden."

    say "Lade gepruefte r24-Basis..."
    fetch "$BASE_DOWNLOAD" "$ZIPFILE" || fail "Basis-ZIP konnte nicht geladen werden."
    ACTUAL=$(sha256_file "$ZIPFILE") || fail "Basis-SHA256-Pruefung fehlgeschlagen."
    [ "$ACTUAL" = "$BASE_EXPECTED" ] || fail "Basis-SHA256 stimmt nicht. Installation abgebrochen."
    say "Basis-SHA256: OK"

    say "Entpacke Basis..."
    extract_zip || fail "Entpacken der Basis fehlgeschlagen."
    PACKAGE_DIR="$EXTRACT/SafeUpdate2026"
    [ -d "$PACKAGE_DIR" ] || fail "SafeUpdate2026-Verzeichnis fehlt in der Basis."
    [ -f "$PACKAGE_DIR/background.png" ] || fail "Klassische Hintergrundgrafik fehlt in der Basis."
    [ -f "$PACKAGE_DIR/__init__.py" ] || fail "__init__.py fehlt in der Basis."

    say "Lade r26 Plugin-Code..."
    fetch "$PLUGIN_URL" "$TMPDIR/plugin.zlib.b64" || fail "r26 Plugin-Payload konnte nicht geladen werden."
    verify_git_blob "$TMPDIR/plugin.zlib.b64" "$PLUGIN_BLOB" || fail "Plugin-Payload ist nicht unveraendert."

    say "Lade r26 neutrale Receiver-Grafik..."
    fetch "$GENERIC_URL" "$TMPDIR/generic.jpg.b64" || fail "r26 Grafik-Payload konnte nicht geladen werden."
    verify_git_blob "$TMPDIR/generic.jpg.b64" "$GENERIC_BLOB" || fail "Grafik-Payload ist nicht unveraendert."

    python3 - "$TMPDIR/plugin.zlib.b64" "$PACKAGE_DIR/plugin.py" <<'PY' || fail "r26 Plugin-Code konnte nicht entpackt werden."
import base64, zlib, sys
src, dst = sys.argv[1], sys.argv[2]
raw = base64.b64decode(open(src, "rb").read())
open(dst, "wb").write(zlib.decompress(raw))
PY

    python3 - "$TMPDIR/generic.jpg.b64" "$PACKAGE_DIR/background_generic.jpg" <<'PY' || fail "r26 Receiver-Grafik konnte nicht entpackt werden."
import base64, sys
src, dst = sys.argv[1], sys.argv[2]
open(dst, "wb").write(base64.b64decode(open(src, "rb").read()))
PY

    cp -f "$PACKAGE_DIR/background.png" "$PACKAGE_DIR/background_vu_duo4kse.png" || fail "VU+-Hintergrund konnte nicht vorbereitet werden."

    python3 - "$PACKAGE_DIR/plugin.py" <<'PY' || fail "r26 Grafikreferenz konnte nicht gesetzt werden."
import sys
p = sys.argv[1]
with open(p, "r", encoding="utf-8") as f:
    s = f.read()
old = '"background_generic.png"'
new = '"background_generic.jpg"'
if s.count(old) != 1:
    raise SystemExit("unerwartete Anzahl background_generic.png: %d" % s.count(old))
s = s.replace(old, new, 1)
with open(p, "w", encoding="utf-8") as f:
    f.write(s)
PY

elif [ "$MODE" = "full" ]; then
    DOWNLOAD=$(json_value download) || fail "Download-URL konnte nicht gelesen werden."
    EXPECTED=$(json_value sha256) || fail "SHA256 konnte nicht gelesen werden."
    say "Lade Paket..."
    fetch "$DOWNLOAD" "$ZIPFILE" || fail "Paket konnte nicht geladen werden."
    ACTUAL=$(sha256_file "$ZIPFILE") || fail "SHA256-Pruefung fehlgeschlagen."
    [ "$ACTUAL" = "$EXPECTED" ] || fail "SHA256 stimmt nicht. Installation abgebrochen."
    say "SHA256: OK"
    say "Entpacke Paket..."
    extract_zip || fail "Entpacken fehlgeschlagen."
    PACKAGE_DIR="$EXTRACT/SafeUpdate2026"
else
    fail "Unbekannter Installationsmodus: $MODE"
fi

[ -d "$PACKAGE_DIR" ] || fail "SafeUpdate2026-Verzeichnis fehlt."
[ -f "$PACKAGE_DIR/plugin.py" ] || fail "plugin.py fehlt."
[ -f "$PACKAGE_DIR/__init__.py" ] || fail "__init__.py fehlt."
syntax_check "$PACKAGE_DIR/plugin.py" || fail "Python-Syntaxpruefung fehlgeschlagen."
say "Python-Syntax: OK"

rm -rf "$PACKAGE_DIR/__pycache__"
find "$PACKAGE_DIR" -name '*.pyc' -delete 2>/dev/null || true

rm -rf "$BACKUP_DIR"
if [ -d "$PLUGIN_DIR" ]; then
    say "Sichere vorhandene Installation..."
    cp -a "$PLUGIN_DIR" "$BACKUP_DIR" || fail "Backup der alten Installation fehlgeschlagen."
fi

say "Installiere SafeUpdate2026..."
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

sync
rm -rf "$TMPDIR"
say "SafeUpdate2026 $VERSION wurde erfolgreich installiert."
say "Enigma2 wird neu gestartet..."
init 4
sleep 3
init 3
