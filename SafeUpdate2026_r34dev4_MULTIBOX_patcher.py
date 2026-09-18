#!/usr/bin/env python3
# SafeUpdate2026 r34-dev4 MULTIBOX strategy patch
#
# Incremental patch for an installed r34-dev3 base.
# Keeps the tested VU+ Duo 4K SE early-boot strategy unchanged and adds
# a conservative HiSilicon multiboot strategy for:
#   - Octagon SF8008 / SF8008 4K Supreme
#   - GigaBlue UHD Trio 4K (gbtrio4k / boxtype gbmv200)
#
# HiSilicon safety model:
#   - eMMC slots 1..4 only
#   - /boot/STARTUP remains on the updated source during the first boot
#   - BootGuard watches Enigma2
#   - on crash-loop, /boot/STARTUP is atomically switched to the verified
#     backup slot and the box reboots
#   - NO claim of pre-init/early-boot recovery on HiSilicon because
#     STARTUP_ONCE has not been validated there
#
# Hostname and /proc/stb/info/model are deliberately NOT trusted for platform
# selection. Detection is based on /proc/cmdline OEM/MACHINEBUILD/MODEL,
# boxtype and the VU bolt/board value.
#
# Does not reboot. Does not arm a recovery plan by itself.

import os
import py_compile
import shutil
import subprocess
from datetime import datetime

PLUGIN = "/usr/lib/enigma2/python/Plugins/Extensions/SafeUpdate2026/plugin.py"
PLUGIN_DIR = os.path.dirname(PLUGIN)
BOOTGUARD = "/usr/bin/safeupdate-bootguard"
BOOTGUARD_PLUGIN = os.path.join(PLUGIN_DIR, "safeupdate-bootguard")
RECOVER = "/usr/bin/safeupdate-recover"
RECOVER_PLUGIN = os.path.join(PLUGIN_DIR, "safeupdate-recover")

BACKUP_ROOT = "/root"
MARKER_PLUGIN = "r34-dev4 MULTIBOX STRATEGY"
MARKER_GUARD = "r34-dev4 multibox strategy"
MARKER_RECOVER = "r34-dev4 multibox strategy"

PLUGIN_HELPERS = r'''
# --- r34-dev4 MULTIBOX STRATEGY ---
# Platform detection intentionally ignores hostname and /proc/stb/info/model.
def safeupdate_dev4_platform():
    def _read(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read().replace("\x00", "").strip()
        except Exception:
            return ""

    cmd = _read("/proc/cmdline")
    vals = {}
    for token in cmd.split():
        if "=" in token:
            k, v = token.split("=", 1)
            vals[k.upper()] = v.strip("'\"").lower()

    machine = vals.get("MACHINEBUILD", "")
    oem = vals.get("OEM", "")
    model = vals.get("MODEL", "")
    boxtype = _read("/proc/stb/info/boxtype").lower()
    bolt_board = _read("/proc/device-tree/bolt/board").lower()

    if bolt_board == "duo4kse" or machine == "duo4kse" or model == "duo4kse":
        return "vu_duo4kse"

    if (oem == "octagon" and machine == "sf8008") or boxtype == "sf8008":
        return "hisilicon_sf8008"

    if (oem == "gigablue" and machine == "gbtrio4k") or (
        boxtype == "gbmv200" and machine == "gbtrio4k"
    ):
        return "hisilicon_gbtrio4k"

    return "unsupported"


def safeupdate_dev4_current_slot():
    try:
        with open("/proc/cmdline", "r", encoding="utf-8", errors="replace") as f:
            cmd = f.read()
    except Exception:
        return None

    for token in cmd.split():
        if token.startswith("rootsubdir="):
            value = token.split("=", 1)[1].strip("'\"")
            base = value.rstrip("/").split("/")[-1]
            if base.startswith("linuxrootfs"):
                try:
                    return int(base[len("linuxrootfs"):])
                except Exception:
                    return None
    return None


def safeupdate_dev4_hisi_startup(slot):
    # We only authorize the exact eMMC layout captured from SF8008 and
    # GigaBlue UHD Trio 4K. USB slots 5/6 are intentionally excluded.
    try:
        slot = int(slot)
    except Exception:
        return None
    if slot < 1 or slot > 4:
        return None

    path = "/boot/STARTUP_%d" % slot
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read().strip()
    except Exception:
        return None

    expected_boot = "boot emmcflash0.linuxkernel%d " % slot
    expected_root = "root=/dev/mmcblk0p16"
    expected_sub = "rootsubdir=linuxrootfs%d" % slot
    expected_kernel = "kernel=/dev/mmcblk0p%d" % (11 + slot)

    if not text.startswith(expected_boot):
        return None
    for required in (expected_root, expected_sub, expected_kernel):
        if required not in text:
            return None
    return path


def safeupdate_dev4_same_file(a, b):
    try:
        with open(a, "rb") as fa, open(b, "rb") as fb:
            return fa.read() == fb.read()
    except Exception:
        return False


def safeupdate_dev4_atomic_json(path, data):
    import json
    tmp = path + ".r34dev4-new"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    subprocess.call(["sync"])


def safeupdate_dev4_prepare_hisilicon_recovery(recovery_ok, recovery_text):
    # VU keeps the already-tested r34-dev3 early-boot path unchanged.
    platform = safeupdate_dev4_platform()
    if platform not in ("hisilicon_sf8008", "hisilicon_gbtrio4k"):
        return recovery_ok, recovery_text

    if not recovery_ok:
        return recovery_ok, recovery_text

    state_path = "/etc/enigma2/safeupdate2026.json"
    plan_path = "/boot/.safeupdate2026-recovery.json"

    try:
        import json
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception as e:
        return False, "HiSilicon-Recovery: Backup-Status nicht lesbar: %s" % e

    if not isinstance(state, dict) or not state.get("verified"):
        return False, "HiSilicon-Recovery benötigt ein verifiziertes Sicherheits-Backup."

    try:
        source = int(state.get("source_slot"))
        backup = int(state.get("target_slot"))
    except Exception:
        return False, "HiSilicon-Recovery: Slot-Zuordnung fehlt oder ist ungültig."

    if source == backup or source < 1 or source > 4 or backup < 1 or backup > 4:
        return False, "HiSilicon-Recovery ist nur für getrennte eMMC-Slots 1 bis 4 freigegeben."

    current = safeupdate_dev4_current_slot()
    if current != source:
        return False, "HiSilicon-Recovery: aktiver Slot %s passt nicht zur Quelle %s." % (current, source)

    source_startup = safeupdate_dev4_hisi_startup(source)
    backup_startup = safeupdate_dev4_hisi_startup(backup)
    if not source_startup or not backup_startup:
        return False, "HiSilicon-Recovery: STARTUP-Layout entspricht nicht dem freigegebenen eMMC-Schema."

    if not safeupdate_dev4_same_file("/boot/STARTUP", source_startup):
        return False, "HiSilicon-Recovery: /boot/STARTUP zeigt nicht eindeutig auf den Quellslot."

    if os.path.exists(plan_path):
        try:
            with open(plan_path, "r", encoding="utf-8") as f:
                old = json.load(f)
        except Exception:
            old = {}
        if isinstance(old, dict) and old.get("phase") in (
            "armed", "restoring", "fallback", "fallback_failed", "blocked_fs_error"
        ):
            return False, "HiSilicon-Recovery: Es existiert bereits ein aktiver Recovery-Vorgang."

    now = int(__import__("time").time())

    root_spec = ""
    try:
        with open("/proc/cmdline", "r", encoding="utf-8", errors="replace") as f:
            for token in f.read().split():
                if token.startswith("root="):
                    root_spec = token.split("=", 1)[1].strip("'\"")
                    break
    except Exception:
        pass

    plan = {
        "version": 2,
        "phase": "armed",
        "source_slot": source,
        "backup_slot": backup,
        "created": now,
        "updated": now,
        "platform": platform,
        "fallback_strategy": "persistent_startup",
        "bootloader_fallback_armed": False,
        "bootloader_default_slot": source,
        "bootloader_once_slot": None,
        "plugin_version": "2026.1-r34-dev4",
        "root_spec": root_spec,
        "kernel_sha256": str(state.get("kernel_sha256") or ""),
    }

    try:
        safeupdate_dev4_atomic_json(plan_path, plan)
    except Exception as e:
        return False, "HiSilicon-Recovery-Plan konnte nicht geschrieben werden: %s" % e

    return True, (
        "HiSilicon-Crash-Fallback ist scharf: Slot %d -> Sicherheits-Slot %d. "
        "Frühe Bootfehler vor BootGuard sind auf diesem Layout noch nicht automatisch abgesichert."
        % (source, backup)
    )
'''

GUARD_PLATFORM_HELPER = r'''
def safeupdate_platform():
    cmd = read_text("/proc/cmdline")
    vals = {}
    for token in cmd.split():
        if "=" in token:
            k, v = token.split("=", 1)
            vals[k.upper()] = v.strip("'\"").lower()

    machine = vals.get("MACHINEBUILD", "")
    oem = vals.get("OEM", "")
    model = vals.get("MODEL", "")
    boxtype = read_text("/proc/stb/info/boxtype").replace("\x00", "").strip().lower()
    bolt_board = board()

    if bolt_board == "duo4kse" or machine == "duo4kse" or model == "duo4kse":
        return "vu_duo4kse"
    if (oem == "octagon" and machine == "sf8008") or boxtype == "sf8008":
        return "hisilicon_sf8008"
    if (oem == "gigablue" and machine == "gbtrio4k") or (
        boxtype == "gbmv200" and machine == "gbtrio4k"
    ):
        return "hisilicon_gbtrio4k"
    return "unsupported"
'''

RECOVER_PLATFORM_HELPER = r'''
def safeupdate_platform():
    def _read(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read().replace("\x00", "").strip()
        except Exception:
            return ""

    cmd = _read("/proc/cmdline")
    vals = {}
    for token in cmd.split():
        if "=" in token:
            k, v = token.split("=", 1)
            vals[k.upper()] = v.strip("'\"").lower()

    machine = vals.get("MACHINEBUILD", "")
    oem = vals.get("OEM", "")
    model = vals.get("MODEL", "")
    boxtype = _read("/proc/stb/info/boxtype").lower()
    bolt_board = _read("/proc/device-tree/bolt/board").lower()

    if bolt_board == "duo4kse" or machine == "duo4kse" or model == "duo4kse":
        return "vu_duo4kse"
    if (oem == "octagon" and machine == "sf8008") or boxtype == "sf8008":
        return "hisilicon_sf8008"
    if (oem == "gigablue" and machine == "gbtrio4k") or (
        boxtype == "gbmv200" and machine == "gbtrio4k"
    ):
        return "hisilicon_gbtrio4k"
    return "unsupported"
'''


def die(msg):
    print("FEHLER: " + msg)
    raise SystemExit(1)


def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_atomic(path, text, mode=None):
    tmp = path + ".r34dev4-new"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    if mode is not None:
        os.chmod(tmp, mode)
    os.replace(tmp, path)


def backup(paths):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(BACKUP_ROOT, "SafeUpdate2026-r34dev4-backup-" + stamp)
    os.makedirs(dest, exist_ok=False)
    for p in paths:
        if os.path.exists(p):
            name = p.strip("/").replace("/", "__")
            shutil.copy2(p, os.path.join(dest, name))
    return dest


def compile_check(path):
    py_compile.compile(path, doraise=True)


def patch_plugin(text):
    changed = False

    if MARKER_PLUGIN not in text:
        anchor = "\ndef safeupdate_dev2_maybe_offer_recovery(session):\n"
        if text.count(anchor) != 1:
            die("plugin.py: dev2 Recovery-Anker nicht eindeutig gefunden.")
        text = text.replace(
            anchor,
            "\n# %s\n%s%s" % (MARKER_PLUGIN, PLUGIN_HELPERS, anchor),
            1,
        )
        changed = True

    call = "            recovery_ok, recovery_text = safeupdate_dev2_prepare_recovery_plan()\n"
    hook = (
        call
        + "            recovery_ok, recovery_text = "
          "safeupdate_dev4_prepare_hisilicon_recovery(recovery_ok, recovery_text)\n"
    )

    if hook not in text:
        if text.count(call) != 1:
            die("plugin.py: Recovery-Aufruf nicht eindeutig gefunden.")
        text = text.replace(call, hook, 1)
        changed = True

    return text, changed


def patch_bootguard(text):
    changed = False

    if MARKER_GUARD not in text:
        header_anchor = "# r34-dev3 early-boot fallback\n"
        if header_anchor not in text:
            die("safeupdate-bootguard: r34-dev3 Basis fehlt.")
        text = text.replace(
            header_anchor,
            header_anchor + "# %s\n" % MARKER_GUARD,
            1,
        )
        changed = True

    if "def safeupdate_platform():\n" not in text:
        anchor = "\ndef current_slot():\n"
        if text.count(anchor) != 1:
            die("safeupdate-bootguard: current_slot-Anker nicht eindeutig.")
        text = text.replace(
            anchor,
            "\n" + GUARD_PLATFORM_HELPER + anchor,
            1,
        )
        changed = True

    old_board_gate = '''    if board() != "duo4kse":
        log("Auto-Recovery nicht aktiv: Boxlayout nicht freigegeben.")
        return 0

    plan = load_plan()
'''
    new_board_gate = '''    platform = safeupdate_platform()
    if platform == "unsupported":
        log("Auto-Recovery nicht aktiv: Boxlayout nicht freigegeben.")
        return 0

    plan = load_plan()
    planned_platform = str(plan.get("platform") or "")
    if planned_platform and planned_platform != platform:
        log("Recovery-Plan ignoriert: Plattform %s passt nicht zu %s." % (planned_platform, platform))
        return 0
'''
    if new_board_gate in text:
        pass
    elif old_board_gate in text:
        text = text.replace(old_board_gate, new_board_gate, 1)
        changed = True
    else:
        die("safeupdate-bootguard: Plattform-Gate ist unbekannt.")

    old_fallback = '''    try:
        set_startup_once(backup)
    except Exception as e:
        plan["phase"] = "fallback_failed"
        plan["error"] = str(e)
        plan["updated"] = int(time.time())
        save_plan(plan)
        log("Fallback konnte nicht vorbereitet werden: %s" % e)
        return 4
'''
    new_fallback = '''    try:
        platform = safeupdate_platform()
        if platform in ("hisilicon_sf8008", "hisilicon_gbtrio4k"):
            # No validated STARTUP_ONCE semantics on these HiSilicon boxes.
            # Switch the persistent boot target only after BootGuard has
            # actually detected a crash-loop.
            set_startup_default(backup)
            plan["bootloader_default_slot"] = backup
            plan["bootloader_once_slot"] = None
            plan["bootloader_fallback_armed"] = True
            plan["fallback_strategy"] = "persistent_startup"
        else:
            # Tested VU+ Duo 4K SE path stays unchanged.
            set_startup_once(backup)
            plan["fallback_strategy"] = "startup_once"
    except Exception as e:
        plan["phase"] = "fallback_failed"
        plan["error"] = str(e)
        plan["updated"] = int(time.time())
        save_plan(plan)
        log("Fallback konnte nicht vorbereitet werden: %s" % e)
        return 4
'''
    if new_fallback in text:
        pass
    elif old_fallback in text:
        text = text.replace(old_fallback, new_fallback, 1)
        changed = True
    else:
        die("safeupdate-bootguard: Fallback-Block ist unbekannt.")

    old_log = '    log("Enigma2 nicht stabil. Einmaliger Start auf Sicherheits-Slot %d vorbereitet." % backup)\n'
    new_log = '''    if safeupdate_platform() in ("hisilicon_sf8008", "hisilicon_gbtrio4k"):
        log("Enigma2 nicht stabil. Dauerhafter STARTUP wurde auf Sicherheits-Slot %d gesetzt." % backup)
    else:
        log("Enigma2 nicht stabil. Einmaliger Start auf Sicherheits-Slot %d vorbereitet." % backup)
'''
    if new_log in text:
        pass
    elif old_log in text:
        text = text.replace(old_log, new_log, 1)
        changed = True
    else:
        die("safeupdate-bootguard: Fallback-Log ist unbekannt.")

    return text, changed


def patch_recover(text):
    changed = False

    if MARKER_RECOVER not in text:
        header = "# SafeUpdate2026 r34-dev2 recovery helper\n"
        if header not in text:
            die("safeupdate-recover: r34-dev2 Basis fehlt.")
        text = text.replace(header, header + "# %s\n" % MARKER_RECOVER, 1)
        changed = True

    if "def safeupdate_platform():\n" not in text:
        anchor = "\ndef set_startup_once(slot):\n"
        if text.count(anchor) != 1:
            die("safeupdate-recover: set_startup_once-Anker nicht eindeutig.")
        text = text.replace(
            anchor,
            "\n" + RECOVER_PLATFORM_HELPER + anchor,
            1,
        )
        changed = True

    old_dst = '    dst = "/boot/STARTUP_ONCE"\n'
    new_dst = '''    platform = safeupdate_platform()
    if platform in ("hisilicon_sf8008", "hisilicon_gbtrio4k"):
        # On validated HiSilicon eMMC multiboot we deliberately use the
        # persistent STARTUP file; STARTUP_ONCE semantics are unverified.
        dst = "/boot/STARTUP"
    else:
        dst = "/boot/STARTUP_ONCE"
'''
    if new_dst in text:
        pass
    elif old_dst in text:
        if text.count(old_dst) != 1:
            die("safeupdate-recover: STARTUP_ONCE-Ziel nicht eindeutig.")
        text = text.replace(old_dst, new_dst, 1)
        changed = True
    else:
        die("safeupdate-recover: Bootziel-Block ist unbekannt.")

    return text, changed


def main():
    if os.geteuid() != 0:
        die("Bitte als root auf der Box ausführen.")

    required = (PLUGIN, BOOTGUARD, RECOVER)
    for p in required:
        if not os.path.isfile(p):
            die("Datei fehlt: %s" % p)

    plugin_text = read(PLUGIN)
    guard_text = read(BOOTGUARD)
    recover_text = read(RECOVER)

    if "r34-dev3 early-boot fallback" not in guard_text:
        die("Abbruch: r34-dev3 BootGuard-Basis fehlt. dev4 wird nicht blind auf eine andere Basis gepatcht.")

    if "set_startup_default" not in guard_text:
        die("Abbruch: r34-dev3 set_startup_default() fehlt.")

    plugin_new, plugin_changed = patch_plugin(plugin_text)
    guard_new, guard_changed = patch_bootguard(guard_text)
    recover_new, recover_changed = patch_recover(recover_text)

    if not (plugin_changed or guard_changed or recover_changed):
        print("Bereits auf r34-dev4 MULTIBOX-Stand; keine Änderung nötig.")
        return 0

    targets = [
        PLUGIN,
        BOOTGUARD,
        BOOTGUARD_PLUGIN,
        RECOVER,
        RECOVER_PLUGIN,
    ]
    backup_dir = backup(targets)
    print("Backup: " + backup_dir)

    try:
        write_atomic(PLUGIN, plugin_new, 0o644)
        write_atomic(BOOTGUARD, guard_new, 0o755)
        write_atomic(BOOTGUARD_PLUGIN, guard_new, 0o755)
        write_atomic(RECOVER, recover_new, 0o755)
        write_atomic(RECOVER_PLUGIN, recover_new, 0o755)

        compile_check(PLUGIN)
        compile_check(BOOTGUARD)
        compile_check(RECOVER)

        subprocess.call(["sync"])
    except Exception as e:
        print("PATCH FEHLGESCHLAGEN: %s" % e)
        print("Originale liegen unter: %s" % backup_dir)
        raise

    print("")
    print("===================================================")
    print(" SafeUpdate2026 r34-dev4 MULTIBOX STRATEGY: OK")
    print("===================================================")
    print("VU+ Duo 4K SE:")
    print(" - bisheriger getesteter STARTUP/STARTUP_ONCE-Pfad bleibt erhalten")
    print("")
    print("Octagon SF8008 / GigaBlue UHD Trio 4K:")
    print(" - Plattform wird über OEM/MACHINEBUILD/boxtype erkannt")
    print(" - Hostname und dm8000-Modelwert werden NICHT zur Erkennung benutzt")
    print(" - nur eMMC-Slots 1..4 freigegeben")
    print(" - Crash-Loop -> /boot/STARTUP atomar auf Sicherheits-Slot")
    print(" - Recovery-Helfer nutzt auf HiSilicon persistenten STARTUP")
    print(" - KEIN unbewiesener STARTUP_ONCE-Early-Boot-Schutz auf HiSilicon")
    print("")
    print("WICHTIG: Der Patch startet NICHT neu und legt keinen Recovery-Plan an.")
    print("Vor einem Test erst Preflight/Plattformerkennung kontrollieren.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
