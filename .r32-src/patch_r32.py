# -*- coding: utf-8 -*-
from __future__ import print_function

import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    s = f.read()


def replace_once(old, new, label):
    global s
    count = s.count(old)
    if count != 1:
        raise RuntimeError("%s: expected exactly 1 match, got %d" % (label, count))
    s = s.replace(old, new, 1)


def replace_block(start, end, new, label):
    global s
    a = s.find(start)
    if a < 0:
        raise RuntimeError("%s: start marker missing" % label)
    b = s.find(end, a + len(start))
    if b < 0:
        raise RuntimeError("%s: end marker missing" % label)
    s = s[:a] + new + s[b:]


replace_once('PLUGIN_VERSION = "2026.1-r31"', 'PLUGIN_VERSION = "2026.1-r32"', 'version')

replace_once(
    'LOG_FILE = "/tmp/safeupdate2026.log"\n',
    'LOG_FILE = "/tmp/safeupdate2026.log"\n'
    'INTERNAL_BACKUP_DIRNAME = "safeupdate2026"\n'
    'INTERNAL_BACKUP_META = "backup.json"\n',
    'internal backup constants'
)

helpers = r'''

def block_device_size(path):
    try:
        value = run_cmd(["blockdev", "--getsize64", path]).strip()
        return int(value)
    except Exception:
        return 0


def read_json_file(path):
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_json_file(path, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.rename(tmp, path)
        return True
    except Exception:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except Exception:
            pass
        return False


def internal_backup_base(mountpoint):
    if not mountpoint:
        return ""
    return os.path.join(mountpoint, INTERNAL_BACKUP_DIRNAME)


def internal_backup_dir(source_slot, mountpoint):
    try:
        source_slot = int(source_slot)
    except Exception:
        return ""
    if source_slot <= 0 or source_slot > 99 or not mountpoint:
        return ""
    return os.path.join(internal_backup_base(mountpoint), "slot%d" % source_slot)


def internal_backup_path_is_safe(path, source_slot, mountpoint):
    expected = internal_backup_dir(source_slot, mountpoint)
    if not expected or not path or not mountpoint:
        return False
    mp_real = os.path.realpath(mountpoint)
    base = internal_backup_base(mountpoint)
    expected_real = os.path.realpath(expected)
    path_real = os.path.realpath(path)
    if path_real != expected_real:
        return False
    if not expected_real.startswith(mp_real.rstrip("/") + "/"):
        return False
    if os.path.basename(expected_real) != "slot%d" % int(source_slot):
        return False
    if os.path.lexists(base) and (not os.path.isdir(base) or os.path.islink(base)):
        return False
    if os.path.lexists(expected) and os.path.islink(expected):
        return False
    return True


def validate_internal_backup_state(state, mountpoint=None):
    if not isinstance(state, dict):
        return None
    if state.get("backup_mode") != "internal" or not state.get("verified"):
        return None
    try:
        source = int(state.get("source_slot"))
    except Exception:
        return None

    mp = mountpoint or ensure_full_mount(False)
    if not mp:
        return None
    info = compatible_startup_slots().get(source)
    if not info:
        return None

    backup_dir = internal_backup_dir(source, mp)
    if not internal_backup_path_is_safe(backup_dir, source, mp):
        return None
    if not os.path.isdir(backup_dir) or os.path.islink(backup_dir):
        return None

    meta_path = os.path.join(backup_dir, INTERNAL_BACKUP_META)
    disk = read_json_file(meta_path)
    if disk.get("backup_mode") != "internal" or not disk.get("verified"):
        return None
    try:
        if int(disk.get("source_slot")) != source:
            return None
    except Exception:
        return None

    recorded_root = os.path.realpath(disk.get("root_device") or "")
    live_root = os.path.realpath(root_device() or "")
    if not recorded_root or recorded_root != live_root:
        return None

    rootfs = os.path.join(backup_dir, "rootfs")
    if os.path.islink(rootfs) or not slot_root_tree_valid(rootfs):
        return None

    image_hash = disk.get("image_version_sha256", "")
    if not image_hash or sha256_prefix(os.path.join(rootfs, "etc", "image-version")) != image_hash:
        return None

    kernel_hash = disk.get("kernel_sha256", "")
    if not kernel_hash:
        return None
    if is_gbtrio4k():
        kernel_file = os.path.join(backup_dir, "kernel.img")
        if os.path.islink(kernel_file) or not os.path.isfile(kernel_file):
            return None
        if sha256_prefix(kernel_file) != kernel_hash:
            return None
        try:
            expected_size = int(disk.get("kernel_size", 0))
        except Exception:
            expected_size = 0
        if expected_size > 0:
            try:
                if os.path.getsize(kernel_file) != expected_size:
                    return None
            except Exception:
                return None
    else:
        zimage = os.path.join(rootfs, "zImage")
        if not os.path.isfile(zimage) or sha256_prefix(zimage) != kernel_hash:
            return None

    result = dict(disk)
    result["_backup_dir"] = backup_dir
    result["_rootfs"] = rootfs
    return result


def discover_internal_backups(mountpoint=None):
    mp = mountpoint or ensure_full_mount(False)
    if not mp:
        return []
    base = internal_backup_base(mp)
    if not os.path.isdir(base) or os.path.islink(base):
        return []
    result = []
    for entry in sorted(glob.glob(os.path.join(base, "slot*"))):
        if os.path.islink(entry) or not os.path.isdir(entry):
            continue
        meta = read_json_file(os.path.join(entry, INTERNAL_BACKUP_META))
        valid = validate_internal_backup_state(meta, mp)
        if valid:
            result.append(valid)
    result.sort(key=lambda x: str(x.get("created_sort", "")), reverse=True)
    return result
'''

replace_once('\ndef _clean_hw_value(value):\n', helpers + '\n\ndef _clean_hw_value(value):\n', 'internal backup helpers')

replace_once(
    '        self.verified_backup_slot = None\n        self.container = None\n',
    '        self.verified_backup_slot = None\n'
    '        self.verified_backup_mode = None\n'
    '        self.verified_backup_path = ""\n'
    '        self.recovery_state = None\n'
    '        self.pending_internal_backup = None\n'
    '        self.pending_restore = None\n'
    '        self.container = None\n',
    'screen state attributes'
)

replace_once(
    '                "0": self.request_delete_backup,\n',
    '                "0": self.request_delete_backup,\n'
    '                "9": self.restore_internal_backup,\n',
    'restore key'
)

old_refresh_else = '''        else:\n            self["targetSlot"].setText("Kein verifizierter freier Slot")\n            self.append_log("> Backup gesperrt: kein eindeutig verifizierter freier Slot.")\n'''
new_refresh_else = '''        else:\n            self["targetSlot"].setText("Internes eMMC")\n            self.append_log("> Kein freier Multiboot-Slot – verwende internes eMMC-Sicherheitsbackup.")\n            self.append_log("> Vorhandene Slots und Recovery werden nicht überschrieben.")\n'''
replace_once(old_refresh_else, new_refresh_else, 'internal fallback UI')

new_load_rollback = r'''    def load_rollback(self):
        self.recovery_state = None
        st = load_state()

        # r32: internal eMMC backup metadata is also stored on the shared
        # multiboot filesystem. This lets another slot discover and restore it.
        internal = None
        if st.get("backup_mode") == "internal":
            internal = validate_internal_backup_state(st)
        if internal is None:
            candidates = discover_internal_backups()
            if candidates:
                current = current_slot()
                same_source = [x for x in candidates if int(x.get("source_slot", -1)) == current]
                internal = same_source[0] if same_source else candidates[0]

        if internal is not None:
            source = int(internal.get("source_slot"))
            self.recovery_state = internal
            self.verified_backup_mode = "internal"
            self.verified_backup_path = internal.get("_backup_dir", "")
            created = (internal.get("created") or "?").split(" ")[0]
            if source == current_slot():
                self.backup_verified = True
                self.verified_backup_slot = None
                self["targetSlot"].setText("Internes eMMC – VERIFIZIERT ✓")
                self.set_backup_progress(100, "Backup-Fortschritt – Fertig", "Status: Internes eMMC-Backup verifiziert.")
                self["rollback"].setText("Backup: Internes eMMC\nQuelle: Slot %s\nErstellt: %s\n0 = BACKUP LÖSCHEN" % (source, created))
                self.append_log("> Internes eMMC-Backup erneut geprüft: Slot %s OK." % source)
            else:
                # A backup of another slot is a recovery source, not permission
                # to update the currently running slot.
                self.backup_verified = False
                self.verified_backup_slot = None
                self["rollback"].setText("eMMC-Backup: OK\nQuelle: Slot %s\nStatus: verifiziert\n9 = WIEDERHERSTELLEN" % source)
                self.append_log("> Notfall-Backup von Slot %s gefunden. Taste 9 = Wiederherstellen." % source)
            return

        # Existing bootable-slot backup mode remains unchanged.
        valid = False
        target = st.get("target_slot")
        source = st.get("source_slot")
        if st.get("verified") and st.get("backup_mode", "slot") == "slot" and source == current_slot() and target is not None:
            try:
                target = int(target)
                info = compatible_startup_slots().get(target)
                mp = ensure_full_mount(False)
                if info and mp:
                    dst = os.path.join(mp, info["rootsubdir"])
                    valid = slot_backup_valid(target, dst, st.get("kernel_sha256", ""))
            except Exception:
                valid = False

        if valid:
            self.backup_verified = True
            self.verified_backup_slot = target
            self.verified_backup_mode = "slot"
            self.verified_backup_path = ""
            self["targetSlot"].setText("Slot %s – VERIFIZIERT ✓" % target)
            self.set_backup_progress(100, "Backup-Fortschritt – Fertig", "Status: Backup in Slot %s verifiziert." % target)
            created = (st.get("created") or "?").split(" ")[0]
            self["rollback"].setText("Backup-Slot:  %s\nQuelle:       Slot %s\nErstellt:     %s\n0 = BACKUP LÖSCHEN" % (target, source, created))
            self.append_log("> Gespeichertes Backup erneut geprüft: Slot %s OK." % target)
        elif st.get("verified"):
            self.backup_verified = False
            self.verified_backup_slot = None
            self.verified_backup_mode = None
            self.verified_backup_path = ""
            self.set_backup_progress(0, "Backup-Fortschritt", "Status: Gespeichertes Backup fehlt – Update gesperrt.")
            self["rollback"].setText("Noch kein gültiges Backup vorhanden.")
            self.append_log("> Alter Backup-Status verworfen: Backup physisch nicht mehr verifizierbar.")
            try:
                st["verified"] = False
                st["invalidated"] = datetime.now().strftime("%d.%m.%Y %H:%M")
                save_state(st)
            except Exception:
                pass

'''
replace_block('    def load_rollback(self):\n', '    def paint_update_state(self):\n', new_load_rollback, 'load_rollback')

internal_methods = r'''    def start_internal_backup(self):
        if self.busy:
            return
        source = current_slot()
        if source is None:
            self.session.open(MessageBox, "Aktiver Quellslot konnte nicht eindeutig erkannt werden.", MessageBox.TYPE_ERROR)
            return
        if source not in compatible_startup_slots():
            self.session.open(MessageBox, "Aktiver Slot ist nicht eindeutig in STARTUP_N verifiziert.", MessageBox.TYPE_ERROR)
            return

        mp = ensure_full_mount(True)
        if not mp:
            self.session.open(MessageBox, "Internes Multiboot-Dateisystem konnte nicht sicher schreibbar geöffnet werden.", MessageBox.TYPE_ERROR)
            return
        src = active_source_path(mp)
        if not src or not slot_root_tree_valid(src):
            self.session.open(MessageBox, "Aktuelles Image konnte nicht vollständig verifiziert werden.", MessageBox.TYPE_ERROR)
            return

        backup_dir = internal_backup_dir(source, mp)
        if not internal_backup_path_is_safe(backup_dir, source, mp):
            self.session.open(MessageBox, "Interner Backup-Pfad besteht die Sicherheitsprüfung nicht.", MessageBox.TYPE_ERROR)
            return
        base = internal_backup_base(mp)
        if os.path.lexists(base) and (not os.path.isdir(base) or os.path.islink(base)):
            self.session.open(MessageBox, "Interner SafeUpdate-Bereich ist nicht sicher nutzbar.", MessageBox.TYPE_ERROR)
            return
        if os.path.lexists(backup_dir):
            existing = validate_internal_backup_state(read_json_file(os.path.join(backup_dir, INTERNAL_BACKUP_META)), mp)
            if existing:
                self.session.open(MessageBox, "Für Slot %d existiert bereits ein verifiziertes internes Backup.\n\nTaste 0 löscht ausschließlich dieses SafeUpdate-Backup." % source, MessageBox.TYPE_INFO)
            else:
                self.session.open(MessageBox, "Im internen SafeUpdate-Bereich liegt ein unvollständiges Backup.\nEs wird aus Sicherheitsgründen nicht überschrieben.", MessageBox.TYPE_ERROR)
            return

        source_bytes = tree_size_bytes(src)
        kernel_bytes = block_device_size(active_kernel_device()) if is_gbtrio4k() else 0
        free_bytes = filesystem_free_bytes(mp)
        reserve = 128 * 1024 * 1024
        needed = source_bytes + kernel_bytes + reserve
        if source_bytes <= 0 or free_bytes <= 0:
            self.session.open(MessageBox, "Freier eMMC-Speicher bzw. Backup-Größe konnte nicht sicher ermittelt werden.", MessageBox.TYPE_ERROR)
            return
        if free_bytes < needed:
            self.session.open(
                MessageBox,
                "Nicht genug freier interner eMMC-Speicher.\n\nBenötigt: ca. %d MB inkl. Reserve\nFrei: ca. %d MB" % (needed // (1024 * 1024), free_bytes // (1024 * 1024)),
                MessageBox.TYPE_ERROR,
            )
            return

        self.append_log("> Kein freier Slot – internes eMMC-Backup gewählt.")
        self.append_log("> Backup-Bereich: /%s/slot%d" % (INTERNAL_BACKUP_DIRNAME, source))
        self.append_log("> Freier eMMC-Speicher: %d MB" % (free_bytes // (1024 * 1024)))
        self.session.openWithCallback(
            lambda yes: self.do_internal_backup(yes, source, src, backup_dir, source_bytes),
            MessageBox,
            "Internes Sicherheitsbackup von Slot %d anlegen?\n\n"
            "Kein vorhandener Multiboot-Slot wird verändert.\n"
            "Recovery bleibt unangetastet.\n"
            "Das Backup liegt separat unter /%s/." % (source, INTERNAL_BACKUP_DIRNAME),
            MessageBox.TYPE_YESNO,
        )

    def do_internal_backup(self, yes, source, src, backup_dir, source_bytes):
        if not yes or self.busy:
            return
        mp = ensure_full_mount(True)
        if not mp or not internal_backup_path_is_safe(backup_dir, source, mp):
            self.session.open(MessageBox, "Backup abgebrochen: interner Zielpfad ist nicht mehr eindeutig.", MessageBox.TYPE_ERROR)
            return
        if os.path.lexists(backup_dir):
            self.session.open(MessageBox, "Backup abgebrochen: interner Zielpfad existiert inzwischen.", MessageBox.TYPE_ERROR)
            return
        if os.path.realpath(src) == os.path.realpath(backup_dir) or os.path.realpath(backup_dir).startswith(os.path.realpath(src).rstrip("/") + "/"):
            self.session.open(MessageBox, "Backup abgebrochen: Ziel liegt unerwartet im Quellimage.", MessageBox.TYPE_ERROR)
            return

        base = internal_backup_base(mp)
        rootfs = os.path.join(backup_dir, "rootfs")
        self.busy = True
        self.backup_verified = False
        self.paint_update_state()
        self.backup_total_bytes = int(source_bytes or 0)
        self.backup_dst = rootfs
        self.pending_internal_backup = (source, backup_dir, src)
        self.set_backup_progress(3, "Backup-Fortschritt – Prüfen", "Status: Internes eMMC-Backup wird vorbereitet ...")
        try:
            self.progress_timer.start(1500, False)
        except Exception:
            pass

        if is_gbtrio4k():
            src_kernel = active_kernel_device()
            if not gigablue_kernel_layout_ok() or not src_kernel or not os.path.exists(src_kernel):
                self.busy = False
                self.pending_internal_backup = None
                self.backup_dst = ""
                self.session.open(MessageBox, "GigaBlue Kernelquelle ist nicht sicher verifizierbar.", MessageBox.TYPE_ERROR)
                return
            script = """
set -e
BASE={base}
DST={dst}
ROOTFS="$DST/rootfs"
SRC={src}
SRC_KERNEL={src_kernel}
if [ -e "$BASE" ]; then test -d "$BASE"; test ! -L "$BASE"; else mkdir "$BASE"; fi
test ! -L "$BASE"
test ! -e "$DST"
mkdir "$DST"
mkdir "$ROOTFS"
echo 'Internes Backup-Ziel ist weiterhin frei.'
echo 'Synchronisiere Dateisystem...'
sync
echo 'Kopiere Image...'
cp -a "$SRC"/. "$ROOTFS"/
sync
test -f "$ROOTFS/etc/image-version"
test -e "$ROOTFS/sbin/init"
test -f "$ROOTFS/usr/bin/enigma2"
echo 'Kopiere GigaBlue Kernel in Sicherheitsdatei...'
dd if="$SRC_KERNEL" of="$DST/kernel.img" bs=1048576 conv=fsync 2>/dev/null
sync
SRC_HASH=$(sha256sum "$SRC_KERNEL" | awk '{{print $1}}')
DST_HASH=$(sha256sum "$DST/kernel.img" | awk '{{print $1}}')
echo "Quelle zImage: $SRC_HASH"
echo "Backup zImage: $DST_HASH"
[ -n "$SRC_HASH" ]
[ "$SRC_HASH" = "$DST_HASH" ] || exit 22
echo 'BACKUP_VERIFIED'
""".format(base=shq(base), dst=shq(backup_dir), src=shq(src), src_kernel=shq(src_kernel))
        else:
            script = """
set -e
BASE={base}
DST={dst}
ROOTFS="$DST/rootfs"
SRC={src}
if [ -e "$BASE" ]; then test -d "$BASE"; test ! -L "$BASE"; else mkdir "$BASE"; fi
test ! -L "$BASE"
test ! -e "$DST"
mkdir "$DST"
mkdir "$ROOTFS"
echo 'Internes Backup-Ziel ist weiterhin frei.'
echo 'Synchronisiere Dateisystem...'
sync
echo 'Kopiere Image...'
cp -a "$SRC"/. "$ROOTFS"/
sync
test -f "$ROOTFS/zImage"
test -f "$ROOTFS/etc/image-version"
SRC_HASH=$(sha256sum "$SRC/zImage" | awk '{{print $1}}')
DST_HASH=$(sha256sum "$ROOTFS/zImage" | awk '{{print $1}}')
echo "Quelle zImage: $SRC_HASH"
echo "Backup zImage: $DST_HASH"
[ -n "$SRC_HASH" ]
[ "$SRC_HASH" = "$DST_HASH" ] || exit 22
echo 'BACKUP_VERIFIED'
""".format(base=shq(base), dst=shq(backup_dir), src=shq(src))

        self.append_log("> Internes eMMC-Sicherheitsbackup startet...")
        self.connect_container(self.backup_data, self.internal_backup_closed)
        self.container.execute("/bin/sh -c %s" % shq(script))

    def internal_backup_closed(self, rc):
        try:
            self.progress_timer.stop()
        except Exception:
            pass
        self.busy = False
        pending = self.pending_internal_backup
        self.pending_internal_backup = None
        if not pending:
            return
        source, backup_dir, src = pending
        rootfs = os.path.join(backup_dir, "rootfs")
        verified = (rc == 0 and slot_root_tree_valid(rootfs))
        kernel_hash = ""
        kernel_size = 0
        if verified:
            if is_gbtrio4k():
                src_kernel = active_kernel_device()
                kernel_file = os.path.join(backup_dir, "kernel.img")
                kernel_hash = sha256_prefix(src_kernel) if src_kernel else ""
                verified = bool(kernel_hash and os.path.isfile(kernel_file) and sha256_prefix(kernel_file) == kernel_hash)
                kernel_size = block_device_size(src_kernel) if src_kernel else 0
                if verified and kernel_size > 0:
                    try:
                        verified = os.path.getsize(kernel_file) == kernel_size
                    except Exception:
                        verified = False
            else:
                src_z = os.path.join(src, "zImage")
                dst_z = os.path.join(rootfs, "zImage")
                kernel_hash = sha256_prefix(src_z)
                verified = bool(kernel_hash and os.path.isfile(dst_z) and sha256_prefix(dst_z) == kernel_hash)

        image_hash = sha256_prefix(os.path.join(rootfs, "etc", "image-version")) if verified else ""
        if not image_hash:
            verified = False

        if verified:
            created = datetime.now().strftime("%d.%m.%Y %H:%M")
            meta = {
                "backup_mode": "internal",
                "source_slot": int(source),
                "created": created,
                "created_sort": datetime.now().strftime("%Y%m%d%H%M%S"),
                "verified": True,
                "build": image_info().get("build", ""),
                "root_device": root_device(),
                "backup_rel": "%s/slot%d" % (INTERNAL_BACKUP_DIRNAME, source),
                "kernel_sha256": kernel_hash,
                "kernel_size": kernel_size,
                "image_version_sha256": image_hash,
            }
            if is_gbtrio4k():
                meta["kernel_source_device"] = active_kernel_device()
            if save_json_file(os.path.join(backup_dir, INTERNAL_BACKUP_META), meta):
                checked = validate_internal_backup_state(meta)
            else:
                checked = None
            verified = checked is not None

        if verified:
            save_state(meta)
            self.backup_verified = True
            self.verified_backup_slot = None
            self.verified_backup_mode = "internal"
            self.verified_backup_path = backup_dir
            self.recovery_state = checked
            self.set_backup_progress(100, "Backup-Fortschritt – Fertig", "Status: Internes eMMC-Backup erfolgreich verifiziert.")
            self["targetSlot"].setText("Internes eMMC – VERIFIZIERT ✓")
            self["rollback"].setText("Backup: Internes eMMC\nQuelle: Slot %d\nStatus: verifiziert\n0 = BACKUP LÖSCHEN" % source)
            self.append_log("> Internes eMMC-Backup verifiziert. Update freigegeben.")
            self.nav_focus = 6
            self.last_action_focus = 6
            self.paint_nav_focus()
        else:
            self.backup_verified = False
            self.verified_backup_mode = None
            self.set_backup_progress(self.progress_value, "Backup-Fortschritt – FEHLER", "Status: Internes Backup nicht vollständig verifiziert.")
            self.append_log("> FEHLER: Internes eMMC-Backup nicht verifiziert.")
            self.session.open(MessageBox, "Internes eMMC-Backup konnte nicht vollständig verifiziert werden.\nDas Update bleibt gesperrt.", MessageBox.TYPE_ERROR)
        self.paint_update_state()
        self.backup_dst = ""
        self.backup_total_bytes = 0

'''
replace_once('    def start_backup(self):\n', internal_methods + '    def start_backup(self):\n', 'internal backup methods')

replace_once(
    '''        if not self.slots:\n            self.session.open(\n                MessageBox,\n                "Kein eindeutig verifizierter freier Multiboot-Slot verfügbar.",\n                MessageBox.TYPE_ERROR\n            )\n            return\n''',
    '''        if not self.slots:\n            self.start_internal_backup()\n            return\n''',
    'fallback start_backup'
)

# Mark legacy slot backups explicitly in state so both modes can coexist safely.
replace_once(
    '            state = {"source_slot": source, "target_slot": target, "created": created, "verified": True, "build": image_info().get("build", "")}\n',
    '            state = {"backup_mode": "slot", "source_slot": source, "target_slot": target, "created": created, "verified": True, "build": image_info().get("build", "")}\n',
    'slot backup mode state'
)
replace_once(
    '            self.verified_backup_slot = target\n            created = datetime.now().strftime("%d.%m.%Y %H:%M")\n',
    '            self.verified_backup_slot = target\n            self.verified_backup_mode = "slot"\n            self.verified_backup_path = ""\n            created = datetime.now().strftime("%d.%m.%Y %H:%M")\n',
    'slot verified mode'
)

internal_delete_methods = r'''    def request_delete_internal_backup(self):
        candidate = None
        if isinstance(self.recovery_state, dict) and self.recovery_state.get("backup_mode") == "internal":
            candidate = self.recovery_state
        if candidate is None:
            st = load_state()
            if st.get("backup_mode") == "internal":
                candidate = validate_internal_backup_state(st)
        if candidate is None:
            found = discover_internal_backups()
            candidate = found[0] if found else None
        if candidate is None:
            self.session.open(MessageBox, "Kein verifiziertes internes SafeUpdate-Backup zum Löschen vorhanden.", MessageBox.TYPE_INFO)
            return

        mp = ensure_full_mount(True)
        checked = validate_internal_backup_state(candidate, mp) if mp else None
        if checked is None:
            self.session.open(MessageBox, "KILLSWITCH blockiert: Internes Backup ist nicht mehr eindeutig verifizierbar.", MessageBox.TYPE_ERROR)
            return
        source = int(checked.get("source_slot"))
        backup_dir = checked.get("_backup_dir", "")
        if not internal_backup_path_is_safe(backup_dir, source, mp):
            self.session.open(MessageBox, "KILLSWITCH blockiert: Backup-Pfad ist nicht sicher.", MessageBox.TYPE_ERROR)
            return

        self.session.openWithCallback(
            lambda yes: self.do_delete_internal_backup(yes, checked),
            MessageBox,
            "KILLSWITCH: Internes Backup von Slot %d wirklich löschen?\n\n"
            "Gelöscht wird ausschließlich /%s/slot%d.\n"
            "Kein linuxrootfs-Slot, keine Kernelpartition und Recovery werden verändert.\n\n"
            "Das OpenATV-Update wird anschließend wieder gesperrt." % (source, INTERNAL_BACKUP_DIRNAME, source),
            MessageBox.TYPE_YESNO,
        )

    def do_delete_internal_backup(self, yes, state):
        if not yes or self.busy:
            return
        mp = ensure_full_mount(True)
        checked = validate_internal_backup_state(state, mp) if mp else None
        if checked is None:
            self.session.open(MessageBox, "Löschen abgebrochen: Backup konnte nicht erneut verifiziert werden.", MessageBox.TYPE_ERROR)
            return
        source = int(checked.get("source_slot"))
        backup_dir = checked.get("_backup_dir", "")
        if not internal_backup_path_is_safe(backup_dir, source, mp):
            self.session.open(MessageBox, "Löschen abgebrochen: Backup-Pfad hat sich geändert.", MessageBox.TYPE_ERROR)
            return

        self.busy = True
        self.backup_verified = False
        self.paint_update_state()
        self.pending_delete = ("internal", source, backup_dir)
        self.set_backup_progress(0, "Backup-Fortschritt – Löschen", "Status: Lösche internes Sicherheitsbackup ...")
        self.append_log("> KILLSWITCH: Lösche ausschließlich /%s/slot%d ..." % (INTERNAL_BACKUP_DIRNAME, source))
        base = internal_backup_base(mp)
        script = """
set -e
DST={dst}
BASE={base}
test -n "$DST"
test "$DST" != "/"
test -d "$DST"
test ! -L "$DST"
test -f "$DST/{meta}"
rm -rf "$DST"
sync
test ! -e "$DST"
rmdir "$BASE" 2>/dev/null || true
echo 'BACKUP_DELETED'
""".format(dst=shq(backup_dir), base=shq(base), meta=INTERNAL_BACKUP_META)
        self.connect_container(self.delete_backup_data, self.internal_delete_closed)
        self.container.execute("/bin/sh -c %s" % shq(script))

    def internal_delete_closed(self, rc):
        self.busy = False
        pending = self.pending_delete
        self.pending_delete = None
        if not pending or pending[0] != "internal":
            return
        _, source, backup_dir = pending
        deleted = (rc == 0 and not os.path.lexists(backup_dir))
        if deleted:
            st = load_state()
            if st.get("backup_mode") == "internal":
                try:
                    if os.path.exists(STATE_FILE):
                        os.unlink(STATE_FILE)
                except Exception:
                    save_state({"backup_mode": "internal", "source_slot": source, "verified": False, "deleted": datetime.now().strftime("%d.%m.%Y %H:%M")})
            self.backup_verified = False
            self.verified_backup_slot = None
            self.verified_backup_mode = None
            self.verified_backup_path = ""
            self.recovery_state = None
            self.set_backup_progress(0, "Backup-Fortschritt", "Status: Internes Backup gelöscht – Update gesperrt.")
            self["rollback"].setText("Noch kein Backup vorhanden.")
            self.append_log("> KILLSWITCH: Internes eMMC-Backup sauber gelöscht. Alle Slots blieben unangetastet.")
            self.refresh_slots()
            self.paint_update_state()
            self.session.open(MessageBox, "Internes Sicherheitsbackup wurde sauber gelöscht.\n\nKein Multiboot-Slot und keine Kernelpartition wurden verändert.\nDas Update ist wieder gesperrt.", MessageBox.TYPE_INFO)
            return

        self.backup_verified = False
        self.verified_backup_mode = None
        self.append_log("> KILLSWITCH FEHLER: Internes Backup wurde nicht vollständig gelöscht.")
        self.set_backup_progress(0, "Backup-Fortschritt – FEHLER", "Status: Löschen unvollständig – Update gesperrt.")
        self.paint_update_state()
        self.session.open(MessageBox, "Internes Backup konnte nicht vollständig gelöscht werden.\nDas Update bleibt gesperrt.", MessageBox.TYPE_ERROR)

'''
replace_once('    def request_delete_backup(self):\n', internal_delete_methods + '    def request_delete_backup(self):\n', 'internal delete methods')

replace_once(
    '''        if self.busy:\n            return\n        if not self.backup_verified or self.verified_backup_slot is None:\n''',
    '''        if self.busy:\n            return\n        if self.verified_backup_mode == "internal" or (isinstance(self.recovery_state, dict) and self.recovery_state.get("backup_mode") == "internal"):\n            self.request_delete_internal_backup()\n            return\n        if not self.backup_verified or self.verified_backup_slot is None:\n''',
    'killswitch internal dispatch'
)

restore_methods = r'''    def restore_internal_backup(self):
        if self.busy:
            return
        state = self.recovery_state
        if not isinstance(state, dict) or state.get("backup_mode") != "internal":
            found = discover_internal_backups()
            state = found[0] if found else None
        if state is None:
            self.session.open(MessageBox, "Kein verifiziertes internes Notfall-Backup vorhanden.", MessageBox.TYPE_INFO)
            return

        mp = ensure_full_mount(True)
        checked = validate_internal_backup_state(state, mp) if mp else None
        if checked is None:
            self.session.open(MessageBox, "Wiederherstellung blockiert: Backup ist nicht mehr vollständig verifizierbar.", MessageBox.TYPE_ERROR)
            return
        source = int(checked.get("source_slot"))
        current = current_slot()
        if current == source:
            self.session.open(MessageBox, "Slot %d läuft gerade.\n\nEin laufender Slot wird niemals über sich selbst wiederhergestellt. Bitte zuerst einen anderen Slot booten." % source, MessageBox.TYPE_INFO)
            return
        info = compatible_startup_slots().get(source)
        if not info or current is None:
            self.session.open(MessageBox, "Zielslot konnte nicht sicher aus STARTUP_N bestimmt werden.", MessageBox.TYPE_ERROR)
            return
        target = os.path.join(mp, info["rootsubdir"])
        active = active_source_path(mp)
        if not active or os.path.realpath(target) == os.path.realpath(active):
            self.session.open(MessageBox, "Wiederherstellung blockiert: Ziel würde den laufenden Slot treffen.", MessageBox.TYPE_ERROR)
            return
        expected = os.path.realpath(os.path.join(mp, "linuxrootfs%d" % source))
        if os.path.realpath(target) != expected or not expected.startswith(os.path.realpath(mp).rstrip("/") + "/"):
            self.session.open(MessageBox, "Wiederherstellung blockiert: Zielpfad ist nicht eindeutig.", MessageBox.TYPE_ERROR)
            return
        if os.path.lexists(target) and (not os.path.isdir(target) or os.path.islink(target)):
            self.session.open(MessageBox, "Wiederherstellung blockiert: Ziel ist kein normales Slot-Verzeichnis.", MessageBox.TYPE_ERROR)
            return
        if is_gbtrio4k():
            dst_kernel = expected_kernel_device(source)
            if not dst_kernel or dst_kernel == active_kernel_device() or not os.path.exists(dst_kernel):
                self.session.open(MessageBox, "Wiederherstellung blockiert: Kernel-Zielpartition ist nicht sicher.", MessageBox.TYPE_ERROR)
                return

        self.session.openWithCallback(
            lambda yes: self.do_restore_internal_backup(yes, checked),
            MessageBox,
            "NOTFALL-RÜCKKEHR: Slot %d aus dem internen SafeUpdate-Backup wiederherstellen?\n\n"
            "Aktuell läuft Slot %d.\n"
            "Nur Slot %d wird ersetzt; der laufende Slot, andere Images und Recovery bleiben unangetastet." % (source, current, source),
            MessageBox.TYPE_YESNO,
        )

    def do_restore_internal_backup(self, yes, state):
        if not yes or self.busy:
            return
        mp = ensure_full_mount(True)
        checked = validate_internal_backup_state(state, mp) if mp else None
        if checked is None:
            self.session.open(MessageBox, "Wiederherstellung abgebrochen: Backup-Prüfung ist nicht mehr gültig.", MessageBox.TYPE_ERROR)
            return
        source = int(checked.get("source_slot"))
        current = current_slot()
        if current is None or current == source:
            self.session.open(MessageBox, "Wiederherstellung abgebrochen: Zielslot läuft jetzt selbst.", MessageBox.TYPE_ERROR)
            return
        info = compatible_startup_slots().get(source)
        if not info:
            self.session.open(MessageBox, "Wiederherstellung abgebrochen: STARTUP-Zuordnung fehlt.", MessageBox.TYPE_ERROR)
            return
        target = os.path.join(mp, info["rootsubdir"])
        active = active_source_path(mp)
        backup_root = checked.get("_rootfs", "")
        if not active or os.path.realpath(target) == os.path.realpath(active) or not slot_root_tree_valid(backup_root):
            self.session.open(MessageBox, "Wiederherstellung abgebrochen: Sicherheitsprüfung fehlgeschlagen.", MessageBox.TYPE_ERROR)
            return

        self.busy = True
        self.pending_restore = (source, target, checked)
        self.append_log("> NOTFALL-RÜCKKEHR: Stelle Slot %d wieder her ..." % source)
        self.set_backup_progress(5, "Wiederherstellung – Prüfen", "Status: Verifiziertes Backup wird zurückgespielt ...")

        if is_gbtrio4k():
            kernel_file = os.path.join(checked.get("_backup_dir", ""), "kernel.img")
            dst_kernel = expected_kernel_device(source)
            if not dst_kernel or dst_kernel == active_kernel_device():
                self.busy = False
                self.pending_restore = None
                self.session.open(MessageBox, "Kernel-Zielpartition ist nicht sicher.", MessageBox.TYPE_ERROR)
                return
            script = """
set -e
BACKUP={backup}
TARGET={target}
KERNEL_FILE={kernel_file}
DST_KERNEL={dst_kernel}
test -d "$BACKUP"
test -f "$BACKUP/etc/image-version"
test -e "$BACKUP/sbin/init"
test -f "$BACKUP/usr/bin/enigma2"
test -f "$KERNEL_FILE"
test -b "$DST_KERNEL"
test "$TARGET" != "/"
if [ -e "$TARGET" ]; then test -d "$TARGET"; test ! -L "$TARGET"; rm -rf "$TARGET"; fi
mkdir "$TARGET"
echo 'Kopiere Image...'
cp -a "$BACKUP"/. "$TARGET"/
sync
test -f "$TARGET/etc/image-version"
test -e "$TARGET/sbin/init"
test -f "$TARGET/usr/bin/enigma2"
echo 'Stelle GigaBlue Kernel wieder her...'
dd if="$KERNEL_FILE" of="$DST_KERNEL" bs=1048576 conv=fsync 2>/dev/null
sync
SRC_HASH=$(sha256sum "$KERNEL_FILE" | awk '{{print $1}}')
DST_HASH=$(sha256sum "$DST_KERNEL" | awk '{{print $1}}')
[ -n "$SRC_HASH" ]
[ "$SRC_HASH" = "$DST_HASH" ] || exit 22
echo 'RESTORE_VERIFIED'
""".format(backup=shq(backup_root), target=shq(target), kernel_file=shq(kernel_file), dst_kernel=shq(dst_kernel))
        else:
            script = """
set -e
BACKUP={backup}
TARGET={target}
test -d "$BACKUP"
test -f "$BACKUP/zImage"
test -f "$BACKUP/etc/image-version"
test "$TARGET" != "/"
if [ -e "$TARGET" ]; then test -d "$TARGET"; test ! -L "$TARGET"; rm -rf "$TARGET"; fi
mkdir "$TARGET"
echo 'Kopiere Image...'
cp -a "$BACKUP"/. "$TARGET"/
sync
SRC_HASH=$(sha256sum "$BACKUP/zImage" | awk '{{print $1}}')
DST_HASH=$(sha256sum "$TARGET/zImage" | awk '{{print $1}}')
[ -n "$SRC_HASH" ]
[ "$SRC_HASH" = "$DST_HASH" ] || exit 22
echo 'RESTORE_VERIFIED'
""".format(backup=shq(backup_root), target=shq(target))

        self.connect_container(self.restore_data, self.restore_closed)
        self.container.execute("/bin/sh -c %s" % shq(script))

    def restore_data(self, data):
        try:
            txt = data.decode("utf-8", "replace")
        except Exception:
            txt = str(data)
        for line in txt.splitlines():
            self.append_log("> " + line)
            low = line.lower()
            if "kopiere image" in low:
                self.set_backup_progress(30, "Wiederherstellung – Kopieren", "Status: Slot wird aus Sicherheitsbackup wiederhergestellt ...")
            elif "stelle gigablue kernel" in low:
                self.set_backup_progress(90, "Wiederherstellung – Kernel", "Status: Kernel wird verifiziert zurückgespielt ...")
            elif "restore_verified" in low:
                self.set_backup_progress(99, "Wiederherstellung – Verifizieren", "Status: Abschlussprüfung ...")

    def restore_closed(self, rc):
        self.busy = False
        pending = self.pending_restore
        self.pending_restore = None
        if not pending:
            return
        source, target, state = pending
        ok = (rc == 0 and slot_root_tree_valid(target))
        if ok and is_gbtrio4k():
            kernel_hash = state.get("kernel_sha256", "")
            ok = bool(kernel_hash and sha256_prefix(expected_kernel_device(source)) == kernel_hash)
        elif ok:
            ok = sha256_prefix(os.path.join(target, "zImage")) == state.get("kernel_sha256", "")
        if ok:
            self.set_backup_progress(100, "Wiederherstellung – Fertig", "Status: Slot %d erfolgreich wiederhergestellt." % source)
            self.append_log("> NOTFALL-RÜCKKEHR: Slot %d erfolgreich verifiziert wiederhergestellt." % source)
            self.session.open(MessageBox, "Slot %d wurde erfolgreich aus dem internen Sicherheitsbackup wiederhergestellt.\n\nDu kannst jetzt in Slot %d booten. Das Sicherheitsbackup bleibt erhalten." % (source, source), MessageBox.TYPE_INFO)
        else:
            self.set_backup_progress(0, "Wiederherstellung – FEHLER", "Status: Wiederherstellung nicht vollständig verifiziert.")
            self.append_log("> NOTFALL-RÜCKKEHR FEHLER: Slot %d nicht verifiziert." % source)
            self.session.open(MessageBox, "Wiederherstellung konnte nicht vollständig verifiziert werden.\nDas interne Sicherheitsbackup wurde NICHT gelöscht und kann erneut verwendet werden.", MessageBox.TYPE_ERROR)

'''
replace_once('    def start_update(self):\n', restore_methods + '    def start_update(self):\n', 'restore methods')

# Details should make the fallback explicit without pretending /media/usb is required.
replace_once(
    '            "Letztes Backup: %s"\n',
    '            "Backup-Modus: %s\\n"\n'
    '            "Letztes Backup: %s"\n',
    'details format label'
)
replace_once(
    '            ", ".join(str(x) for x in self.slots) or "keine", st.get("created", "keins")\n',
    '            ", ".join(str(x) for x in self.slots) or "keine", st.get("backup_mode", "slot"), st.get("created", "keins")\n',
    'details format values'
)

with open(path, "w", encoding="utf-8") as f:
    f.write(s)

print("r32 patch applied")
