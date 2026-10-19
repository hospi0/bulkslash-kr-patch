# -*- coding: utf-8 -*-
r"""벌크 슬래시 시험 디스크 — 원본 Track 1 을 복사해 1ST.BIN·KANJI.FON 을 제자리(같은 크기)에 덮고 EDC/ECC 재계산.
   먼저 python tools/subs.py 로 work/kr/ 를 만든다. 디렉터리·크기 변경 없음.
   python tools/build_disc.py --write     # OUT 에 기록(허락받고!)"""
import os, shutil, struct, sys
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import cdmode1
SRC = r'C:\claude\roms\ss\Bulk Slash (Japan)'
BASE = 'Bulk Slash (Japan)'
OUT = r'F:\hospi\roms\ss roms\Bulk Slash (Japan)'
FILES = [('1ST.BIN', 22, 356352), ('KANJI.FON', 67116, 249792)] + [  # (이름, LBA, 크기) — tools/iso.py list
    ('ALL.ST1', 15570, 2136064), ('ALL.ST2', 16613, 2129920), ('ALL.ST3', 17653, 2144256), ('ALL.ST4', 18700, 2140160), ('ALL.ST5', 19745, 2136064), ('ALL.ST6', 20788, 2146304), ('ALL.ST7', 21836, 2181120), ('SEL_DEMO.ALL', 22901, 1615872), ('TITLE.ALL', 24114, 804864)]   # 브리핑·합류 포인터 표만 바뀜


def main():
    t_src = os.path.join(SRC, BASE + ' (Track 1).bin')
    ok, bad = cdmode1.verify(t_src, range(16, 16 + 200))
    assert bad == 0, 'EDC/ECC 규약 검산 실패'
    new = {n: open(os.path.join(ROOT, 'work', 'kr', n), 'rb').read() for n, _, _ in FILES}
    for n, lba, size in FILES:
        assert len(new[n]) == size, (n, len(new[n]), size)
    if '--write' not in sys.argv:
        print('검산만(규약 %d/%d) — 기록하려면 --write' % (ok, ok + bad)); return
    os.makedirs(OUT, exist_ok=True)
    t1 = os.path.join(OUT, BASE + ' (Track 1).bin')
    shutil.copyfile(t_src, t1)
    for fn in (BASE + ' (Track 2).bin', BASE + ' (Track 3).bin', BASE + '.cue'):
        d = os.path.join(OUT, fn)
        if not os.path.exists(d) or os.path.getsize(d) != os.path.getsize(os.path.join(SRC, fn)):
            shutil.copyfile(os.path.join(SRC, fn), d)
    f = open(t1, 'r+b'); changed = 0
    for n, lba, size in FILES:
        d = new[n]
        for k in range((size + 2047) // 2048):
            f.seek((lba + k) * 2352); s = bytearray(f.read(2352))
            chunk = d[k * 2048:k * 2048 + 2048]
            if s[16:16 + len(chunk)] == chunk: continue
            s[16:16 + len(chunk)] = chunk; cdmode1.fix(s); f.seek((lba + k) * 2352); f.write(s); changed += 1
    f.close()
    print('기록: 섹터 %d개 바꿈 → %s' % (changed, t1))


if __name__ == '__main__':
    main()
