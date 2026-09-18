#!/bin/sh
set -eu

BASE="https://raw.githubusercontent.com/keggy6893/SafeUpdate2026/r34-dev"
META_URL="$BASE/latest-r34-test.json"
TMP="/tmp/safeupdate2026-r34-test.$$"
PLUGIN_DIR="/usr/lib/enigma2/python/Plugins/Extensions/SafeUpdate2026"
RECOVER="/usr/bin/safeupdate-recover"
BOOTGUARD="/usr/bin/safeupdate-bootguard"
INITGUARD="/etc/init.d/safeupdate-bootguard"
ROLLBACK="/tmp/safeupdate2026-before-r34-test"
RECOVER_OLD="/tmp/safeupdate-recover.before-r34-test"
BOOTGUARD_OLD="/tmp/safeupdate-bootguard.before-r34-test"
INITGUARD_OLD="/tmp/safeupdate-bootguard.init.before-r34-test"

cleanup() {
    rm -rf "$TMP" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

backup_one() {
    SRC="$1"
    DST="$2"
    rm -f "$DST"
    [ -e "$SRC" ] && cp -a "$SRC" "$DST"
}

restore_one() {
    DST="$1"
    SRC="$2"
    rm -f "$DST"
    [ -e "$SRC" ] && cp -a "$SRC" "$DST"
}

register_bootguard() {
    if command -v update-rc.d >/dev/null 2>&1; then
        update-rc.d safeupdate-bootguard defaults >/dev/null 2>&1 || return 1
        return 0
    fi
    for D in /etc/rcS.d /etc/rc3.d /etc/rc4.d /etc/rc5.d; do
        [ -d "$D" ] || continue
        ln -sf ../init.d/safeupdate-bootguard "$D/S99safeupdate-bootguard"
    done
    return 0
}

unregister_bootguard() {
    if command -v update-rc.d >/dev/null 2>&1; then
        update-rc.d -f safeupdate-bootguard remove >/dev/null 2>&1 || true
    fi
    rm -f /etc/rcS.d/S99safeupdate-bootguard           /etc/rc3.d/S99safeupdate-bootguard           /etc/rc4.d/S99safeupdate-bootguard           /etc/rc5.d/S99safeupdate-bootguard 2>/dev/null || true
}

echo '[SafeUpdate2026] r34-dev2 Auto-Recovery Testinstaller'
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
[ -f "$SOURCE/safeupdate-bootguard" ] || { echo 'BootGuard fehlt' >&2; exit 1; }
[ -f "$SOURCE/safeupdate-bootguard.init" ] || { echo 'BootGuard-Init fehlt' >&2; exit 1; }

python3 -m py_compile "$SOURCE/plugin.py" "$SOURCE/safeupdate-recover" "$SOURCE/safeupdate-bootguard"
sh -n "$SOURCE/safeupdate-bootguard.init"
echo '[SafeUpdate2026] Syntax-/Service-Prüfung: OK'

rm -rf "$ROLLBACK"
if [ -d "$PLUGIN_DIR" ]; then
    cp -a "$PLUGIN_DIR" "$ROLLBACK"
fi
backup_one "$RECOVER" "$RECOVER_OLD"
backup_one "$BOOTGUARD" "$BOOTGUARD_OLD"
backup_one "$INITGUARD" "$INITGUARD_OLD"

rollback() {
    echo '[SafeUpdate2026] Installation fehlgeschlagen – Rollback.' >&2
    unregister_bootguard
    rm -rf "$PLUGIN_DIR"
    [ -d "$ROLLBACK" ] && cp -a "$ROLLBACK" "$PLUGIN_DIR"
    restore_one "$RECOVER" "$RECOVER_OLD"
    restore_one "$BOOTGUARD" "$BOOTGUARD_OLD"
    restore_one "$INITGUARD" "$INITGUARD_OLD"
    [ -x "$INITGUARD" ] && register_bootguard || true
    exit 1
}

rm -rf "$PLUGIN_DIR"
cp -a "$SOURCE" "$PLUGIN_DIR"
cp -a "$SOURCE/safeupdate-recover" "$RECOVER"
cp -a "$SOURCE/safeupdate-bootguard" "$BOOTGUARD"
cp -a "$SOURCE/safeupdate-bootguard.init" "$INITGUARD"
chmod 0755 "$RECOVER" "$BOOTGUARD" "$INITGUARD"

python3 -m py_compile "$PLUGIN_DIR/plugin.py" "$RECOVER" "$BOOTGUARD" || rollback
sh -n "$INITGUARD" || rollback
register_bootguard || rollback

echo '[SafeUpdate2026] r34-dev2 installiert.'
echo '[SafeUpdate2026] Vor Updates prüft SafeUpdate jetzt Dateisystem, Backup und Bootpfad.'
echo '[SafeUpdate2026] VU+ Duo 4K SE: Crash-Fallback wird nach erfolgreichem Update automatisch vorbereitet.'
echo '[SafeUpdate2026] Enigma2 wird nur neu gestartet – kein Box-Reboot.'
init 4
sleep 3
init 3
