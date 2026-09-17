from pathlib import Path
import re
import sys

p = Path(sys.argv[1])
s = p.read_text(encoding="utf-8")


def one(old, new, label):
    global s
    n = s.count(old)
    if n != 1:
        raise SystemExit("%s: expected 1 match, got %d" % (label, n))
    s = s.replace(old, new, 1)


one('PLUGIN_VERSION = "2026.1-r29"', 'PLUGIN_VERSION = "2026.1-r30"', 'version')

marker = '''KERNEL_PACKAGES = (
    "kernel-4.1.45-1.17",
    "kernel-image-4.1.45-1.17",
    "kernel-image-zimage-4.1.45-1.17",
)
'''
injected = marker + '''
# r30: verified GigaBlue UHD Trio 4K layout from the real test receiver.
GBTRIO4K_KERNEL_PACKAGES = (
    "kernel-4.4.35",
    "kernel-image-4.4.35",
    "kernel-image-uimage-4.4.35",
)
GBTRIO4K_ROOT_DEVICE = "/dev/mmcblk0p16"
GBTRIO4K_KERNEL_DEVICES = {
    1: "/dev/mmcblk0p12",
    2: "/dev/mmcblk0p13",
    3: "/dev/mmcblk0p14",
    4: "/dev/mmcblk0p15",
}
'''
one(marker, injected, 'gb constants')

# Insert GigaBlue helpers after cmd_value(), so cmd_value itself is already defined.
cmd_value_block = '''def cmd_value(name, text=None):
    c = cmdline() if text is None else str(text)
    m = re.search(r"(?:^|\\s)%s=([^\\s]+)" % re.escape(name), c)
    return m.group(1) if m else ""
'''
cmd_value_injected = cmd_value_block + '''

def machinebuild():
    return cmd_value("MACHINEBUILD").strip().lower()


def oem_name():
    return cmd_value("OEM").strip().lower()


def is_gbtrio4k():
    # /proc/stb/info/model reports dm8000 on the tested receiver, so use cmdline identity.
    return machinebuild() == "gbtrio4k" and oem_name() == "gigablue"


def kernel_packages():
    return GBTRIO4K_KERNEL_PACKAGES if is_gbtrio4k() else KERNEL_PACKAGES


def active_kernel_device():
    value = cmd_value("kernel").strip()
    return os.path.realpath(value) if value.startswith("/dev/") else ""


def expected_kernel_device(slot):
    if not is_gbtrio4k():
        return ""
    try:
        return os.path.realpath(GBTRIO4K_KERNEL_DEVICES[int(slot)])
    except Exception:
        return ""
'''
one(cmd_value_block, cmd_value_injected, 'identity helpers')

# STARTUP parser: retain classic in-tree zImage support and accept a dedicated kernel block device.
pat = re.compile(r'^def parse_startup_text\(slot, text, path=""\):.*?^def startup_slots\(\):', re.M | re.S)
repl = '''def parse_startup_text(slot, text, path=""):
    root = ""
    rootsubdir = ""
    kernel = ""

    m = re.search(r"(?:^|\\s)root=([^\\s]+)", text or "")
    if m:
        root = m.group(1)
    m = re.search(r"(?:^|\\s)rootsubdir=([^\\s]+)", text or "")
    if m:
        rootsubdir = m.group(1)
    m = re.search(r"(?:^|\\s)kernel=([^\\s]+)", text or "")
    if m:
        kernel = m.group(1)

    rootsubdir = safe_rootsubdir(rootsubdir, slot)
    if not root or not rootsubdir or not kernel:
        return None

    kernel_norm = os.path.normpath(kernel.strip().lstrip("/"))
    expected_tree_kernel = os.path.join(rootsubdir, "zImage")
    kernel_in_tree = kernel_norm == expected_tree_kernel
    kernel_device = os.path.realpath(kernel) if kernel.startswith("/dev/") else ""
    if not kernel_in_tree and not kernel_device:
        return None

    dev = resolve_root_spec(root)
    if not dev:
        return None

    return {
        "slot": int(slot),
        "path": path,
        "root_spec": root,
        "root_device": dev,
        "rootsubdir": rootsubdir,
        "kernel": kernel,
        "kernel_device": kernel_device,
        "kernel_in_tree": kernel_in_tree,
    }


def startup_slots():'''
s, n = pat.subn(repl, s, count=1)
if n != 1:
    raise SystemExit('parse_startup_text replacement failed')

old_full = '''def _full_mount_is_valid(mountpoint):
    sub = active_rootsubdir()
    if not mountpoint or not sub:
        return False
    src = os.path.join(mountpoint, sub)
    return (
        os.path.isdir(src) and
        os.path.isfile(os.path.join(src, "zImage")) and
        os.path.isfile(os.path.join(src, "etc", "image-version"))
    )
'''
new_full = '''def slot_root_tree_valid(path):
    common = (
        os.path.isdir(path) and
        os.path.isfile(os.path.join(path, "etc", "image-version")) and
        os.path.exists(os.path.join(path, "sbin", "init")) and
        os.path.isfile(os.path.join(path, "usr", "bin", "enigma2"))
    )
    if not common:
        return False
    if is_gbtrio4k():
        return True
    return os.path.isfile(os.path.join(path, "zImage"))


def _full_mount_is_valid(mountpoint):
    sub = active_rootsubdir()
    if not mountpoint or not sub:
        return False
    return slot_root_tree_valid(os.path.join(mountpoint, sub))
'''
one(old_full, new_full, 'full mount validation')

old_kexec = '''def kexec_ok():
    return sha256_prefix(KEXEC_DEVICE, KEXEC_SIZE) == KEXEC_GOOD_HASH
'''
new_kexec = '''def gigablue_kernel_layout_ok():
    if not is_gbtrio4k():
        return False
    slot = current_slot()
    if slot not in GBTRIO4K_KERNEL_DEVICES:
        return False
    if os.path.realpath(root_device() or "") != os.path.realpath(GBTRIO4K_ROOT_DEVICE):
        return False
    if active_kernel_device() != expected_kernel_device(slot):
        return False
    slots = startup_slots()
    for number, device in sorted(GBTRIO4K_KERNEL_DEVICES.items()):
        info = slots.get(number)
        if not info:
            return False
        if info.get("rootsubdir") != "linuxrootfs%d" % number:
            return False
        if os.path.realpath(info.get("root_device") or "") != os.path.realpath(GBTRIO4K_ROOT_DEVICE):
            return False
        if os.path.realpath(info.get("kernel_device") or "") != os.path.realpath(device):
            return False
    return True


def kexec_ok():
    # VU+ retains its established KEXEC hash check. GigaBlue verifies native kernel slots.
    if is_gbtrio4k():
        return gigablue_kernel_layout_ok()
    return sha256_prefix(KEXEC_DEVICE, KEXEC_SIZE) == KEXEC_GOOD_HASH


def kernel_device_for_slot(slot):
    try:
        info = startup_slots().get(int(slot))
    except Exception:
        info = None
    if not info:
        return ""
    return os.path.realpath(info.get("kernel_device") or "")


def slot_backup_valid(slot, path, expected_kernel_hash=""):
    if not slot_root_tree_valid(path):
        return False
    if not is_gbtrio4k():
        return True
    kernel_dev = kernel_device_for_slot(slot)
    if not kernel_dev or not os.path.exists(kernel_dev):
        return False
    target_hash = sha256_prefix(kernel_dev)
    if not target_hash:
        return False
    if expected_kernel_hash:
        return target_hash == expected_kernel_hash
    source_dev = active_kernel_device()
    source_hash = sha256_prefix(source_dev) if source_dev else ""
    return bool(source_hash and target_hash == source_hash)
'''
one(old_kexec, new_kexec, 'kernel guard')

old_holds = '''def holds_ok():
    return all(package_on_hold(p) for p in KERNEL_PACKAGES)
'''
new_holds = '''def holds_ok():
    return all(package_on_hold(p) for p in kernel_packages())


def ensure_kernel_holds():
    for package in kernel_packages():
        try:
            if subprocess.call(["opkg", "flag", "hold", package]) != 0:
                return False
        except Exception:
            return False
    return holds_ok()
'''
one(old_holds, new_holds, 'dynamic hold packages')

# GigaBlue backup may proceed only when its observed kernel mapping still matches exactly.
start_marker = '''    def start_backup(self):
        if self.busy:
            return
'''
start_repl = '''    def start_backup(self):
        if self.busy:
            return
        if is_gbtrio4k() and not gigablue_kernel_layout_ok():
            self.session.open(MessageBox, "GigaBlue Kernel-/Slot-Struktur ist nicht eindeutig verifizierbar.\\nBackup bleibt gesperrt.", MessageBox.TYPE_ERROR)
            return
'''
one(start_marker, start_repl, 'start backup gb guard')

one('''        if not os.path.isfile(os.path.join(src, "zImage")) or not os.path.isfile(os.path.join(src, "etc", "image-version")):
''', '''        if not slot_root_tree_valid(src):
''', 'backup source validation')

# Replace the do_backup copy script only.
script_pat = re.compile(r'        script = """\nset -e\nSRC=\{src\}.*?"""\.format\(src=shq\(src\), dst=shq\(dst\)\)', re.S)
script_repl = '''        if is_gbtrio4k():
            src_kernel = active_kernel_device()
            dst_kernel = kernel_device_for_slot(target)
            if (not gigablue_kernel_layout_ok() or not src_kernel or not dst_kernel or
                    src_kernel == dst_kernel or dst_kernel != expected_kernel_device(target)):
                self.busy = False
                self.backup_dst = ""
                self.backup_total_bytes = 0
                self.set_backup_progress(0, "Backup-Fortschritt – FEHLER", "Status: GigaBlue Kernel-Slot nicht sicher verifizierbar.")
                self.session.open(MessageBox, "GigaBlue Kernel-Slot ist nicht sicher verifizierbar.\\nEs wurde kein Backup gestartet.", MessageBox.TYPE_ERROR)
                return
            script = """
set -e
SRC={src}
DST={dst}
SRC_KERNEL={src_kernel}
DST_KERNEL={dst_kernel}

test -d "$SRC"
test -f "$SRC/etc/image-version"
test -e "$SRC/sbin/init"
test -f "$SRC/usr/bin/enigma2"
test -b "$SRC_KERNEL"
test -b "$DST_KERNEL"
test ! -e "$DST"

echo 'Zielslot ist weiterhin frei.'
mkdir "$DST"
echo 'Synchronisiere Dateisystem...'
sync
echo 'Kopiere Image...'
cp -a "$SRC"/. "$DST"/
sync

test -f "$DST/etc/image-version"
test -e "$DST/sbin/init"
test -f "$DST/usr/bin/enigma2"

echo 'Kopiere GigaBlue Kernel-Slot...'
dd if="$SRC_KERNEL" of="$DST_KERNEL" bs=1048576 conv=fsync 2>/dev/null
sync
SRC_HASH=$(sha256sum "$SRC_KERNEL" | awk '{{print $1}}')
DST_HASH=$(sha256sum "$DST_KERNEL" | awk '{{print $1}}')
echo "Quelle zImage: $SRC_HASH"
echo "Backup zImage: $DST_HASH"
[ -n "$SRC_HASH" ]
[ "$SRC_HASH" = "$DST_HASH" ] || exit 22

echo 'BACKUP_VERIFIED'
""".format(src=shq(src), dst=shq(dst), src_kernel=shq(src_kernel), dst_kernel=shq(dst_kernel))
        else:
            script = """
set -e
SRC={src}
DST={dst}

test -d "$SRC"
test -f "$SRC/zImage"
test -f "$SRC/etc/image-version"
test ! -e "$DST"

echo 'Zielslot ist weiterhin frei.'
mkdir "$DST"
echo 'Synchronisiere Dateisystem...'
sync
echo 'Kopiere Image...'
cp -a "$SRC"/. "$DST"/
sync

test -f "$DST/zImage"
test -f "$DST/etc/image-version"

SRC_HASH=$(sha256sum "$SRC/zImage" | awk '{{print $1}}')
DST_HASH=$(sha256sum "$DST/zImage" | awk '{{print $1}}')
echo "Quelle zImage: $SRC_HASH"
echo "Backup zImage: $DST_HASH"
[ "$SRC_HASH" = "$DST_HASH" ] || exit 22

echo 'BACKUP_VERIFIED'
""".format(src=shq(src), dst=shq(dst))'''
s, n = script_pat.subn(script_repl, s, count=1)
if n != 1:
    raise SystemExit('backup script replacement failed')

one('''        verified = rc == 0 and os.path.isfile(os.path.join(dst, "zImage")) and os.path.isfile(os.path.join(dst, "etc", "image-version"))
''', '''        verified = rc == 0 and slot_backup_valid(target, dst)
''', 'backup closed validation')

old_save = '''            save_state({"source_slot": source, "target_slot": target, "created": created, "verified": True, "build": image_info().get("build", "")})
'''
new_save = '''            state = {"source_slot": source, "target_slot": target, "created": created, "verified": True, "build": image_info().get("build", "")}
            if is_gbtrio4k():
                state["kernel_device"] = kernel_device_for_slot(target)
                state["kernel_sha256"] = sha256_prefix(state["kernel_device"])
            save_state(state)
'''
one(old_save, new_save, 'backup state kernel hash')

# Revalidate saved backup after restart using rootfs + saved kernel hash on GigaBlue.
rollback_pat = re.compile(r'^    def load_rollback\(self\):.*?^    def paint_update_state\(self\):', re.M | re.S)
rollback_repl = '''    def load_rollback(self):
        st = load_state()
        if not st:
            return
        valid = False
        target = st.get("target_slot")
        source = st.get("source_slot")
        if st.get("verified") and source == current_slot() and target is not None:
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
            self["targetSlot"].setText("Slot %s – VERIFIZIERT ✓" % target)
            self.set_backup_progress(100, "Backup-Fortschritt – Fertig", "Status: Backup in Slot %s verifiziert." % target)
            created = (st.get("created") or "?").split(" ")[0]
            self["rollback"].setText("Backup-Slot:  %s\\nQuelle:       Slot %s\\nErstellt:     %s\\n0 = BACKUP LÖSCHEN" % (target, source, created))
            self.append_log("> Gespeichertes Backup erneut geprüft: Slot %s OK." % target)
        elif st.get("verified"):
            self.backup_verified = False
            self.verified_backup_slot = None
            self.set_backup_progress(0, "Backup-Fortschritt", "Status: Gespeichertes Backup fehlt – Update gesperrt.")
            self["rollback"].setText("Noch kein gültiges Backup vorhanden.")
            self.append_log("> Alter Backup-Status verworfen: Backup physisch nicht mehr verifizierbar.")
            try:
                st["verified"] = False
                st["invalidated"] = datetime.now().strftime("%d.%m.%Y %H:%M")
                save_state(st)
            except Exception:
                pass

    def paint_update_state(self):'''
s, n = rollback_pat.subn(rollback_repl, s, count=1)
if n != 1:
    raise SystemExit('load_rollback replacement failed')

# Delete path check: on GigaBlue there is no zImage inside linuxrootfsN.
one('''            os.path.isdir(dst) and
            os.path.isfile(os.path.join(dst, "zImage")) and
            os.path.isfile(os.path.join(dst, "etc", "image-version")) and
''', '''            os.path.isdir(dst) and
            slot_root_tree_valid(dst) and
            os.path.isfile(os.path.join(dst, "etc", "image-version")) and
''', 'delete safe path')

# Make delete shell script layout-aware while retaining the final race checks.
delete_pat = re.compile(r'        script = """\nset -e\nDST=\{dst\}\ntest -n "\$DST".*?echo \'BACKUP_DELETED\'\n"""\.format\(dst=shq\(current_dst\)\)', re.S)
delete_repl = '''        if is_gbtrio4k():
            script = """
set -e
DST={dst}
test -n "$DST"
test "$DST" != "/"
test -d "$DST"
test ! -L "$DST"
test -f "$DST/etc/image-version"
test -e "$DST/sbin/init"
test -f "$DST/usr/bin/enigma2"
rm -rf "$DST"
sync
test ! -e "$DST"
echo 'BACKUP_DELETED'
""".format(dst=shq(current_dst))
        else:
            script = """
set -e
DST={dst}
test -n "$DST"
test "$DST" != "/"
test -d "$DST"
test ! -L "$DST"
test -f "$DST/zImage"
test -f "$DST/etc/image-version"
rm -rf "$DST"
sync
test ! -e "$DST"
echo 'BACKUP_DELETED'
""".format(dst=shq(current_dst))'''
s, n = delete_pat.subn(delete_repl, s, count=1)
if n != 1:
    raise SystemExit('delete script replacement failed')

# GigaBlue: apply the observed 4.4.35 HOLDs from the UI; no extra SSH command required.
old_hold_block = '''        if not holds_ok():
            self.session.open(MessageBox, "Nicht alle Kernel-Pakete stehen auf HOLD. Update wird blockiert.", MessageBox.TYPE_ERROR)
            return
'''
new_hold_block = '''        if not holds_ok():
            if is_gbtrio4k():
                self.append_log("> Setze GigaBlue Kernel-Pakete auf HOLD...")
                if not ensure_kernel_holds():
                    self.session.open(MessageBox, "GigaBlue Kernel-Pakete konnten nicht sicher auf HOLD gesetzt werden. Update wird blockiert.", MessageBox.TYPE_ERROR)
                    return
                self.refresh_status()
            else:
                self.session.open(MessageBox, "Nicht alle Kernel-Pakete stehen auf HOLD. Update wird blockiert.", MessageBox.TYPE_ERROR)
                return
'''
one(old_hold_block, new_hold_block, 'start update hold handling')
one('''        hold_cmd = "; ".join("opkg flag hold %s >/dev/null 2>&1 || true" % shq(p) for p in KERNEL_PACKAGES)
''', '''        hold_cmd = "; ".join("opkg flag hold %s >/dev/null 2>&1 || true" % shq(p) for p in kernel_packages())
''', 'update hold command')

# The VU+ kexec guard is not a valid post-update test for this GigaBlue layout.
one('''        if os.path.isfile("/usr/local/sbin/kexec-guard.sh"):
            guard_ok = subprocess.call(["/usr/local/sbin/kexec-guard.sh"]) == 0
''', '''        if (not is_gbtrio4k()) and os.path.isfile("/usr/local/sbin/kexec-guard.sh"):
            guard_ok = subprocess.call(["/usr/local/sbin/kexec-guard.sh"]) == 0
''', 'post update guard')

p.write_text(s, encoding="utf-8")
compile(p.read_bytes(), str(p), "exec")

# Static safety invariants.
s = p.read_text(encoding="utf-8")
checks = [
    'PLUGIN_VERSION = "2026.1-r30"',
    'GBTRIO4K_ROOT_DEVICE = "/dev/mmcblk0p16"',
    '1: "/dev/mmcblk0p12"',
    '4: "/dev/mmcblk0p15"',
    '"kernel-4.4.35"',
    'def gigablue_kernel_layout_ok():',
    'dd if="$SRC_KERNEL" of="$DST_KERNEL"',
    'resolution="1920,1080"',
    'scale="1"',
]
for item in checks:
    if item not in s:
        raise SystemExit('missing r30 invariant: %s' % item)
if 'for p in KERNEL_PACKAGES)' in s:
    raise SystemExit('old fixed hold package loop still present')
print('r30 patch + syntax + invariants: OK')
