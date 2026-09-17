# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import re
import json
import hashlib
import subprocess
import glob
from datetime import datetime

from Plugins.Plugin import PluginDescriptor
from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from Components.Label import Label
from Components.ActionMap import ActionMap
from Components.ProgressBar import ProgressBar
from enigma import eConsoleAppContainer, eTimer, ePoint
from skin import parseColor

PLUGIN_NAME = "Safe Update 2026"
PLUGIN_VERSION = "2026.1-r29"

KEXEC_DEVICE = "/dev/mmcblk0p6"
KEXEC_SIZE = 6483040
KEXEC_GOOD_HASH = "361e9dfddcc4e23ec566608ddf22778779256919728b53b00d244466071b2cdf"

KERNEL_PACKAGES = (
    "kernel-4.1.45-1.17",
    "kernel-image-4.1.45-1.17",
    "kernel-image-zimage-4.1.45-1.17",
)

FULL_MOUNT = "/tmp/safeupdate2026-full"
STATE_FILE = "/etc/enigma2/safeupdate2026.json"
LOG_FILE = "/tmp/safeupdate2026.log"


def read_text(path, default=""):
    try:
        with open(path, "r") as f:
            return f.read()
    except Exception:
        return default


def run_cmd(args):
    try:
        return subprocess.check_output(args, stderr=subprocess.STDOUT).decode("utf-8", "replace")
    except Exception:
        return ""


def image_info():
    data = {}
    for line in read_text("/etc/image-version").splitlines():
        if "=" in line:
            key, val = line.split("=", 1)
            data[key.strip()] = val.strip()
    return data


def cmdline():
    return read_text("/proc/cmdline").strip()


def cmd_value(name, text=None):
    c = cmdline() if text is None else str(text)
    m = re.search(r"(?:^|\s)%s=([^\s]+)" % re.escape(name), c)
    return m.group(1) if m else ""


def current_slot():
    sub = cmd_value("rootsubdir")
    m = re.search(r"(?:^|/)linuxrootfs(\d+)$", sub)
    if m:
        return int(m.group(1))

    kern = cmd_value("kernel")
    m = re.search(r"(?:^|/)linuxrootfs(\d+)/zImage$", kern)
    return int(m.group(1)) if m else None


def root_spec():
    return cmd_value("root")


def resolve_root_spec(spec):
    spec = (spec or "").strip()
    if not spec:
        return ""

    if spec.startswith("/dev/"):
        return os.path.realpath(spec)

    if spec.startswith("UUID="):
        return os.path.realpath(run_cmd(["blkid", "-U", spec[5:]]).strip())

    if spec.startswith("LABEL="):
        return os.path.realpath(run_cmd(["blkid", "-L", spec[6:]]).strip())

    if spec.startswith("PARTUUID="):
        out = run_cmd(["blkid", "-t", "PARTUUID=%s" % spec[9:], "-o", "device"]).strip()
        return os.path.realpath(out)

    return ""


def root_device():
    return resolve_root_spec(root_spec())


def active_rootsubdir():
    raw = cmd_value("rootsubdir").strip().strip("/")
    if not raw:
        return ""
    norm = os.path.normpath(raw)
    if norm == ".." or norm.startswith("../"):
        return ""
    return norm


def safe_rootsubdir(raw, slot):
    raw = (raw or "").strip().strip("/")
    if not raw:
        return ""
    norm = os.path.normpath(raw)
    if norm == ".." or norm.startswith("../"):
        return ""
    if norm != raw:
        return ""
    m = re.search(r"(?:^|/)linuxrootfs(\d+)$", norm)
    if not m or int(m.group(1)) != int(slot):
        return ""
    return norm


def parse_startup_text(slot, text, path=""):
    root = ""
    rootsubdir = ""
    kernel = ""

    m = re.search(r"(?:^|\s)root=([^\s]+)", text or "")
    if m:
        root = m.group(1)

    m = re.search(r"(?:^|\s)rootsubdir=([^\s]+)", text or "")
    if m:
        rootsubdir = m.group(1)

    m = re.search(r"(?:^|\s)kernel=([^\s]+)", text or "")
    if m:
        kernel = m.group(1)

    rootsubdir = safe_rootsubdir(rootsubdir, slot)
    if not root or not rootsubdir or not kernel:
        return None

    # Fail closed: this backup method is only safe when the slot's STARTUP
    # points its kernel into the same linuxrootfsN tree that will be cloned.
    kernel_norm = os.path.normpath(kernel.strip().lstrip("/"))
    expected_kernel = os.path.join(rootsubdir, "zImage")
    if kernel_norm != expected_kernel:
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
    }


def startup_slots():
    result = {}
    for path in sorted(glob.glob("/boot/STARTUP_*")):
        base = os.path.basename(path)
        m = re.match(r"^STARTUP_(\d+)$", base)
        if not m:
            continue
        slot = int(m.group(1))
        info = parse_startup_text(slot, read_text(path), path)
        if info is not None:
            result[slot] = info
    return result


def same_device(a, b):
    a = os.path.realpath(a or "")
    b = os.path.realpath(b or "")
    return bool(a and b and a == b)


def _decode_mount_field(value):
    return (value
            .replace("\\040", " ")
            .replace("\\011", "\t")
            .replace("\\012", "\n")
            .replace("\\134", "\\"))


def mount_entries():
    rows = []
    for line in read_text("/proc/mounts").splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        rows.append({
            "source": _decode_mount_field(parts[0]),
            "mountpoint": _decode_mount_field(parts[1]),
            "fstype": parts[2],
            "options": parts[3].split(","),
        })
    return rows


def _full_mount_is_valid(mountpoint):
    sub = active_rootsubdir()
    if not mountpoint or not sub:
        return False
    src = os.path.join(mountpoint, sub)
    return (
        os.path.isdir(src) and
        os.path.isfile(os.path.join(src, "zImage")) and
        os.path.isfile(os.path.join(src, "etc", "image-version"))
    )


def _mount_entry_for_path(path):
    path = os.path.realpath(path)
    for row in mount_entries():
        if os.path.realpath(row["mountpoint"]) == path:
            return row
    return None


def _device_mount_profile(dev):
    fstype = ""
    rw_mounted = False
    for row in mount_entries():
        if not same_device(row.get("source"), dev):
            continue
        if not fstype and row.get("fstype"):
            fstype = row.get("fstype")
        if "rw" in row.get("options", []):
            rw_mounted = True
    return fstype, rw_mounted


def ensure_full_mount(writable=False):
    """Return a verified full-filesystem view of the active multiboot device."""
    dev = root_device()
    sub = active_rootsubdir()
    if not dev or not sub:
        return ""

    if os.path.ismount(FULL_MOUNT):
        row = _mount_entry_for_path(FULL_MOUNT)
        if not row or not same_device(row["source"], dev) or not _full_mount_is_valid(FULL_MOUNT):
            return ""
        if writable and "ro" in row["options"]:
            if subprocess.call(["mount", "-o", "remount,rw", FULL_MOUNT]) != 0:
                return ""
        return FULL_MOUNT

    for row in mount_entries():
        if not same_device(row["source"], dev):
            continue
        mp = row["mountpoint"]
        if not _full_mount_is_valid(mp):
            continue
        if writable and "ro" in row["options"]:
            continue
        return mp

    try:
        if not os.path.isdir(FULL_MOUNT):
            os.makedirs(FULL_MOUNT)
    except Exception:
        return ""

    # KEXEC rootsubdir systems often have this same device already mounted rw
    # as '/'. A second ro mount can fail with EBUSY, so discovery uses the same
    # rw mode if needed. Merely mounting rw does not change files.
    fstype, dev_rw = _device_mount_profile(dev)
    mode = "rw" if (writable or dev_rw) else "ro"
    args = ["mount"]
    if fstype:
        args += ["-t", fstype]
    args += ["-o", mode, dev, FULL_MOUNT]
    if subprocess.call(args) != 0:
        return ""

    if not _full_mount_is_valid(FULL_MOUNT):
        try:
            subprocess.call(["umount", FULL_MOUNT])
        except Exception:
            pass
        return ""
    return FULL_MOUNT


def active_source_path(mountpoint=None):
    mp = mountpoint or ensure_full_mount(False)
    sub = active_rootsubdir()
    if not mp or not sub:
        return ""
    return os.path.join(mp, sub)


def compatible_startup_slots():
    dev = root_device()
    result = {}
    if not dev:
        return result
    for slot, info in startup_slots().items():
        if same_device(info.get("root_device"), dev):
            result[slot] = info
    return result


def slot_path(slot, mountpoint=None):
    info = compatible_startup_slots().get(int(slot))
    if not info:
        return ""
    mp = mountpoint or ensure_full_mount(False)
    if not mp:
        return ""
    return os.path.join(mp, info["rootsubdir"])


def is_strictly_empty_dir(path):
    try:
        return os.path.isdir(path) and not os.path.islink(path) and len(os.listdir(path)) == 0
    except Exception:
        return False


def slot_is_verified_free(info, mountpoint):
    if not info or not mountpoint:
        return False
    path = os.path.join(mountpoint, info["rootsubdir"])
    # OpenATV Delete can leave an empty linuxrootfsN directory behind.
    # Only a completely empty real directory is reusable; partial images stay blocked.
    return (not os.path.lexists(path)) or is_strictly_empty_dir(path)


def free_slots():
    """
    A slot is offered only when:
    - a numeric /boot/STARTUP_N exists and passes strict validation,
    - it belongs to the same multiboot root device as the running slot,
    - the running slot is verifiably visible in a full-filesystem view,
    - the target linuxrootfsN path does not exist, or is a strictly empty OpenATV delete-remnant.
    """
    active = current_slot()
    mp = ensure_full_mount(False)
    if active is None or not mp:
        return []

    src = active_source_path(mp)
    if not src or not os.path.isdir(src):
        return []

    result = []
    for slot, info in sorted(compatible_startup_slots().items()):
        if slot == active:
            continue
        if slot_is_verified_free(info, mp):
            result.append(slot)
    return result


def tree_size_bytes(path):
    try:
        out = subprocess.check_output(["du", "-sk", path], stderr=subprocess.STDOUT)
        kb = int(out.decode("utf-8", "replace").split()[0])
        return kb * 1024
    except Exception:
        return 0


def filesystem_free_bytes(path):
    try:
        st = os.statvfs(path)
        return int(st.f_bavail) * int(st.f_frsize)
    except Exception:
        return 0


def sha256_prefix(path, size=None):
    h = hashlib.sha256()
    try:
        with open(path, "rb", buffering=0) as f:
            left = size
            while True:
                n = 1024 * 1024
                if left is not None:
                    if left <= 0:
                        break
                    n = min(n, left)
                chunk = f.read(n)
                if not chunk:
                    break
                h.update(chunk)
                if left is not None:
                    left -= len(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def kexec_ok():
    return sha256_prefix(KEXEC_DEVICE, KEXEC_SIZE) == KEXEC_GOOD_HASH


def hdd_ok():
    for line in read_text("/proc/mounts").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "/media/usb":
            return True
    return False


def _clean_hw_value(value):
    value = str(value or "").strip()
    if not value or value.lower() in ("unknown", "none", "n/a", "null"):
        return ""
    return value


def detect_box_identity():
    """Return a user-facing (brand, model) without assuming a specific receiver vendor."""
    brand = ""
    model_candidates = []

    def add_model(value):
        value = _clean_hw_value(value)
        if value and value not in model_candidates:
            model_candidates.append(value)

    # OpenATV/OE-A SystemInfo is preferred when available. Some images return
    # only the vendor name as displaymodel; keep collecting fallbacks instead
    # of displaying e.g. "GigaBlue GigaBlue".
    try:
        from Components.SystemInfo import BoxInfo
        for key in ("displaybrand", "brand", "manufacturer"):
            value = _clean_hw_value(BoxInfo.getItem(key))
            if value:
                brand = value
                break
        for key in ("displaymodel", "model", "machinebuild", "boxtype", "machine"):
            add_model(BoxInfo.getItem(key))
    except Exception:
        pass

    # Cross-image fallbacks.
    if not brand:
        for path in ("/proc/stb/info/brand", "/proc/stb/info/manufacturer"):
            value = _clean_hw_value(read_text(path))
            if value:
                brand = value
                break
    for path in ("/proc/stb/info/model", "/proc/stb/info/boxtype", "/proc/stb/info/machinebuild"):
        add_model(read_text(path))

    info = image_info()
    for key in ("displaymodel", "model", "box_type", "machinebuild", "machine"):
        add_model(info.get(key))

    # Normalize common brand spelling before filtering model candidates.
    b = brand.lower().replace(" ", "")
    if b in ("vuplus", "vu+"):
        brand = "VU+"
    elif b == "gigablue":
        brand = "GigaBlue"
    elif b == "octagon":
        brand = "Octagon"

    def norm(value):
        return re.sub(r"[^a-z0-9+]", "", (value or "").lower())

    # Human-friendly names for common receiver families.
    aliases = {
        "vuduo4kse": ("VU+", "Duo 4K SE"),
        "vuduo4k": ("VU+", "Duo 4K"),
        "vuuno4kse": ("VU+", "Uno 4K SE"),
        "vuuno4k": ("VU+", "Uno 4K"),
        "vusolo4k": ("VU+", "Solo 4K"),
        "vuzero4k": ("VU+", "Zero 4K"),
        "sf8008": ("Octagon", "SF8008"),
        "sf8008m": ("Octagon", "SF8008 M"),
        "sf8008s": ("Octagon", "SF8008 S"),
        "sf8008t": ("Octagon", "SF8008 T"),
        "sf8008combo": ("Octagon", "SF8008 Combo"),
        "sf8008supreme": ("Octagon", "SF8008 Supreme"),
        "sf4008": ("Octagon", "SF4008"),
        "gbquad4k": ("GigaBlue", "UHD Quad 4K"),
        "gbquad4kpro": ("GigaBlue", "UHD Quad 4K Pro"),
        "gbue4k": ("GigaBlue", "UHD UE 4K"),
        "gbx34k": ("GigaBlue", "UHD X3 4K"),
        "gbtrio4k": ("GigaBlue", "UHD Trio 4K"),
        "gbtrio4kpro": ("GigaBlue", "UHD Trio 4K Pro"),
    }

    alias = None
    for candidate in model_candidates:
        key = norm(candidate)
        if key in aliases:
            alias = aliases[key]
            break
    if alias:
        brand, model = alias
        return brand, model

    # Pick the first candidate that is more informative than the vendor name.
    model = ""
    brand_norm = norm(brand)
    generic_values = {"receiver", "settopbox", "stb", "enigma2", brand_norm}
    for candidate in model_candidates:
        c = norm(candidate)
        if c and c not in generic_values:
            model = candidate.strip()
            break

    # Derive a conservative brand only from unmistakable model prefixes.
    low = norm(model or (model_candidates[0] if model_candidates else ""))
    if not brand:
        if low.startswith("vu"):
            brand = "VU+"
        elif low.startswith("sf"):
            brand = "Octagon"
        elif low.startswith("gb"):
            brand = "GigaBlue"
        else:
            brand = "Receiver"

    if not model:
        model = ""

    return brand, model

# r26: restore the classic VU+ Duo 4K SE hero artwork only on that box.
# Other receivers (GigaBlue/Octagon/etc.) keep the vendor-neutral r25 artwork.
_BOOT_BRAND, _BOOT_MODEL = detect_box_identity()
def _hw_norm(value):
    return re.sub(r"[^a-z0-9+]", "", (value or "").lower())

_USE_CLASSIC_VU_DUO4KSE = (
    _BOOT_BRAND == "VU+" and _hw_norm(_BOOT_MODEL) in ("duo4kse", "vuduo4kse")
)
_BACKGROUND_FILE = (
    "background_vu_duo4kse.png" if _USE_CLASSIC_VU_DUO4KSE else "background_generic.png"
)
_BACKGROUND_PATH = "/usr/lib/enigma2/python/Plugins/Extensions/SafeUpdate2026/" + _BACKGROUND_FILE

def package_on_hold(package):
    out = run_cmd(["opkg", "status", package])
    for line in out.splitlines():
        if line.startswith("Status:"):
            return " hold " in (" " + line + " ")
    return False


def holds_ok():
    return all(package_on_hold(p) for p in KERNEL_PACKAGES)

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(data):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        return True
    except Exception:
        return False


def shq(s):
    return "'" + str(s).replace("'", "'\"'\"'") + "'"


class SafeUpdateScreen(Screen):
    skin = '''
    <screen name="SafeUpdateScreen" position="0,0" size="1920,1080" resolution="1920,1080" flags="wfNoBorder" backgroundColor="#000b14">
        <ePixmap zPosition="0" position="0,0" size="1920,1080"
                 pixmap="__BACKGROUND_PATH__"
                 scale="1" alphatest="on" />

        <!-- live time/date, aligned to approved preview -->
        <widget zPosition="20" name="clock" position="1755,9" size="126,44"
                font="Regular;34" halign="right" foregroundColor="#f4f8fb"
                backgroundColor="#061a2a" transparent="1" />
        <widget zPosition="20" name="date" position="1663,57" size="218,32"
                font="Regular;18" halign="right" foregroundColor="#d5e4f2"
                backgroundColor="#061a2a" transparent="1" />

        <!-- r25: one dynamic receiver identity in the header; hero artwork stays vendor-neutral -->
        <widget zPosition="35" name="boxHeader" position="1140,13" size="505,42"
                font="Regular;22" halign="center" valign="center" foregroundColor="#f4f8fb"
                backgroundColor="#061a2a" transparent="1" />

        <!-- current image -->
        <widget zPosition="20" name="currentInfo" position="161,188" size="597,39"
                font="Regular;27" foregroundColor="#f4f8fb"
                backgroundColor="#082640" transparent="1" />
        <widget zPosition="20" name="currentOK" position="942,188" size="83,39"
                font="Regular;25" halign="right" foregroundColor="#01f76f"
                backgroundColor="#082640" transparent="1" />

        <!-- safety statuses -->
        <widget zPosition="20" name="kexecOK" position="942,247" size="83,37"
                font="Regular;24" halign="right" foregroundColor="#01f76f"
                backgroundColor="#082136" transparent="1" />
        <widget zPosition="20" name="holdsOK" position="942,302" size="83,37"
                font="Regular;24" halign="right" foregroundColor="#01f76f"
                backgroundColor="#082136" transparent="1" />
        <widget zPosition="20" name="hddOK" position="942,356" size="83,37"
                font="Regular;24" halign="right" foregroundColor="#01f76f"
                backgroundColor="#082136" transparent="1" />

        <!-- backup -->
        <widget zPosition="20" name="targetSlot" position="210,518" size="330,36"
                font="Regular;25" foregroundColor="#f4f8fb"
                backgroundColor="#092b45" transparent="1" />
        <!-- r16: clear separation between backup button and progress area -->
        <widget zPosition="25" name="progressTitle" position="125,646" size="590,23"
                font="Regular;18" foregroundColor="#d8edf8"
                backgroundColor="#082136" transparent="1" />
        <widget zPosition="25" name="backupProgress" position="125,672" size="590,28"
                backgroundColor="#25465c" foregroundColor="#00dfff"
                borderWidth="1" borderColor="#71cdea" />
        <!-- percentage is centered directly on top of the progress bar -->
        <widget zPosition="30" name="progressPercent" position="125,670" size="590,31"
                font="Regular;20" halign="center" valign="center" foregroundColor="#f4f8fb"
                backgroundColor="#082136" transparent="1" />
        <widget zPosition="25" name="backupStatus" position="125,704" size="590,20"
                font="Regular;15" foregroundColor="#ffd400"
                backgroundColor="#082136" transparent="1" />

        <!-- r19: the baked-in static update artwork was removed from background.png.
             This is now the ONE dynamic button, so enabled/disabled states can never overlap. -->
        <widget zPosition="30" name="updateButton" position="937,512" size="610,58"
                font="Regular;29" halign="center" valign="center"
                foregroundColor="#f4f8fb" backgroundColor="#29465a"
                borderWidth="2" borderColor="#71cdea" />
        <widget zPosition="30" name="updateHint" position="950,576" size="585,28"
                font="Regular;17" halign="center" valign="center" foregroundColor="#b8d6e8"
                backgroundColor="#082136" transparent="1" />

        <!-- holdLine intentionally not rendered: approved checkbox/text stays untouched -->

        <!-- live output -->
        <widget zPosition="20" name="log" position="69,790" size="1068,166"
                font="Console;21" foregroundColor="#f4f8fb"
                backgroundColor="#000609" transparent="1" />

        <!-- rollback -->
        <widget zPosition="20" name="rollback" position="1360,793" size="258,110"
                font="Regular;21" foregroundColor="#f4f8fb"
                backgroundColor="#082136" transparent="1" />
        <!-- keyboard / remote focus cursor -->
        <widget zPosition="50" name="navCursor" position="184,516" size="22,40"
                font="Regular;28" foregroundColor="#00ecff" transparent="1" />

    </screen>
    '''.replace("__BACKGROUND_PATH__", _BACKGROUND_PATH)

    def __init__(self, session):
        Screen.__init__(self, session)
        self.session = session
        self.log_lines = []
        self.slots = []
        self.slot_index = 0
        self.busy = False
        self.backup_verified = False
        self.verified_backup_slot = None
        self.container = None
        self.pending_backup = None
        self.pending_delete = None
        self.backup_total_bytes = 0
        self.backup_dst = ""
        self.progress_value = 0

        for name in ("clock", "date", "boxHeader", "currentInfo", "currentOK", "kexecOK", "holdsOK", "hddOK", "targetSlot", "progressTitle", "progressPercent", "backupStatus", "updateButton", "updateHint", "holdLine", "log", "rollback", "navCursor"):
            self[name] = Label("")
        self["backupProgress"] = ProgressBar()
        self["backupProgress"].setRange((0, 100))
        self["backupProgress"].setValue(0)

        self["currentOK"].setText("●  OK")
        self["progressTitle"].setText("Backup-Fortschritt")
        self["progressPercent"].setText("0 %")
        self["backupStatus"].setText("Status: Noch kein Backup für dieses Update.")
        self["holdLine"].setText("Kernel-Pakete auf HOLD lassen")
        self["rollback"].setText("Noch kein Backup vorhanden.")
        self["navCursor"].setText(">")
        self.nav_focus = 5  # 0=currentInfo, 1=kexec, 2=holds, 3=hdd, 4=targetSlot, 5=backup, 6=update
        self.last_action_focus = 5

        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions", "NumberActions"],
            {
                "cancel": self.close,
                "red": self.close,
                "yellow": self.start_backup,
                "green": self.start_update,
                "blue": self.show_details,
                "0": self.request_delete_backup,
                "left": self.nav_left,
                "right": self.nav_right,
                "up": self.nav_up,
                "down": self.nav_down,
                "ok": self.nav_ok,
            },
            -1,
        )

        self.timer = eTimer()
        try:
            self.timer.callback.append(self.update_clock)
        except Exception:
            try:
                self.timer.timeout.connect(self.update_clock)
            except Exception:
                pass

        self.progress_timer = eTimer()
        try:
            self.progress_timer.callback.append(self.update_backup_progress)
        except Exception:
            try:
                self.progress_timer.timeout.connect(self.update_backup_progress)
            except Exception:
                pass

        self.onLayoutFinish.append(self.startup)

    def startup(self):
        self.update_clock()
        self.update_box_identity()
        try:
            self.timer.start(30000, False)
        except Exception:
            pass
        self.append_log("> Prüfe Multiboot-Schutz...")
        self.refresh_status()
        self.refresh_slots()
        self.load_rollback()
        self.paint_update_state()
        self.paint_nav_focus()

    def update_box_identity(self):
        brand, model = detect_box_identity()
        display = (brand + (" " + model if model else "")).strip()
        if _USE_CLASSIC_VU_DUO4KSE:
            # The classic VU+ Duo 4K SE header is already part of the approved artwork.
            self["boxHeader"].setText("")
        else:
            self["boxHeader"].setText("%s  •  Multiboot Schutz" % display)
        self.append_log("> Receiver erkannt: %s" % display)

    def update_clock(self):
        now = datetime.now()
        self["clock"].setText(now.strftime("%H:%M"))
        weekdays = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
        months = ("Jan.", "Feb.", "Mär.", "Apr.", "Mai", "Jun.", "Jul.", "Aug.", "Sep.", "Okt.", "Nov.", "Dez.")
        self["date"].setText("%s, %d. %s %d" % (
            weekdays[now.weekday()],
            now.day,
            months[now.month - 1],
            now.year
        ))

    def set_status(self, name, ok):
        self[name].setText("●  OK" if ok else "●  FEHLER")
        try:
            self[name].instance.setForegroundColor(parseColor("#01f76f" if ok else "#ff4141"))
        except Exception:
            pass

    def refresh_status(self):
        info = image_info()
        slot = current_slot()
        version = info.get("version", "?")
        build = info.get("build", info.get("imagebuild", "?"))
        self["currentInfo"].setText("Slot %s    OpenATV %s    Build %s" % (slot if slot is not None else "?", version, build))
        self.set_status("kexecOK", kexec_ok())
        self.set_status("holdsOK", holds_ok())
        self.set_status("hddOK", hdd_ok())
        self.append_log("> KEXEC-Kernel: %s" % ("OK" if kexec_ok() else "FEHLER"))
        self.append_log("> Kernel-HOLDs: %s" % ("OK" if holds_ok() else "FEHLER"))
        self.append_log("> HDD /media/usb: %s" % ("OK" if hdd_ok() else "FEHLER"))

    def refresh_slots(self):
        previous = None
        if self.slots and 0 <= self.slot_index < len(self.slots):
            previous = self.slots[self.slot_index]

        self.slots = free_slots()

        if previous in self.slots:
            self.slot_index = self.slots.index(previous)
        else:
            self.slot_index = 0

        if self.slots:
            self["targetSlot"].setText("Slot %d – FREI" % self.slots[self.slot_index])
            self.append_log("> Verifizierte freie Slots: %s" % ", ".join(str(x) for x in self.slots))
        else:
            self["targetSlot"].setText("Kein verifizierter freier Slot")
            self.append_log("> Backup gesperrt: kein eindeutig verifizierter freier Slot.")

    def paint_nav_focus(self):
        """Move a minimal cursor without changing the approved layout."""
        try:
            positions = {
                0: (43, 188),    # current image first row
                1: (43, 247),    # KEXEC-Kernel
                2: (43, 302),    # Kernel-HOLDs
                3: (43, 356),    # HDD /media/usb
                4: (184, 516),   # target slot
                5: (43, 590),    # backup button
                6: (900, 520),   # update button
            }
            x, y = positions.get(self.nav_focus, positions[5])
            self["navCursor"].instance.move(ePoint(x, y))
            self["navCursor"].show()
        except Exception:
            pass

    def nav_left(self):
        if self.busy:
            return
        if self.nav_focus == 4:
            self.prev_slot()
        elif self.nav_focus == 6:
            self.nav_focus = 5
            self.last_action_focus = 5
            self.paint_nav_focus()

    def nav_right(self):
        if self.busy:
            return
        if self.nav_focus == 4:
            self.next_slot()
        elif self.nav_focus == 5:
            self.nav_focus = 6
            self.last_action_focus = 6
            self.paint_nav_focus()

    def nav_up(self):
        if self.busy:
            return
        mapping = {
            0: 0,
            1: 0,
            2: 1,
            3: 2,
            4: 3,
            5: 4,
            6: 4,
        }
        self.nav_focus = mapping.get(self.nav_focus, 5)
        self.paint_nav_focus()

    def nav_down(self):
        if self.busy:
            return
        mapping = {
            0: 1,
            1: 2,
            2: 3,
            3: 4,
            4: self.last_action_focus if self.last_action_focus in (5, 6) else 5,
            5: 5,
            6: 6,
        }
        self.nav_focus = mapping.get(self.nav_focus, 5)
        self.paint_nav_focus()

    def nav_ok(self):
        if self.busy:
            return
        if self.nav_focus == 6:
            self.start_update()
        elif self.nav_focus in (0, 1, 2, 3):
            self.show_details()
        else:
            self.start_backup()

    def prev_slot(self):
        if self.busy or not self.slots:
            return
        self.slot_index = (self.slot_index - 1) % len(self.slots)
        self["targetSlot"].setText("Slot %d – FREI" % self.slots[self.slot_index])

    def next_slot(self):
        if self.busy or not self.slots:
            return
        self.slot_index = (self.slot_index + 1) % len(self.slots)
        self["targetSlot"].setText("Slot %d – FREI" % self.slots[self.slot_index])

    def set_backup_progress(self, value, title=None, status=None):
        try:
            value = max(0, min(100, int(value)))
        except Exception:
            value = 0
        self.progress_value = value
        try:
            self["backupProgress"].setValue(value)
            self["progressPercent"].setText("%d %%" % value)
            if title is not None:
                self["progressTitle"].setText(str(title))
            if status is not None:
                self["backupStatus"].setText(str(status))
        except Exception:
            pass

    def update_backup_progress(self):
        if not self.busy or not self.backup_dst or self.backup_total_bytes <= 0:
            return
        try:
            if not os.path.isdir(self.backup_dst):
                return
            copied = tree_size_bytes(self.backup_dst)
            if copied <= 0:
                return
            ratio = min(1.0, float(copied) / float(self.backup_total_bytes))
            value = 10 + int(ratio * 82)
            if value > self.progress_value and value <= 92:
                self.set_backup_progress(value, "Backup-Fortschritt – Kopieren", "Status: Kopiere aktuelles Image ...")
        except Exception:
            pass

    def append_log(self, text):
        for line in str(text).replace("\r", "").split("\n"):
            if line:
                self.log_lines.append(line)
        self.log_lines = self.log_lines[-7:]
        self["log"].setText("\n".join(self.log_lines))
        try:
            with open(LOG_FILE, "a") as f:
                f.write(str(text) + "\n")
        except Exception:
            pass

    def load_rollback(self):
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
                    valid = (
                        os.path.isdir(dst) and
                        os.path.isfile(os.path.join(dst, "zImage")) and
                        os.path.isfile(os.path.join(dst, "etc", "image-version")) and
                        os.path.exists(os.path.join(dst, "sbin", "init")) and
                        os.path.isfile(os.path.join(dst, "usr", "bin", "enigma2"))
                    )
            except Exception:
                valid = False

        if valid:
            self.backup_verified = True
            self.verified_backup_slot = target
            self["targetSlot"].setText("Slot %s – VERIFIZIERT ✓" % target)
            self.set_backup_progress(100, "Backup-Fortschritt – Fertig", "Status: Backup in Slot %s verifiziert." % target)
            created = (st.get("created") or "?").split(" ")[0]
            self["rollback"].setText("Backup-Slot:  %s\nQuelle:       Slot %s\nErstellt:     %s\n0 = BACKUP LÖSCHEN" % (target, source, created))
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

    def paint_update_state(self):
        """Use the baked enabled button artwork; dynamic widget is only the disabled overlay."""
        try:
            self["updateHint"].show()
            if self.backup_verified:
                # The enabled button is part of background.png so it is pixel-identical
                # in style to BACKUP JETZT ANLEGEN. Hide the grey dynamic overlay.
                self["updateButton"].hide()
                self["updateHint"].setText("Backup verifiziert – Update freigegeben")
                try:
                    self["updateHint"].instance.setForegroundColor(parseColor("#55e8ff"))
                except Exception:
                    pass
            else:
                self["updateButton"].setText("OPENATV UPDATE STARTEN")
                self["updateButton"].show()
                self["updateHint"].setText("Wird nach erfolgreichem Backup freigeschaltet.")
                try:
                    self["updateButton"].instance.setBackgroundColor(parseColor("#29465a"))
                    self["updateButton"].instance.setForegroundColor(parseColor("#a9bdca"))
                    self["updateHint"].instance.setForegroundColor(parseColor("#b8d6e8"))
                except Exception:
                    pass
        except Exception:
            pass

    def connect_container(self, data_cb, close_cb):
        self.container = eConsoleAppContainer()
        try:
            self.container.dataAvail.append(data_cb)
            self.container.appClosed.append(close_cb)
        except Exception:
            self.container.dataAvail.connect(data_cb)
            self.container.appClosed.connect(close_cb)

    def start_backup(self):
        if self.busy:
            return
        # A verified backup stays visible after success. When the user explicitly
        # starts another backup, switch the field back to the selected free target.
        if self.backup_verified and self.slots:
            self["targetSlot"].setText("Slot %d – FREI" % self.slots[self.slot_index])

        if not self.slots:
            self.session.open(
                MessageBox,
                "Kein eindeutig verifizierter freier Multiboot-Slot verfügbar.",
                MessageBox.TYPE_ERROR
            )
            return

        # Selected target from the last verified scan.
        if self.slot_index < 0 or self.slot_index >= len(self.slots):
            self.refresh_slots()
            return

        target = self.slots[self.slot_index]
        source = current_slot()

        # SECURITY CHECK #1:
        # Re-scan immediately before doing anything writable. Never trust the
        # slot list from screen startup because another tool may have changed it.
        latest_free = free_slots()
        if target not in latest_free:
            self.append_log("> ABBRUCH: Zielslot %d ist nicht mehr verifiziert frei." % target)
            self.refresh_slots()
            self.session.open(
                MessageBox,
                "Zielslot %d ist nicht mehr eindeutig frei.\\n\\n"
                "Es wurde nichts verändert." % target,
                MessageBox.TYPE_ERROR
            )
            return

        if source is None:
            self.append_log("> ABBRUCH: Aktiver Quellslot nicht eindeutig erkannt.")
            self.session.open(
                MessageBox,
                "Aktiver Quellslot konnte nicht eindeutig erkannt werden.\\n"
                "Es wurde nichts verändert.",
                MessageBox.TYPE_ERROR
            )
            return

        target_info = compatible_startup_slots().get(target)
        if not target_info:
            self.append_log("> ABBRUCH: STARTUP_%d ist nicht kompatibel." % target)
            self.refresh_slots()
            self.session.open(
                MessageBox,
                "STARTUP_%d ist nicht sicher für dieses Backup nutzbar.\\n"
                "Es wurde nichts verändert." % target,
                MessageBox.TYPE_ERROR
            )
            return

        # Switch/create the full view as writable only now, immediately before
        # the confirmed backup flow.
        mp = ensure_full_mount(True)
        if not mp:
            self.append_log("> ABBRUCH: Vollständiger Multiboot-Mount nicht schreibbar.")
            self.session.open(
                MessageBox,
                "Multiboot-Datenträger konnte nicht sicher schreibbar geöffnet werden.\\n"
                "Es wurde nichts verändert.",
                MessageBox.TYPE_ERROR
            )
            return

        src = active_source_path(mp)
        dst = os.path.join(mp, target_info["rootsubdir"])

        # SECURITY CHECK #2:
        # Re-check source and target on the actual writable full mount.
        if not src or not os.path.isdir(src):
            self.append_log("> ABBRUCH: Quellpfad fehlt: %s" % (src or "?"))
            self.session.open(
                MessageBox,
                "Quellslot konnte im vollständigen Multiboot-Dateisystem nicht verifiziert werden.\\n"
                "Es wurde nichts verändert.",
                MessageBox.TYPE_ERROR
            )
            return

        if not os.path.isfile(os.path.join(src, "zImage")) or not os.path.isfile(os.path.join(src, "etc", "image-version")):
            self.append_log("> ABBRUCH: Quellslot %d ist unvollständig." % source)
            self.session.open(
                MessageBox,
                "Quellslot %d ist nicht vollständig verifizierbar.\\n"
                "Es wurde nichts verändert." % source,
                MessageBox.TYPE_ERROR
            )
            return

        if os.path.lexists(dst) and not is_strictly_empty_dir(dst):
            self.append_log("> ABBRUCH: Zielpfad existiert bereits: %s" % dst)
            self.refresh_slots()
            self.session.open(
                MessageBox,
                "Zielslot %d ist nicht mehr frei.\n\n"
                "Es wurde nichts überschrieben." % target,
                MessageBox.TYPE_ERROR
            )
            return
        if is_strictly_empty_dir(dst):
            self.append_log("> Leerer OpenATV-Rest in Slot %d erkannt (wird erst nach Bestätigung entfernt)." % target)

        # STARTUP_N itself must still exist and remain valid. It is never
        # overwritten by SafeUpdate2026; it defines which slots the box offers.
        live_target_info = parse_startup_text(
            target,
            read_text(target_info["path"]),
            target_info["path"]
        )
        if not live_target_info or not same_device(live_target_info["root_device"], root_device()):
            self.append_log("> ABBRUCH: STARTUP_%d änderte sich während der Prüfung." % target)
            self.refresh_slots()
            self.session.open(
                MessageBox,
                "Die Bootdefinition von Slot %d ist nicht mehr eindeutig.\\n"
                "Es wurde nichts verändert." % target,
                MessageBox.TYPE_ERROR
            )
            return

        # Space check before the confirmation dialog.
        source_bytes = tree_size_bytes(src)
        free_bytes = filesystem_free_bytes(mp)
        reserve = 64 * 1024 * 1024
        if source_bytes <= 0 or free_bytes <= 0:
            self.append_log("> ABBRUCH: Speicherbedarf konnte nicht sicher geprüft werden.")
            self.session.open(
                MessageBox,
                "Freier Speicher bzw. Backup-Größe konnte nicht sicher ermittelt werden.\\n"
                "Backup bleibt gesperrt.",
                MessageBox.TYPE_ERROR
            )
            return

        if free_bytes < source_bytes + reserve:
            self.append_log("> ABBRUCH: Nicht genug freier Speicher für Slot %d." % target)
            self.session.open(
                MessageBox,
                "Nicht genug freier Speicher für ein vollständiges Backup.\\n\\n"
                "Benötigt: ca. %d MB + 64 MB Reserve\\n"
                "Frei: ca. %d MB" % (
                    source_bytes // (1024 * 1024),
                    free_bytes // (1024 * 1024)
                ),
                MessageBox.TYPE_ERROR
            )
            return

        self.append_log("> Quelle verifiziert: Slot %d" % source)
        self.append_log("> Ziel verifiziert frei: Slot %d" % target)
        self.append_log("> STARTUP_%d: OK (wird nicht verändert)" % target)

        self.session.openWithCallback(
            lambda yes: self.do_backup(yes, source, target, src, dst, source_bytes),
            MessageBox,
            "Backup von Slot %d nach Slot %d anlegen?\\n\\n"
            "Der Zielslot wurde unmittelbar vorher zweimal geprüft.\\n"
            "Bestehende Slots werden niemals überschrieben." % (source, target),
            MessageBox.TYPE_YESNO,
        )

    def do_backup(self, yes, source, target, src, dst, source_bytes):
        if not yes:
            return

        # Final race check after the user's confirmation.
        if os.path.lexists(dst):
            if is_strictly_empty_dir(dst):
                try:
                    os.rmdir(dst)
                    self.append_log("> Leeren Slot-Rest %d sicher entfernt." % target)
                except Exception:
                    self.append_log("> ABBRUCH: Leerer Zielrest konnte nicht entfernt werden.")
                    return
            else:
                self.append_log("> ABBRUCH: Zielslot %d wurde zwischenzeitlich belegt." % target)
                self.refresh_slots()
                self.session.open(
                    MessageBox,
                    "Zielslot %d ist inzwischen nicht mehr frei.\n"
                    "Es wurde nichts überschrieben." % target,
                    MessageBox.TYPE_ERROR
                )
                return

        self.busy = True
        self.backup_verified = False
        self.paint_update_state()
        self.backup_total_bytes = int(source_bytes or 0)
        self.backup_dst = dst
        self.set_backup_progress(3, "Backup-Fortschritt – Prüfen", "Status: Backup wird vorbereitet ...")
        try:
            self.progress_timer.start(1500, False)
        except Exception:
            pass
        self.append_log("> Backup Slot %d -> Slot %d startet..." % (source, target))

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
""".format(src=shq(src), dst=shq(dst))

        self.pending_backup = (source, target, dst)
        self.connect_container(self.backup_data, self.backup_closed)
        self.container.execute("/bin/sh -c %s" % shq(script))

    def backup_data(self, data):
        try:
            txt = data.decode("utf-8", "replace")
        except Exception:
            txt = str(data)
        for line in txt.splitlines():
            self.append_log("> " + line)
            low = line.lower()
            if "zielslot ist weiterhin frei" in low:
                self.set_backup_progress(max(self.progress_value, 6), "Backup-Fortschritt – Prüfen", "Status: Zielslot geprüft ...")
            elif "synchronisiere dateisystem" in low:
                self.set_backup_progress(max(self.progress_value, 8), "Backup-Fortschritt – Vorbereiten", "Status: Dateisystem wird synchronisiert ...")
            elif "kopiere image" in low:
                self.set_backup_progress(max(self.progress_value, 10), "Backup-Fortschritt – Kopieren", "Status: Kopiere aktuelles Image ...")
            elif "quelle zimage" in low or "backup zimage" in low:
                self.set_backup_progress(max(self.progress_value, 95), "Backup-Fortschritt – Verifizieren", "Status: Prüfe Kernel und Integrität ...")
            elif "backup_verified" in low:
                self.set_backup_progress(99, "Backup-Fortschritt – Verifizieren", "Status: Abschlussprüfung ...")

    def backup_closed(self, rc):
        try:
            self.progress_timer.stop()
        except Exception:
            pass
        self.busy = False
        source, target, dst = self.pending_backup
        verified = rc == 0 and os.path.isfile(os.path.join(dst, "zImage")) and os.path.isfile(os.path.join(dst, "etc", "image-version"))
        if verified:
            self.backup_verified = True
            self.verified_backup_slot = target
            created = datetime.now().strftime("%d.%m.%Y %H:%M")
            save_state({"source_slot": source, "target_slot": target, "created": created, "verified": True, "build": image_info().get("build", "")})
            self.set_backup_progress(100, "Backup-Fortschritt – Fertig", "Status: Backup in Slot %d erfolgreich verifiziert." % target)
            self["rollback"].setText("Backup-Slot:  %d\nQuelle:       Slot %d\nErstellt:     %s\n0 = BACKUP LÖSCHEN" % (target, source, created.split(" ")[0]))
            self.append_log("> Backup verifiziert. Update freigegeben.")
            self.refresh_slots()
            self["targetSlot"].setText("Slot %d – VERIFIZIERT ✓" % target)
            self.nav_focus = 6
            self.last_action_focus = 6
            self.paint_nav_focus()
        else:
            self.set_backup_progress(self.progress_value, "Backup-Fortschritt – FEHLER", "Status: Backup FEHLGESCHLAGEN – Zielslot nicht verwenden.")
            self.append_log("> FEHLER: Backup nicht verifiziert.")
            self.session.open(MessageBox, "Backup konnte nicht verifiziert werden.\nDer Zielslot wurde NICHT automatisch gelöscht.", MessageBox.TYPE_ERROR)
        self.paint_update_state()
        self.backup_dst = ""
        self.backup_total_bytes = 0

    def request_delete_backup(self):
        """Safely remove only the verified SafeUpdate backup tree; keep STARTUP_N intact."""
        if self.busy:
            return
        if not self.backup_verified or self.verified_backup_slot is None:
            self.session.open(
                MessageBox,
                "Kein verifiziertes SafeUpdate-Backup zum Löschen vorhanden.",
                MessageBox.TYPE_INFO,
            )
            return

        st = load_state()
        try:
            target = int(self.verified_backup_slot)
        except Exception:
            target = -1
        source = current_slot()

        # Fail closed: only the exact backup recorded and physically revalidated by SafeUpdate may be deleted.
        if (
            target < 0 or
            target == source or
            not st.get("verified") or
            int(st.get("target_slot", -1)) != target or
            int(st.get("source_slot", -1)) != source
        ):
            self.append_log("> KILLSWITCH blockiert: Backup-Zuordnung nicht eindeutig.")
            self.session.open(
                MessageBox,
                "Löschen blockiert. Das gespeicherte Backup ist nicht eindeutig dem laufenden Slot zugeordnet.",
                MessageBox.TYPE_ERROR,
            )
            return

        info = compatible_startup_slots().get(target)
        mp = ensure_full_mount(True)
        if not info or not mp:
            self.append_log("> KILLSWITCH blockiert: Slot/Dateisystem nicht sicher verifizierbar.")
            self.session.open(
                MessageBox,
                "Löschen blockiert. Zielslot oder Dateisystem konnte nicht sicher verifiziert werden.",
                MessageBox.TYPE_ERROR,
            )
            return

        dst = os.path.join(mp, info["rootsubdir"])
        mp_real = os.path.realpath(mp)
        dst_real = os.path.realpath(dst)
        expected_suffix = "linuxrootfs%d" % target
        safe_path = (
            dst_real.startswith(mp_real.rstrip("/") + "/") and
            os.path.basename(dst_real) == expected_suffix and
            not os.path.islink(dst) and
            os.path.isdir(dst) and
            os.path.isfile(os.path.join(dst, "zImage")) and
            os.path.isfile(os.path.join(dst, "etc", "image-version")) and
            os.path.exists(os.path.join(dst, "sbin", "init")) and
            os.path.isfile(os.path.join(dst, "usr", "bin", "enigma2"))
        )
        if not safe_path:
            self.append_log("> KILLSWITCH blockiert: Slot %d besteht Sicherheitsprüfung nicht." % target)
            self.session.open(
                MessageBox,
                "Löschen blockiert. Slot %d besteht die Sicherheitsprüfung nicht." % target,
                MessageBox.TYPE_ERROR,
            )
            return

        self.session.openWithCallback(
            lambda yes: self.do_delete_backup(yes, target, dst),
            MessageBox,
            "KILLSWITCH: Backup in Slot %d wirklich löschen?\n\n"
            "Gelöscht wird NUR das von SafeUpdate verifizierte linuxrootfs%d-Verzeichnis.\n"
            "STARTUP_%d bleibt erhalten, damit der Slot danach wieder sauber FREI ist.\n\n"
            "Das OpenATV-Update wird anschließend wieder gesperrt." % (target, target, target),
            MessageBox.TYPE_YESNO,
        )

    def do_delete_backup(self, yes, target, dst):
        if not yes:
            return
        if self.busy:
            return

        # Final race check immediately after confirmation.
        info = compatible_startup_slots().get(int(target))
        mp = ensure_full_mount(True)
        if not info or not mp:
            self.session.open(MessageBox, "Löschen abgebrochen: Slot konnte nicht erneut geprüft werden.", MessageBox.TYPE_ERROR)
            return
        current_dst = os.path.join(mp, info["rootsubdir"])
        if os.path.realpath(current_dst) != os.path.realpath(dst) or int(target) == current_slot():
            self.session.open(MessageBox, "Löschen abgebrochen: Slot-Zuordnung hat sich geändert.", MessageBox.TYPE_ERROR)
            return

        self.busy = True
        self.backup_verified = False
        self.paint_update_state()
        self.pending_delete = (int(target), current_dst)
        self.set_backup_progress(0, "Backup-Fortschritt – Löschen", "Status: Lösche Sicherheitsbackup aus Slot %d ..." % target)
        self.append_log("> KILLSWITCH: Lösche verifiziertes Backup aus Slot %d ..." % target)

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
""".format(dst=shq(current_dst))

        self.connect_container(self.delete_backup_data, self.delete_backup_closed)
        self.container.execute("/bin/sh -c %s" % shq(script))

    def delete_backup_data(self, data):
        try:
            txt = data.decode("utf-8", "replace")
        except Exception:
            txt = str(data)
        for line in txt.splitlines():
            self.append_log("> " + line)

    def delete_backup_closed(self, rc):
        self.busy = False
        pending = self.pending_delete
        self.pending_delete = None
        if not pending:
            return
        target, dst = pending

        deleted = (rc == 0 and not os.path.lexists(dst))
        if deleted:
            try:
                if os.path.exists(STATE_FILE):
                    os.unlink(STATE_FILE)
            except Exception:
                # If state cleanup fails, overwrite it fail-closed so a stale verified state can never unlock updates.
                save_state({
                    "source_slot": current_slot(),
                    "target_slot": target,
                    "verified": False,
                    "deleted": datetime.now().strftime("%d.%m.%Y %H:%M"),
                })
            self.backup_verified = False
            self.verified_backup_slot = None
            self.set_backup_progress(0, "Backup-Fortschritt", "Status: Backup aus Slot %d gelöscht – Update gesperrt." % target)
            self["rollback"].setText("Noch kein Backup vorhanden.")
            self.append_log("> KILLSWITCH: Slot %d sauber gelöscht. STARTUP_%d blieb erhalten." % (target, target))
            self.refresh_slots()
            if target in self.slots:
                self.slot_index = self.slots.index(target)
                self["targetSlot"].setText("Slot %d – FREI" % target)
            self.paint_update_state()
            self.session.open(
                MessageBox,
                "Backup in Slot %d wurde sauber gelöscht.\n\nSTARTUP_%d blieb erhalten. Der Slot ist wieder frei und das Update ist gesperrt." % (target, target),
                MessageBox.TYPE_INFO,
            )
            return

        # A failed rm can leave a partial image. Never call that slot free automatically.
        self.append_log("> KILLSWITCH FEHLER: Slot %d wurde nicht vollständig gelöscht." % target)
        st = load_state()
        st["verified"] = False
        st["invalidated"] = datetime.now().strftime("%d.%m.%Y %H:%M")
        save_state(st)
        self.backup_verified = False
        self.verified_backup_slot = None
        self.set_backup_progress(0, "Backup-Fortschritt – FEHLER", "Status: Löschen unvollständig – Slot %d NICHT verwenden." % target)
        self["rollback"].setText("Backup-Löschung unvollständig.\nSlot %d NICHT verwenden." % target)
        self.paint_update_state()
        self.session.open(
            MessageBox,
            "Backup konnte nicht vollständig gelöscht werden.\n\nSlot %d wird NICHT als frei behandelt. Bitte Details prüfen." % target,
            MessageBox.TYPE_ERROR,
        )

    def start_update(self):
        if self.busy:
            return
        if not self.backup_verified:
            self.session.open(MessageBox, "Update bleibt gesperrt, bis ein Backup erfolgreich verifiziert wurde.", MessageBox.TYPE_INFO)
            return
        if not kexec_ok():
            self.session.open(MessageBox, "KEXEC-Kernel ist nicht korrekt. Update wird blockiert.", MessageBox.TYPE_ERROR)
            return
        if not holds_ok():
            self.session.open(MessageBox, "Nicht alle Kernel-Pakete stehen auf HOLD. Update wird blockiert.", MessageBox.TYPE_ERROR)
            return
        self.session.openWithCallback(self.do_update, MessageBox, "Backup ist verifiziert.\n\nOpenATV jetzt mit opkg update && opkg upgrade aktualisieren?", MessageBox.TYPE_YESNO)

    def do_update(self, yes):
        if not yes:
            return
        self.busy = True
        self.append_log("> opkg update")
        hold_cmd = "; ".join("opkg flag hold %s >/dev/null 2>&1 || true" % shq(p) for p in KERNEL_PACKAGES)
        cmd = "set -e; %s; opkg update; echo __SAFEUPDATE_UPGRADE__; opkg upgrade" % hold_cmd
        self.connect_container(self.update_data, self.update_closed)
        self.container.execute("/bin/sh -c %s" % shq(cmd))

    def update_data(self, data):
        try:
            txt = data.decode("utf-8", "replace")
        except Exception:
            txt = str(data)
        for line in txt.splitlines():
            if line == "__SAFEUPDATE_UPGRADE__":
                self.append_log("> opkg upgrade")
            else:
                self.append_log("> " + line[:120])

    def update_closed(self, rc):
        self.busy = False
        self.append_log("> Update-Prozess beendet. RC=%s" % rc)
        guard_ok = True
        if os.path.isfile("/usr/local/sbin/kexec-guard.sh"):
            guard_ok = subprocess.call(["/usr/local/sbin/kexec-guard.sh"]) == 0
        self.refresh_status()
        if rc == 0 and guard_ok and kexec_ok():
            self.append_log("> Sicherheitsprüfung: OK")
            self.session.open(MessageBox, "Update abgeschlossen.\nKEXEC-Schutz ist weiterhin OK.\n\nNeustart bitte anschließend manuell ausführen.", MessageBox.TYPE_INFO)
        else:
            self.append_log("> WARNUNG: Update/Sicherheitsprüfung nicht sauber beendet.")
            self.session.open(MessageBox, "Update oder Sicherheitsprüfung meldet einen Fehler.\nBitte NICHT neu starten, bevor die Details geprüft wurden.", MessageBox.TYPE_ERROR)

    def show_details(self):
        info = image_info()
        st = load_state()
        text = (
            "%s %s\n\n"
            "Aktueller Slot: %s\n"
            "Image: %s\n"
            "Build: %s\n"
            "Root: %s\n\n"
            "KEXEC: %s\n"
            "Kernel-HOLDs: %s\n"
            "HDD /media/usb: %s\n"
            "Verifiziert freie Slots: %s\n\n"
            "Letztes Backup: %s"
        ) % (
            PLUGIN_NAME, PLUGIN_VERSION,
            current_slot() if current_slot() is not None else "?",
            info.get("version", "?"), info.get("build", "?"), root_device() or "?",
            "OK" if kexec_ok() else "FEHLER", "OK" if holds_ok() else "FEHLER", "OK" if hdd_ok() else "FEHLER",
            ", ".join(str(x) for x in self.slots) or "keine", st.get("created", "keins")
        )
        self.session.open(MessageBox, text, MessageBox.TYPE_INFO)


def main(session, **kwargs):
    session.open(SafeUpdateScreen)


def Plugins(**kwargs):
    return [
        PluginDescriptor(name=PLUGIN_NAME, description="Backup + sicheres OpenATV Update für KEXEC-Multiboot", where=PluginDescriptor.WHERE_PLUGINMENU, fnc=main),
        PluginDescriptor(name=PLUGIN_NAME, description="Backup + sicheres OpenATV Update für KEXEC-Multiboot", where=PluginDescriptor.WHERE_EXTENSIONSMENU, fnc=main),
    ]
