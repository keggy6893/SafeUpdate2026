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


one('PLUGIN_VERSION = "2026.1-r30"', 'PLUGIN_VERSION = "2026.1-r31"', 'version')

# GigaBlue STARTUP lines wrap the kernel arguments in single quotes, e.g.
# boot ... 'root=/dev/mmcblk0p16 rootsubdir=linuxrootfs1 ...'
# r30 required whitespace before root=, so the first argument was never parsed.
for key in ("root", "rootsubdir", "kernel"):
    old = 'r"(?:^|\\s)%s=([^\\s]+)"' % key
    new = 'r"(?:^|[\\s\\\'\\\"])%s=([^\\s\\\'\\\"]+)"' % key
    n = s.count(old)
    if n != 1:
        raise SystemExit("startup %s regex: expected 1 match, got %d" % (key, n))
    s = s.replace(old, new, 1)

p.write_text(s, encoding="utf-8")
compile(p.read_bytes(), str(p), "exec")

# Verify the exact STARTUP quoting style reported by the real GigaBlue tester.
sample = (
    "boot emmcflash0.linuxkernel1 'root=/dev/mmcblk0p16 "
    "rootsubdir=linuxrootfs1 rootfstype=ext4 kernel=/dev/mmcblk0p12 "
    "userdataroot=/dev/mmcblk0p16 userdatasubdir=userdata1'"
)
expected = {
    "root": "/dev/mmcblk0p16",
    "rootsubdir": "linuxrootfs1",
    "kernel": "/dev/mmcblk0p12",
}
for key, value in expected.items():
    rx = re.compile(r"(?:^|[\s'\"])%s=([^\s'\"]+)" % re.escape(key))
    m = rx.search(sample)
    if not m or m.group(1) != value:
        raise SystemExit("quoted STARTUP parser self-test failed for %s" % key)

checks = [
    'PLUGIN_VERSION = "2026.1-r31"',
    'GBTRIO4K_ROOT_DEVICE = "/dev/mmcblk0p16"',
    '1: "/dev/mmcblk0p12"',
    '4: "/dev/mmcblk0p15"',
    'dd if="$SRC_KERNEL" of="$DST_KERNEL"',
    'slot_backup_valid(target, dst)',
    'resolution="1920,1080"',
    'scale="1"',
]
for item in checks:
    if item not in s:
        raise SystemExit("missing r31 invariant: %s" % item)

print("r31 parser fix + syntax + invariants: OK")
