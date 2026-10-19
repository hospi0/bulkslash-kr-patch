# -*- coding: utf-8 -*-
"""Bulk Slash (Japan) Track 1(MODE1/2352) ISO9660 읽기 — python tools/iso.py [list|extract 이름…]"""
import os, struct, sys
sys.stdout.reconfigure(encoding='utf-8')
ROM = r'C:\claude\roms\ss\Bulk Slash (Japan)\Bulk Slash (Japan) (Track 1).bin'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
f = open(ROM, 'rb')


def sec(lba, n=1):
    out = b''
    for i in range(n):
        f.seek((lba + i) * 2352 + 16); out += f.read(2048)
    return out


def walk(lba, size, path=''):
    d = sec(lba, (size + 2047) // 2048); i = 0
    while i < len(d):
        ln = d[i]
        if ln == 0:
            i = (i // 2048 + 1) * 2048; continue
        el = struct.unpack_from('<I', d, i + 2)[0]; es = struct.unpack_from('<I', d, i + 10)[0]
        fl = d[i + 25]; nl = d[i + 32]; name = d[i + 33:i + 33 + nl].decode('ascii', 'replace')
        if name not in ('\x00', '\x01'):
            p = path + '/' + name.split(';')[0]
            if fl & 2:
                yield from walk(el, es, p)
            else:
                yield p, el, es
        i += ln


pvd = sec(16)
rl = struct.unpack_from('<I', pvd, 156 + 2)[0]; rs = struct.unpack_from('<I', pvd, 156 + 10)[0]
files = list(walk(rl, rs))
if len(sys.argv) < 2 or sys.argv[1] == 'list':
    for p, l, s in files:
        print('%-40s %8d %10d' % (p, l, s))
    print(len(files), '개', sum(s for _, _, s in files), 'B')
else:
    os.makedirs(os.path.join(ROOT, 'work', 'iso'), exist_ok=True)
    want = set(sys.argv[2:])
    for p, l, s in files:
        if not want or p.lstrip('/') in want:
            open(os.path.join(ROOT, 'work', 'iso', p.lstrip('/').replace('/', '_')), 'wb').write(sec(l, (s + 2047) // 2048)[:s])
