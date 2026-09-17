#!/usr/bin/env python3
from pathlib import Path
import re
import sys

p = Path(sys.argv[1])
s = p.read_text(encoding='utf-8')

old_version = 'PLUGIN_VERSION = "2026.1-r33-dev1"'
new_version = 'PLUGIN_VERSION = "2026.1-r33-dev2"'
if s.count(old_version) != 1:
    raise SystemExit('unexpected dev1 version marker count: %d' % s.count(old_version))
s = s.replace(old_version, new_version, 1)

# Make rotation-driven UI busy state repaint the update area immediately,
# and restore the normal state as soon as the operation finishes.
pattern = re.compile(
    r'    def _ui_start\(self, ui, title, status\):\n.*?'
    r'    def _start_slot_rotation\(self, state, fingerprint, ui\):',
    re.S,
)
replacement = '''    def _ui_start(self, ui, title, status):
        self.ui = ui
        if ui is not None:
            try:
                ui.busy = True
                ui.paint_update_state()
                ui.set_backup_progress(10, title, status)
            except Exception:
                pass

    def _ui_finish(self):
        ui = self.ui
        if ui is not None:
            try:
                ui.busy = False
                ui.paint_update_state()
            except Exception:
                pass
        return ui

    def _start_slot_rotation(self, state, fingerprint, ui):'''
s, n = pattern.subn(replacement, s, count=1)
if n != 1:
    raise SystemExit('could not patch rotation UI busy lifecycle')

# Replace update painter with an explicit red lock while any safety operation is busy.
pattern = re.compile(
    r'    def paint_update_state\(self\):\n.*?'
    r'    def connect_container\(self, data_cb, close_cb\):',
    re.S,
)
replacement = '''    def paint_update_state(self):
        """Paint update availability; safety operations get a real red lock overlay."""
        try:
            self["updateHint"].show()
            if self.busy:
                lock_text = "UPDATE GESPERRT – BACKUP LÄUFT"
                lock_hint = "Sicherheitsbackup wird erstellt und verifiziert."
                if self.pending_delete is not None:
                    lock_text = "UPDATE GESPERRT – LÖSCHEN LÄUFT"
                    lock_hint = "Sicherheitsvorgang wird abgeschlossen."
                elif self.pending_restore is not None:
                    lock_text = "UPDATE GESPERRT – WIEDERHERSTELLUNG"
                    lock_hint = "Notfall-Rückkehr wird sicher abgeschlossen."
                self["updateButton"].setText(lock_text)
                self["updateButton"].show()
                self["updateHint"].setText(lock_hint)
                try:
                    self["updateButton"].instance.setBackgroundColor(parseColor("#9b111e"))
                    self["updateButton"].instance.setForegroundColor(parseColor("#ffffff"))
                    self["updateButton"].instance.setBorderColor(parseColor("#ff5a5f"))
                    self["updateHint"].instance.setForegroundColor(parseColor("#ffb3b8"))
                except Exception:
                    pass
            elif self.backup_verified:
                # The enabled button is baked into background.png; hide the overlay.
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
                    self["updateButton"].instance.setBorderColor(parseColor("#71cdea"))
                    self["updateHint"].instance.setForegroundColor(parseColor("#b8d6e8"))
                except Exception:
                    pass
        except Exception:
            pass

    def connect_container(self, data_cb, close_cb):'''
s, n = pattern.subn(replacement, s, count=1)
if n != 1:
    raise SystemExit('could not patch update state painter')

old = '''    def start_update(self):
        if self.busy:
            return
        if not self.backup_verified:
'''
new = '''    def start_update(self):
        if self.busy:
            self.session.open(
                MessageBox,
                "Update ist gesperrt, solange ein Sicherheitsvorgang läuft.",
                MessageBox.TYPE_INFO,
            )
            return
        if not self.backup_verified:
'''
if s.count(old) != 1:
    raise SystemExit('unexpected start_update busy guard count: %d' % s.count(old))
s = s.replace(old, new, 1)

# Static dev2 markers.
required = [
    'PLUGIN_VERSION = "2026.1-r33-dev2"',
    'UPDATE GESPERRT – BACKUP LÄUFT',
    '#9b111e',
    'ui.paint_update_state()',
    'Update ist gesperrt, solange ein Sicherheitsvorgang läuft.',
    'if self.busy:',
    'ROTATION_VERIFIED',
]
for marker in required:
    if marker not in s:
        raise SystemExit('missing dev2 marker: %r' % marker)

p.write_text(s, encoding='utf-8')
print('r33-dev2 patch: OK')
