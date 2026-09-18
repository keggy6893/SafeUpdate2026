#!/bin/sh
set -u

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

die() {
    echo "[SafeUpdate2026] FEHLER: $*" >&2
    exit 1
}

backup_one() {
    SRC="$1"
    DST="$2"
    rm -f "$DST" 2>/dev/null || true
    if [ -e "$SRC" ]; then
        cp -a "$SRC" "$DST" || return 1
    fi
    return 0
}

restore_one() {
    DST="$1"
    SRC="$2"
    rm -f "$DST" 2>/dev/null || true
    if [ -e "$SRC" ]; then
        cp -a "$SRC" "$DST" || return 1
    fi
    return 0
}

register_bootguard() {
    if command -v update-rc.d >/dev/null 2>&1; then
        update-rc.d safeupdate-bootguard defaults >/dev/null 2>&1
        return $?
    fi
    for D in /etc/rcS.d /etc/rc3.d /etc/rc4.d /etc/rc5.d; do
        [ -d "$D" ] || continue
        ln -sf ../init.d/safeupdate-bootguard "$D/S99safeupdate-bootguard" || return 1
    done
    return 0
}

unregister_bootguard() {
    if command -v update-rc.d >/dev/null 2>&1; then
        update-rc.d -f safeupdate-bootguard remove >/dev/null 2>&1 || true
    fi
    rm -f /etc/rcS.d/S99safeupdate-bootguard           /etc/rc3.d/S99safeupdate-bootguard           /etc/rc4.d/S99safeupdate-bootguard           /etc/rc5.d/S99safeupdate-bootguard 2>/dev/null || true
}

rollback() {
    echo '[SafeUpdate2026] Installation fehlgeschlagen – Rollback.' >&2
    unregister_bootguard
    rm -rf "$PLUGIN_DIR" 2>/dev/null || true
    if [ -d "$ROLLBACK" ]; then
        cp -a "$ROLLBACK" "$PLUGIN_DIR" 2>/dev/null || true
    fi
    restore_one "$RECOVER" "$RECOVER_OLD" || true
    restore_one "$BOOTGUARD" "$BOOTGUARD_OLD" || true
    restore_one "$INITGUARD" "$INITGUARD_OLD" || true
    if [ -x "$INITGUARD" ]; then
        register_bootguard || true
    fi
    exit 1
}

echo '[SafeUpdate2026] r34-dev2 Auto-Recovery Testinstaller'
mkdir -p "$TMP" || die "Temporäres Verzeichnis konnte nicht angelegt werden."
wget -qO "$TMP/latest.json" "$META_URL" || die "Metadaten konnten nicht geladen werden."

VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$TMP/latest.json" 2>/dev/null)" || die "Version konnte nicht gelesen werden."
DOWNLOAD="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["download"])' "$TMP/latest.json" 2>/dev/null)" || die "Download-URL konnte nicht gelesen werden."
EXPECTED_SHA="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sha256"])' "$TMP/latest.json" 2>/dev/null)" || die "SHA256 konnte nicht gelesen werden."

printf '[SafeUpdate2026] Version: %s\n' "$VERSION"
wget -qO "$TMP/package.zip" "$DOWNLOAD" || die "Paket konnte nicht geladen werden."
ACTUAL_SHA="$(sha256sum "$TMP/package.zip" | awk '{print $1}')"
[ "$ACTUAL_SHA" = "$EXPECTED_SHA" ] || die "SHA256-Prüfung fehlgeschlagen."
echo '[SafeUpdate2026] SHA256: OK'

unzip -q "$TMP/package.zip" -d "$TMP/unpacked" || die "ZIP konnte nicht entpackt werden."
SOURCE="$TMP/unpacked/SafeUpdate2026"
[ -f "$SOURCE/plugin.py" ] || die "plugin.py fehlt."
[ -f "$SOURCE/safeupdate-recover" ] || die "Recovery-Helfer fehlt."
[ -f "$SOURCE/safeupdate-bootguard" ] || die "BootGuard fehlt."
[ -f "$SOURCE/safeupdate-bootguard.init" ] || die "BootGuard-Init fehlt."

python3 -m py_compile "$SOURCE/plugin.py" "$SOURCE/safeupdate-recover" "$SOURCE/safeupdate-bootguard" || die "Python-Syntaxprüfung fehlgeschlagen."
sh -n "$SOURCE/safeupdate-bootguard.init" || die "Init-Skriptprüfung fehlgeschlagen."
echo '[SafeUpdate2026] Syntax-/Service-Prüfung: OK'

echo '[SafeUpdate2026] Sichere aktuelle Installation ...'
rm -rf "$ROLLBACK" 2>/dev/null || die "Altes temporäres Rollback konnte nicht entfernt werden."
if [ -d "$PLUGIN_DIR" ]; then
    cp -a "$PLUGIN_DIR" "$ROLLBACK" || die "Bestehendes Plugin konnte nicht temporär gesichert werden."
fi
backup_one "$RECOVER" "$RECOVER_OLD" || die "Bestehender Recovery-Helfer konnte nicht gesichert werden."
backup_one "$BOOTGUARD" "$BOOTGUARD_OLD" || die "Bestehender BootGuard konnte nicht gesichert werden."
backup_one "$INITGUARD" "$INITGUARD_OLD" || die "Bestehendes BootGuard-Init konnte nicht gesichert werden."
echo '[SafeUpdate2026] Rollback-Sicherung: OK'

echo '[SafeUpdate2026] Installiere r34-dev2 ...'
rm -rf "$PLUGIN_DIR" || rollback
cp -a "$SOURCE" "$PLUGIN_DIR" || rollback
cp -a "$SOURCE/safeupdate-recover" "$RECOVER" || rollback
cp -a "$SOURCE/safeupdate-bootguard" "$BOOTGUARD" || rollback
cp -a "$SOURCE/safeupdate-bootguard.init" "$INITGUARD" || rollback
chmod 0755 "$RECOVER" "$BOOTGUARD" "$INITGUARD" || rollback

python3 -m py_compile "$PLUGIN_DIR/plugin.py" "$RECOVER" "$BOOTGUARD" || rollback
sh -n "$INITGUARD" || rollback
register_bootguard || rollback

echo '[SafeUpdate2026] r34-dev2 installiert.'
echo '[SafeUpdate2026] Vor Updates prüft SafeUpdate jetzt Dateisystem, Backup und Bootpfad.'
echo '[SafeUpdate2026] VU+ Duo 4K SE: Crash-Fallback wird nach erfolgreichem Update automatisch vorbereitet.'
echo '[SafeUpdate2026] Enigma2 wird nur neu gestartet – kein Box-Reboot.'
init 4 || die "Enigma2 konnte nicht gestoppt werden."
sleep 3
init 3 || die "Enigma2 konnte nicht gestartet werden."
echo '[SafeUpdate2026] Fertig.'
