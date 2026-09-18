#!/usr/bin/env python3
# SafeUpdate2026 r34-dev2 -> r34-dev3 early-boot fallback patch
# Runs ON the Enigma2 box as root.
# Does not reboot and does not arm recovery immediately.

import os
import shutil
import py_compile
import subprocess
from datetime import datetime

PLUGIN = "/usr/lib/enigma2/python/Plugins/Extensions/SafeUpdate2026/plugin.py"
PLUGIN_DIR = os.path.dirname(PLUGIN)
BOOTGUARD = "/usr/bin/safeupdate-bootguard"
BOOTGUARD_PLUGIN = os.path.join(PLUGIN_DIR, "safeupdate-bootguard")
ARM_HELPER = "/usr/local/sbin/safeupdate-arm-boot"
ARM_HELPER_PLUGIN = os.path.join(PLUGIN_DIR, "safeupdate-arm-boot")

MARKER_PLUGIN = "r34-dev3 EARLY-BOOT FALLBACK"
MARKER_GUARD = "r34-dev3 early-boot fallback"
BACKUP_ROOT = "/root"

ARM_HELPER_TEXT = '#!/usr/bin/env python3\n# SafeUpdate2026 r34-dev3 early-boot armer\n# Arms a bootloader-level safety net for VU+ Duo 4K SE:\n#   /boot/STARTUP      -> verified backup slot\n#   /boot/STARTUP_ONCE -> updated source slot\n\nimport json\nimport os\nimport re\nimport subprocess\n\nPLAN_FILE = "/boot/.safeupdate2026-recovery.json"\nSTARTUP = "/boot/STARTUP"\nSTARTUP_ONCE = "/boot/STARTUP_ONCE"\nORIGINAL_STARTUP = "/boot/.safeupdate2026-startup.preupdate"\n\ndef log(msg):\n    print("[SafeUpdateArm] %s" % msg)\n\ndef read_bytes(path):\n    with open(path, "rb") as f:\n        return f.read()\n\ndef read_text(path):\n    try:\n        with open(path, "r", encoding="utf-8", errors="replace") as f:\n            return f.read()\n    except Exception:\n        return ""\n\ndef board():\n    return read_text("/proc/device-tree/bolt/board").replace("\\x00", "").strip().lower()\n\ndef current_slot():\n    cmd = read_text("/proc/cmdline")\n    for key in ("rootsubdir", "kernel"):\n        m = re.search(r"(?:^|\\s)%s=([^\\s]+)" % key, cmd)\n        if not m:\n            continue\n        val = m.group(1).strip("\'\\"")\n        m2 = re.search(r"(?:^|/)linuxrootfs(\\d+)(?:/zImage)?$", val)\n        if m2:\n            return int(m2.group(1))\n    return None\n\ndef startup_for_slot(slot):\n    path = "/boot/STARTUP_%d" % int(slot)\n    text = read_text(path)\n    if not text:\n        return None\n    m = re.search(r"(?:^|[\\s\'\\"])rootsubdir=([^\\s\'\\"]+)", text)\n    if not m:\n        return None\n    sub = os.path.normpath(m.group(1).lstrip("/"))\n    if sub.startswith("../") or sub == ".." or sub.split("/")[-1] != "linuxrootfs%d" % int(slot):\n        return None\n    if not re.search(r"(?:^|[\\s\'\\"])root=([^\\s\'\\"]+)", text):\n        return None\n    if not re.search(r"(?:^|[\\s\'\\"])kernel=([^\\s\'\\"]+)", text):\n        return None\n    return path\n\ndef startup_points_to(path, slot):\n    text = read_text(path)\n    if not text:\n        return False\n    m = re.search(r"(?:^|[\\s\'\\"])rootsubdir=([^\\s\'\\"]+)", text)\n    if not m:\n        return False\n    sub = os.path.normpath(m.group(1).lstrip("/"))\n    return (not sub.startswith("../") and sub != ".." and\n            sub.split("/")[-1] == "linuxrootfs%d" % int(slot) and\n            re.search(r"(?:^|[\\s\'\\"])root=([^\\s\'\\"]+)", text) is not None and\n            re.search(r"(?:^|[\\s\'\\"])kernel=([^\\s\'\\"]+)", text) is not None)\n\ndef atomic_write(path, data, mode=0o644):\n    tmp = path + ".safeupdate-new"\n    try:\n        with open(tmp, "wb") as f:\n            f.write(data)\n            f.flush()\n            os.fsync(f.fileno())\n        try:\n            os.chmod(tmp, mode)\n        except Exception:\n            pass\n        os.replace(tmp, path)\n    finally:\n        try:\n            if os.path.exists(tmp):\n                os.unlink(tmp)\n        except Exception:\n            pass\n\ndef sync():\n    subprocess.call(["sync"])\n\ndef load_plan():\n    with open(PLAN_FILE, "r", encoding="utf-8") as f:\n        d = json.load(f)\n    if not isinstance(d, dict):\n        raise RuntimeError("Recovery-Plan ist kein JSON-Objekt.")\n    return d\n\ndef save_plan(plan):\n    data = (json.dumps(plan, indent=2, sort_keys=True) + "\\n").encode("utf-8")\n    atomic_write(PLAN_FILE, data, 0o644)\n    sync()\n\ndef rollback(orig_startup, old_once):\n    try:\n        atomic_write(STARTUP, orig_startup, 0o644)\n    except Exception as e:\n        log("WARNUNG: STARTUP-Rollback fehlgeschlagen: %s" % e)\n    try:\n        if old_once is None:\n            if os.path.exists(STARTUP_ONCE):\n                os.unlink(STARTUP_ONCE)\n        else:\n            atomic_write(STARTUP_ONCE, old_once, 0o644)\n    except Exception as e:\n        log("WARNUNG: STARTUP_ONCE-Rollback fehlgeschlagen: %s" % e)\n    sync()\n\ndef main():\n    if board() != "duo4kse":\n        log("Boxlayout ist nicht duo4kse; Early-Boot-Arming wird nicht benötigt.")\n        return 0\n\n    if not os.path.isfile(PLAN_FILE):\n        log("Kein Recovery-Plan vorhanden; nichts zu tun.")\n        return 0\n\n    plan = load_plan()\n    if plan.get("version") != 2 or plan.get("phase") != "armed":\n        raise RuntimeError("Recovery-Plan ist nicht in Phase \'armed\'.")\n\n    try:\n        source = int(plan.get("source_slot"))\n        backup = int(plan.get("backup_slot"))\n    except Exception:\n        raise RuntimeError("Recovery-Plan enthält ungültige Slotnummern.")\n\n    if source <= 0 or backup <= 0 or source == backup:\n        raise RuntimeError("Unsichere source_slot/backup_slot-Zuordnung.")\n\n    cur = current_slot()\n    if cur != source:\n        raise RuntimeError("Aktiver Slot %s passt nicht zum Quellslot %s." % (cur, source))\n\n    source_startup = startup_for_slot(source)\n    backup_startup = startup_for_slot(backup)\n    if not source_startup:\n        raise RuntimeError("STARTUP_%d ist nicht sicher validierbar." % source)\n    if not backup_startup:\n        raise RuntimeError("STARTUP_%d ist nicht sicher validierbar." % backup)\n\n    source_data = read_bytes(source_startup)\n    backup_data = read_bytes(backup_startup)\n\n    if startup_points_to(STARTUP, backup) and os.path.exists(STARTUP_ONCE):\n        try:\n            if read_bytes(STARTUP_ONCE) == source_data:\n                plan["bootloader_fallback_armed"] = True\n                plan["bootloader_default_slot"] = backup\n                plan["bootloader_once_slot"] = source\n                save_plan(plan)\n                log("Bootloader-Fallback war bereits korrekt scharf.")\n                return 0\n        except Exception:\n            pass\n\n    if not startup_points_to(STARTUP, source):\n        raise RuntimeError("/boot/STARTUP zeigt vor dem Arming nicht auf Quellslot %d." % source)\n    if os.path.exists(STARTUP_ONCE):\n        raise RuntimeError("Unerwartetes /boot/STARTUP_ONCE vorhanden; Arming abgebrochen.")\n\n    orig_startup = read_bytes(STARTUP)\n    old_once = None\n\n    if os.path.exists(ORIGINAL_STARTUP):\n        if not startup_points_to(ORIGINAL_STARTUP, source):\n            raise RuntimeError("Alter STARTUP-Sicherungsrest passt nicht zum Quellslot.")\n    else:\n        atomic_write(ORIGINAL_STARTUP, orig_startup, 0o644)\n\n    try:\n        atomic_write(STARTUP, backup_data, 0o644)\n        atomic_write(STARTUP_ONCE, source_data, 0o644)\n        sync()\n\n        if not startup_points_to(STARTUP, backup):\n            raise RuntimeError("Readback von /boot/STARTUP auf Sicherheits-Slot fehlgeschlagen.")\n        if read_bytes(STARTUP_ONCE) != source_data:\n            raise RuntimeError("Readback von /boot/STARTUP_ONCE fehlgeschlagen.")\n\n        plan["bootloader_fallback_armed"] = True\n        plan["bootloader_default_slot"] = backup\n        plan["bootloader_once_slot"] = source\n        save_plan(plan)\n    except Exception:\n        rollback(orig_startup, old_once)\n        raise\n\n    log("EARLY-BOOT FALLBACK SCHARF: STARTUP -> Slot %d, STARTUP_ONCE -> Slot %d." % (backup, source))\n    return 0\n\nif __name__ == "__main__":\n    try:\n        raise SystemExit(main())\n    except Exception as e:\n        log("FEHLER: %s" % e)\n        raise SystemExit(1)\n'
PLUGIN_INSERT = '            # r34-dev3 EARLY-BOOT FALLBACK:\n            # On VU+ Duo 4K SE the updated slot is tried once while the\n            # verified safety slot becomes the persistent default. This also\n            # covers failures that happen before init/SSH/BootGuard.\n            if recovery_ok:\n                _su_board = ""\n                try:\n                    with open("/proc/device-tree/bolt/board", "rb") as _su_f:\n                        _su_board = _su_f.read().replace(b"\\x00", b"").decode("ascii", "ignore").strip().lower()\n                except Exception:\n                    _su_board = ""\n                if _su_board == "duo4kse":\n                    _su_arm = "/usr/local/sbin/safeupdate-arm-boot"\n                    if not os.path.isfile(_su_arm):\n                        recovery_ok = False\n                        recovery_text = "Early-Boot-Recovery-Helfer fehlt: %s" % _su_arm\n                    else:\n                        try:\n                            _su_arm_rc = subprocess.call([_su_arm])\n                        except Exception:\n                            _su_arm_rc = 127\n                        if _su_arm_rc != 0:\n                            recovery_ok = False\n                            recovery_text = "Bootloader-Fallback konnte nicht sicher vorbereitet werden (RC=%s)." % _su_arm_rc\n'
GUARD_REPLACEMENT = 'def set_startup_default(slot):\n    src = startup_for_slot(slot)\n    if not src:\n        raise RuntimeError("STARTUP_%d nicht sicher validierbar" % int(slot))\n    dst = "/boot/STARTUP"\n    tmp = dst + ".safeupdate-new"\n    with open(src, "rb") as fsrc, open(tmp, "wb") as fdst:\n        while True:\n            data = fsrc.read(65536)\n            if not data:\n                break\n            fdst.write(data)\n        fdst.flush()\n        os.fsync(fdst.fileno())\n    os.replace(tmp, dst)\n    subprocess.call(["sync"])\n\ndef cleanup_source_startup_once(slot):\n    dst = "/boot/STARTUP_ONCE"\n    src = startup_for_slot(slot)\n    if not src or not os.path.exists(dst):\n        return\n    try:\n        with open(src, "rb") as a, open(dst, "rb") as b:\n            same = a.read() == b.read()\n        if same:\n            os.unlink(dst)\n            subprocess.call(["sync"])\n    except Exception:\n        pass\n\ndef mark_healthy(plan):\n    # Restore the normal persistent boot target BEFORE declaring the update\n    # healthy. If this fails we deliberately keep the safety slot as default.\n    source = int(plan.get("source_slot") or 0)\n    if source <= 0:\n        raise RuntimeError("Quellslot fehlt beim Abschluss des BootGuard.")\n    set_startup_default(source)\n    cleanup_source_startup_once(source)\n\n    plan["bootloader_fallback_armed"] = False\n    plan["bootloader_default_slot"] = source\n    plan["phase"] = "healthy"\n    plan["healthy_at"] = int(time.time())\n    save_plan(plan)\n\n    try:\n        pre = "/boot/.safeupdate2026-startup.preupdate"\n        if os.path.exists(pre):\n            os.unlink(pre)\n    except Exception:\n        pass\n\n    try:\n        os.replace(PLAN_FILE, PLAN_FILE + ".last-good")\n    except Exception:\n        try:\n            os.unlink(PLAN_FILE)\n        except Exception:\n            pass\n    subprocess.call(["sync"])\n    log("Erster Boot nach Update ist stabil. STARTUP wurde auf Quellslot %d zurückgestellt." % source)\n'

def die(msg):
    print("FEHLER: " + msg)
    raise SystemExit(1)

def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def write_atomic(path, text, mode=None):
    tmp = path + ".r34dev3-new"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    if mode is not None:
        os.chmod(tmp, mode)
    os.replace(tmp, path)

def backup(paths):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(BACKUP_ROOT, "SafeUpdate2026-r34dev3-backup-" + stamp)
    os.makedirs(dest, exist_ok=False)
    for p in paths:
        if os.path.exists(p):
            name = p.strip("/").replace("/", "__")
            shutil.copy2(p, os.path.join(dest, name))
    return dest

def patch_plugin(text):
    if MARKER_PLUGIN in text:
        return text, False

    needle = "            recovery_ok, recovery_text = safeupdate_dev2_prepare_recovery_plan()\n"
    if text.count(needle) != 1:
        die("plugin.py: erwartete genau 1 Recovery-Aufruf, gefunden %d." % text.count(needle))

    text = text.replace(needle, needle + PLUGIN_INSERT, 1)
    return text, True

def patch_bootguard(text):
    changed = False

    if MARKER_GUARD not in text:
        header = "# SafeUpdate2026 r34-dev2 boot guard\n"
        if text.count(header) != 1:
            die("safeupdate-bootguard: r34-dev2 Header nicht eindeutig gefunden.")
        text = text.replace(header, header + "# r34-dev3 early-boot fallback\n", 1)
        changed = True

    old_phase = '    if plan.get("version") != 2 or plan.get("phase") != "armed":\n'
    new_phase = '    if plan.get("version") != 2 or plan.get("phase") not in ("armed", "restoring"):\n'
    if old_phase in text:
        if text.count(old_phase) != 1:
            die("safeupdate-bootguard: Phase-Prüfung nicht eindeutig.")
        text = text.replace(old_phase, new_phase, 1)
        changed = True
    elif new_phase not in text:
        die("safeupdate-bootguard: erwartete Phase-Prüfung fehlt.")

    start = text.find("def mark_healthy(plan):\n")
    end = text.find("\ndef fallback(plan, reason):\n", start)
    if start < 0 or end < 0:
        die("safeupdate-bootguard: mark_healthy/fallback Block nicht gefunden.")

    current_block = text[start:end]
    if "set_startup_default" not in current_block:
        text = text[:start] + GUARD_REPLACEMENT + text[end:]
        changed = True

    return text, changed

def compile_check(path):
    py_compile.compile(path, doraise=True)

def main():
    if os.geteuid() != 0:
        die("Bitte als root auf der Box ausführen.")

    for p in (PLUGIN, BOOTGUARD):
        if not os.path.isfile(p):
            die("Datei fehlt: %s" % p)

    plugin_text = read(PLUGIN)
    guard_text = read(BOOTGUARD)

    if "r34-dev2" not in guard_text and MARKER_GUARD not in guard_text:
        die("Abbruch: installierter BootGuard ist nicht die erwartete r34-dev2 Basis.")

    plugin_new, plugin_changed = patch_plugin(plugin_text)
    guard_new, guard_changed = patch_bootguard(guard_text)

    if (not plugin_changed and not guard_changed and
            os.path.isfile(ARM_HELPER) and os.path.isfile(ARM_HELPER_PLUGIN)):
        print("Bereits gepatcht; keine Änderung nötig.")
        return 0

    backup_dir = backup([PLUGIN, BOOTGUARD, BOOTGUARD_PLUGIN, ARM_HELPER, ARM_HELPER_PLUGIN])
    print("Backup: " + backup_dir)

    try:
        write_atomic(PLUGIN, plugin_new, 0o644)
        write_atomic(BOOTGUARD, guard_new, 0o755)
        write_atomic(BOOTGUARD_PLUGIN, guard_new, 0o755)
        write_atomic(ARM_HELPER, ARM_HELPER_TEXT, 0o755)
        write_atomic(ARM_HELPER_PLUGIN, ARM_HELPER_TEXT, 0o755)

        compile_check(PLUGIN)
        compile_check(BOOTGUARD)
        compile_check(ARM_HELPER)
        subprocess.call(["sync"])
    except Exception as e:
        print("PATCH FEHLGESCHLAGEN: %s" % e)
        print("Originale liegen unter: %s" % backup_dir)
        raise

    print("")
    print("==============================================")
    print(" SafeUpdate2026 r34-dev3 EARLY-BOOT FIX: OK")
    print("==============================================")
    print("Geändert:")
    print(" - Recovery-Plan armt vor dem Reboot den Bootloader-Fallback")
    print(" - /boot/STARTUP wird Sicherheits-Slot (dauerhafter Fallback)")
    print(" - /boot/STARTUP_ONCE testet den aktualisierten Quellslot einmal")
    print(" - BootGuard stellt STARTUP nach stabilem Boot auf Quellslot zurück")
    print(" - Phase 'restoring' wird ebenfalls überwacht")
    print("")
    print("WICHTIG: Noch ist KEIN Recovery-Vorgang scharf.")
    print("Vor dem echten Update erst Preflight prüfen.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
