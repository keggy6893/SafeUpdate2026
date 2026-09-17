#!/usr/bin/env python3
from pathlib import Path
import re
import sys

p = Path(sys.argv[1])
s = p.read_text(encoding='utf-8')

old_version = 'PLUGIN_VERSION = "2026.1-r33-dev2"'
new_version = 'PLUGIN_VERSION = "2026.1-r33-dev3"'
if s.count(old_version) != 1:
    raise SystemExit('unexpected dev2 version marker count: %d' % s.count(old_version))
s = s.replace(old_version, new_version, 1)

# Fail-closed architecture gate. Only layouts explicitly supported by r33 may use
# automatic/manual rotation. All normal r32 backup/update/rollback functions stay available.
anchor = '_BACKGROUND_PATH = "/usr/lib/enigma2/python/Plugins/Extensions/SafeUpdate2026/" + _BACKGROUND_FILE\n'
insert = '''_BACKGROUND_PATH = "/usr/lib/enigma2/python/Plugins/Extensions/SafeUpdate2026/" + _BACKGROUND_FILE


def rotation_layout_supported():
    """True only for receiver layouts explicitly allowed to rotate backups in r33."""
    if _USE_CLASSIC_VU_DUO4KSE:
        return True
    if is_gbtrio4k():
        return True
    return False


def rotation_layout_name():
    if _USE_CLASSIC_VU_DUO4KSE:
        return "VU+ Duo 4K SE"
    if is_gbtrio4k():
        return "GigaBlue UHD Trio 4K"
    return "nicht freigegebenes Layout"
'''
if s.count(anchor) != 1:
    raise SystemExit('background anchor count: %d' % s.count(anchor))
s = s.replace(anchor, insert, 1)

# Status must never advertise rotation on an unsupported receiver.
pattern = re.compile(r'def rotation_status_text\(state\):\n.*?\n\ndef _rotation_seed\(', re.S)
replacement = '''def rotation_status_text(state):
    if not isinstance(state, dict) or not state.get("verified"):
        return "Status: Noch kein verifiziertes Backup."
    if not rotation_layout_supported():
        return "Status: Backup verifiziert · Auto-Rotation NICHT VERFÜGBAR"
    if not state.get("rotation_enabled", False):
        return "Status: Backup verifiziert · Auto-Rotation AUS (Taste 8)"
    return "Status: Backup verifiziert · Auto 24h EIN · nächste Prüfung %s" % rotation_time_text(state.get("rotation_next_due", 0))


def _rotation_seed('''
s, n = pattern.subn(replacement, s, count=1)
if n != 1:
    raise SystemExit('could not patch rotation_status_text')

# Clamp every seed call (manual backup, slot rotation, internal rotation) to the gate.
old = '''    fp = fingerprint if fingerprint is not None else current_system_fingerprint()
    result["rotation_enabled"] = bool(enabled)
    result["system_fingerprint"] = fp or ""
'''
new = '''    fp = fingerprint if fingerprint is not None else current_system_fingerprint()
    enabled = bool(enabled and rotation_layout_supported())
    result["rotation_enabled"] = enabled
    result["system_fingerprint"] = fp or ""
'''
if s.count(old) != 1:
    raise SystemExit('rotation seed enable block count: %d' % s.count(old))
s = s.replace(old, new, 1)

# Existing states from dev1/dev2 are forced OFF on unsupported boxes.
pattern = re.compile(r'def ensure_rotation_state\(state\):\n.*?\n\ndef rotation_temp_path_safe\(', re.S)
replacement = '''def ensure_rotation_state(state):
    if state is None:
        return None
    result = dict(state)
    if not rotation_layout_supported():
        changed = (
            result.get("rotation_enabled") is not False or
            int(result.get("rotation_next_due") or 0) != 0 or
            result.get("rotation_last_error") != "Auto-Rotation sicher deaktiviert: Box-/Slot-Layout nicht freigegeben."
        )
        result["rotation_enabled"] = False
        result["rotation_next_due"] = 0
        result["rotation_last_error"] = "Auto-Rotation sicher deaktiviert: Box-/Slot-Layout nicht freigegeben."
        result.pop("rotation_post_update_hold_until", None)
        if changed:
            persist_rotation_state(result)
        return result
    if "rotation_enabled" not in result:
        result = _rotation_seed(result, True)
        persist_rotation_state(result)
    elif result.get("rotation_enabled") and not result.get("rotation_next_due"):
        result["rotation_next_due"] = int(time.time()) + ROTATION_INTERVAL
        if not result.get("system_fingerprint"):
            result["system_fingerprint"] = current_system_fingerprint()
        persist_rotation_state(result)
    return result


def rotation_temp_path_safe('''
s, n = pattern.subn(replacement, s, count=1)
if n != 1:
    raise SystemExit('could not patch ensure_rotation_state')

# Do not start/schedule a background timer on an unsupported layout.
old = '''        try:
            self.timer.start(5 * 60 * 1000, True)
        except Exception:
            pass

    def _schedule_periodic(self):
        try:
            self.timer.start(ROTATION_TICK_MS, False)
        except Exception:
            pass
'''
new = '''        if rotation_layout_supported():
            try:
                self.timer.start(5 * 60 * 1000, True)
            except Exception:
                pass

    def _schedule_periodic(self):
        if not rotation_layout_supported():
            return
        try:
            self.timer.start(ROTATION_TICK_MS, False)
        except Exception:
            pass
'''
if s.count(old) != 1:
    raise SystemExit('rotation timer block count: %d' % s.count(old))
s = s.replace(old, new, 1)

# Gate the worker before it even reads/changes rotation state.
old = '''    def check(self, force=False, ui=None):
        global _SAFEUPDATE_UI_OPEN
        if self.busy:
            return False
        if _SAFEUPDATE_UI_OPEN and ui is None:
            return False

        state = physically_verified_rotation_state()
'''
new = '''    def check(self, force=False, ui=None):
        global _SAFEUPDATE_UI_OPEN
        if self.busy:
            return False
        if _SAFEUPDATE_UI_OPEN and ui is None:
            return False
        if not rotation_layout_supported():
            if force:
                self._emit("Rotation blockiert: Box-/Slot-Layout ist für r33 nicht freigegeben.")
            return False

        state = physically_verified_rotation_state()
'''
if s.count(old) != 1:
    raise SystemExit('rotation service check anchor count: %d' % s.count(old))
s = s.replace(old, new, 1)

# No background service is instantiated on unknown boxes.
old = '''    if reason == 0:
        session = kwargs.get("session")
        if session is not None:
            get_rotation_service(session)
'''
new = '''    if reason == 0:
        session = kwargs.get("session")
        if session is not None and rotation_layout_supported():
            get_rotation_service(session)
'''
if s.count(old) != 1:
    raise SystemExit('sessionstart block count: %d' % s.count(old))
s = s.replace(old, new, 1)

# Keys 8 and 7 fail closed with a clear explanation on unsupported boxes.
old = '''    def toggle_rotation(self):
        if self.busy:
            return
        state = physically_verified_rotation_state()
'''
new = '''    def toggle_rotation(self):
        if self.busy:
            return
        if not rotation_layout_supported():
            self.session.open(
                MessageBox,
                "Auto-Rotation ist auf dieser Box sicher deaktiviert.\\n\\nDas Box-/Slot-Layout ist für r33 noch nicht freigegeben. Normales Backup, Update, Killswitch und Rollback bleiben verfügbar.",
                MessageBox.TYPE_INFO,
            )
            return
        state = physically_verified_rotation_state()
'''
if s.count(old) != 1:
    raise SystemExit('toggle_rotation anchor count: %d' % s.count(old))
s = s.replace(old, new, 1)

old = '''    def force_rotation_now(self):
        if self.busy:
            return
        state = physically_verified_rotation_state()
'''
new = '''    def force_rotation_now(self):
        if self.busy:
            return
        if not rotation_layout_supported():
            self.session.open(
                MessageBox,
                "Rotation ist auf dieser Box blockiert.\\n\\nDas Box-/Slot-Layout ist für r33 noch nicht freigegeben; es wird nichts verändert.",
                MessageBox.TYPE_INFO,
            )
            return
        state = physically_verified_rotation_state()
'''
if s.count(old) != 1:
    raise SystemExit('force_rotation anchor count: %d' % s.count(old))
s = s.replace(old, new, 1)

# Details screen must state the gate explicitly instead of showing a stale dev2 ON state.
old = '''        auto_text = "EIN / 24h" if st.get("rotation_enabled", False) else "AUS"
        next_text = rotation_time_text(st.get("rotation_next_due", 0)) if st.get("rotation_enabled", False) else "-"
'''
new = '''        if rotation_layout_supported():
            auto_text = "EIN / 24h" if st.get("rotation_enabled", False) else "AUS"
            next_text = rotation_time_text(st.get("rotation_next_due", 0)) if st.get("rotation_enabled", False) else "-"
        else:
            auto_text = "NICHT VERFÜGBAR"
            next_text = "-"
'''
if s.count(old) != 1:
    raise SystemExit('details auto text block count: %d' % s.count(old))
s = s.replace(old, new, 1)

required = [
    'PLUGIN_VERSION = "2026.1-r33-dev3"',
    'def rotation_layout_supported():',
    '_USE_CLASSIC_VU_DUO4KSE',
    'if is_gbtrio4k():',
    'Auto-Rotation NICHT VERFÜGBAR',
    'enabled = bool(enabled and rotation_layout_supported())',
    'Auto-Rotation sicher deaktiviert: Box-/Slot-Layout nicht freigegeben.',
    'if not rotation_layout_supported():',
    'session is not None and rotation_layout_supported()',
    'Normales Backup, Update, Killswitch und Rollback bleiben verfügbar.',
    'es wird nichts verändert.',
    'auto_text = "NICHT VERFÜGBAR"',
    'UPDATE GESPERRT – BACKUP LÄUFT',
    'ROTATION_VERIFIED',
]
for marker in required:
    if marker not in s:
        raise SystemExit('missing dev3 safety marker: %r' % marker)

p.write_text(s, encoding='utf-8')
print('r33-dev3 architecture gate patch: OK')
