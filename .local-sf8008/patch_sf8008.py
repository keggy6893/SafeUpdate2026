# -*- coding: utf-8 -*-
from __future__ import print_function

import io
import re
import sys

path = sys.argv[1]
with io.open(path, 'r', encoding='utf-8') as f:
    s = f.read()

if 'PLUGIN_VERSION = "2026.1-r32"' not in s:
    raise SystemExit('expected r32 source')
s = s.replace('PLUGIN_VERSION = "2026.1-r32"', 'PLUGIN_VERSION = "2026.1-r32-local-sf8008-1"', 1)

marker = '''def is_gbtrio4k():\n    # /proc/stb/info/model reports dm8000 on the tested receiver, so use cmdline identity.\n    return machinebuild() == "gbtrio4k" and oem_name() == "gigablue"\n\n\n'''
if marker not in s:
    raise SystemExit('is_gbtrio4k marker missing')
insert = marker + '''def is_sf8008():\n    # SF8008 also reports a bogus dm8000 model on some images.\n    # The cmdline is authoritative for the tested Octagon receiver.\n    return machinebuild() == "sf8008" and oem_name() == "octagon"\n\n\ndef is_hisi4slot_emmc():\n    # Verified shared-root layout used by GigaBlue UHD Trio 4K and Octagon SF8008:\n    # root=/dev/mmcblk0p16, linuxrootfs1..4, kernel p12..p15.\n    return is_gbtrio4k() or is_sf8008()\n\n\n'''
s = s.replace(marker, insert, 1)

# Generalize all operational GigaBlue-only branches to the verified shared HISI layout.
s = re.sub(r'(?<!def )is_gbtrio4k\(\)', 'is_hisi4slot_emmc()', s)

# HDD status: tested SF8008 uses /media/hdd. Either standard mount is acceptable.
s = s.replace('if len(parts) >= 2 and parts[1] == "/media/usb":',
              'if len(parts) >= 2 and parts[1] in ("/media/usb", "/media/hdd"):', 1)

# User-facing wording must not claim the SF8008 is a GigaBlue.
repls = {
    'GigaBlue Kernel-/Slot-Struktur ist nicht eindeutig verifizierbar.': 'HISI-4Slot Kernel-/Slot-Struktur ist nicht eindeutig verifizierbar.',
    'GigaBlue Kernel-Slot nicht sicher verifizierbar.': 'HISI-4Slot Kernel-Slot nicht sicher verifizierbar.',
    'GigaBlue Kernel-Slot ist nicht sicher verifizierbar.': 'HISI-4Slot Kernel-Slot ist nicht sicher verifizierbar.',
    'Kopiere GigaBlue Kernel-Slot...': 'Kopiere separaten Kernel-Slot...',
    'Setze GigaBlue Kernel-Pakete auf HOLD...': 'Setze Kernel-Pakete auf HOLD...',
    'GigaBlue Kernel-Pakete konnten nicht sicher auf HOLD gesetzt werden.': 'Kernel-Pakete konnten nicht sicher auf HOLD gesetzt werden.',
    'GigaBlue: RootFS plus separate Kernelpartition': 'HISI-4Slot: RootFS plus separate Kernelpartition',
}
for old, new in repls.items():
    s = s.replace(old, new)

# Details label: show either accepted HDD mount rather than hard-coding only /media/usb.
s = s.replace('HDD /media/usb: %s', 'HDD /media/usb|hdd: %s')

# r32 details can show a stale default 'slot' before the first internal backup.
old = 'backup_mode = st.get("backup_mode", "slot")'
if old in s:
    s = s.replace(old,
        'backup_mode = st.get("backup_mode") or ("internal" if (not free_slots()) else "slot")', 1)

required = [
    'def is_sf8008():',
    'def is_hisi4slot_emmc():',
    'machinebuild() == "sf8008"',
    'oem_name() == "octagon"',
    'GBTRIO4K_ROOT_DEVICE = "/dev/mmcblk0p16"',
    '1: "/dev/mmcblk0p12"',
    '2: "/dev/mmcblk0p13"',
    '3: "/dev/mmcblk0p14"',
    '4: "/dev/mmcblk0p15"',
    'INTERNAL_BACKUP_DIRNAME = "safeupdate2026"',
    'Kein vorhandener Multiboot-Slot wird verändert.',
    '9 = WIEDERHERSTELLEN',
]
for item in required:
    if item not in s:
        raise SystemExit('missing required marker: %r' % item)

# After generalization only the function definition itself retains is_gbtrio4k().
left = [m.start() for m in re.finditer(r'is_gbtrio4k\(\)', s)]
if len(left) != 1:
    raise SystemExit('unexpected remaining is_gbtrio4k() calls: %d' % len(left))

with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
    f.write(s)
print('SF8008 local patch applied')
