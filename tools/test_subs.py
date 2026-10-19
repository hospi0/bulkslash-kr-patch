# -*- coding: utf-8 -*-
"""자막 훅 검산(SH-2 흉내기, 스테이트 메모리 위) — python tools/test_subs.py [스테이트이름=nav1]
   요청 훅 → 지도·셀 확인 → 프레임을 흘리며 쪽 넘김·끝 지움 → 합류 화면(스크롤)·스테이지 아님·남의 지도 칸이면 안 그림.
   미리보기 work/pv_subs_<번호>.png (NBG0 위쪽 화면 320×224, 실제 CRAM 팔레트)"""
import os, struct, sys
import numpy as np
from PIL import Image
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import subs as B, sh2sim as S

R = B.build()
name = sys.argv[1] if len(sys.argv) > 1 else 'nav1'
MEM = os.path.join(ROOT, 'work', 'mem', name)


def fresh():
    m = S.Mem()
    m.add(0x06000000, 0x100000, open(os.path.join(MEM, 'WorkRAMH.bin'), 'rb').read())
    low = bytearray(open(os.path.join(MEM, 'WorkRAML.bin'), 'rb').read()); low[:len(R['font'])] = R['font']
    m.add(0x00200000, 0x100000, bytes(low))
    m.add(0x25E00000, 0x80000, open(os.path.join(MEM, 'VDP2_VRAM.bin'), 'rb').read())
    return m


def orig_req(r, mem):                      # 0x06007788 흉내: 바쁘지 않으면 번호·깃발
    if mem.r16(0x06023616) == 0 and mem.r16(0x0602343C) == 0 and r[4] < mem.r16(0x06023F10):
        mem.w16(0x06023F38, r[4]); mem.w16(0x06023F3A, 1)
    r[15] = r[14]; r[14] = mem.r32(r[15]); r[15] += 4      # 원래 끝: mov r14,r15 / rts / mov.l @r15+,r14


CALLS = {B.REQ_CONT: orig_req, B.SRV_CONT: lambda r, mem: None}
lab = R['lab']


def req(m, n):
    r, _ = S.run(m, lab['req'], regs=[0, 0, 0, 0, n, 0, 0, 0, 0x1111, 0x2222, 0x3333, 0x4444, 0x5555, 0x6666, 0x7777], calls=CALLS)
    assert r[8:15] == [0x1111, 0x2222, 0x3333, 0x4444, 0x5555, 0x6666, 0x7777], '요청 훅이 r8‥r14 를 망가뜨림'


def frame(m, vbl=1):
    for _ in range(vbl): S.run(m, lab['vbl'], calls=CALLS)
    r, _ = S.run(m, lab['srv'], regs=[0, 0, 0, 0, 1, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14], calls=CALLS)
    assert r[4:15] == [1, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14], '프레임 훅이 레지스터를 망가뜨림'


def ours(m):
    return sum(1 for rr in range(min(B.ROW, B.ROW2), max(B.ROW, B.ROW2) + 4) for c in range(B.COLS)
               if m.r16(B.MAPBUF + rr * 128 + c * 2) & 0xFF80 == B.MAPV)


def preview(m, path):
    cram = open(os.path.join(MEM, 'CRAM.bin'), 'rb').read()
    cram = np.frombuffer(bytes(b for i in range(0, len(cram), 2) for b in (cram[i + 1], cram[i])), '>u2').astype(int)
    out = np.zeros((224, 320, 3), np.uint8)
    for cy in range(28):
        for cx in range(40):
            w = m.r16(B.MAPBUF + cy * 128 + cx * 2)
            if not w: continue
            chn = (w & 0xFFF) | 0x3000; pal = w >> 12
            for y in range(8):
                for x in range(8):
                    b = m.r8(0x25E00000 + chn * 32 + y * 4 + x // 2); px = (b >> 4) if x % 2 == 0 else (b & 15)
                    if px:
                        e = cram[pal * 16 + px]
                        out[cy * 8 + y, cx * 8 + x] = [(e & 31) << 3, (e >> 5 & 31) << 3, (e >> 10 & 31) << 3]
            if w & 0xC00: pass
    Image.fromarray(out).resize((640, 448), Image.NEAREST).save(path)


ok = True
# 1) 짧은 음성 28(전방입니다)
m = fresh(); m.w16(0x06023616, 0); m.w16(0x0602343C, 0)
req(m, 28)
print('28 요청: 켜짐', m.r32(B.STATE), '끝', m.r32(B.STATE + 8), '지도 칸', ours(m), '시계 방식', m.r32(B.STATE + 24),
      '콜백', hex(m.r32(B.VBL_SLOT)))
preview(m, os.path.join(ROOT, 'work', 'pv_subs_28.png'))
ok &= ours(m) > 0 and m.r32(B.VBL_SLOT) == lab['vbl']
end = m.r32(B.STATE + 8); seen = 0
for f in range(end + 5):
    frame(m); seen += ours(m) > 0
print('  프레임 흘림: 보인 프레임', seen, '(기대 %d) 끝 뒤 지도 칸' % (end - 1), ours(m), '켜짐', m.r32(B.STATE))
ok &= ours(m) == 0 and m.r32(B.STATE) == 0 and abs(seen - (end - 1)) <= 1

# 2) 긴 음성 72(두 줄 이상 → 쪽 넘김)
m = fresh(); req(m, 72); preview(m, os.path.join(ROOT, 'work', 'pv_subs_72a.png'))
pages = []; last = None
for f in range(m.r32(B.STATE + 8) + 3):
    sig = tuple(m.r16(B.MAPBUF + (B.ROW + i // 40) * 128 + (i % 40) * 2) for i in range(160))
    if sig != last: pages.append(f); last = sig
    if f == 150: preview(m, os.path.join(ROOT, 'work', 'pv_subs_72b.png'))
    frame(m)
print('72: 지도 바뀐 프레임', pages)

# 3) 다른 음성이 오면 바꿔 그림, 자막 없는 번호(75)면 지움
m = fresh(); req(m, 72); req(m, 29); a = ours(m); req(m, 75); b = ours(m)
print('바꿔 그림: 29 지도 칸', a, '· 75(자막 없음) 뒤', b, '켜짐', m.r32(B.STATE)); ok &= a > 0 and b == 0 and m.r32(B.STATE) == 0

# 4) 합류 화면(SCYIN0 ≠ 0)이면 안 그림 · 그리던 중 스크롤되면 지움
m = fresh(); m.w16(B.SCY, 0x100); req(m, 28); a = ours(m)
m.w16(B.SCY, 0); req(m, 28); m.w16(B.SCY, 0x100); frame(m); b = ours(m)
print('합류 화면: 시작 안 함', a == 0, '· 도중 지움', b == 0); ok &= a == 0 and b == 0

# 5) 스테이지 프로그램 아님(표지 없음)이면 안 그림
m = fresh(); m.w32(B.SIG[0][0], 0); req(m, 28)
print('스테이지 아님: 지도 칸', ours(m), '켜짐', m.r32(B.STATE)); ok &= ours(m) == 0 and m.r32(B.STATE) == 0

# 6) 두 후보 자리(1‥4행·4‥7행)에 모두 남의 칸이 있으면 안 그림(그 칸은 그대로)
m = fresh(); m.w16(B.MAPBUF + (B.ROW + 1) * 128 + 10, 0x5158); m.w16(B.MAPBUF + (B.ROW2 + 2) * 128 + 10, 0x5158); req(m, 28)   # 두 자리 다 막힘
print('남의 지도 칸: 우리 칸', ours(m), '남의 칸 유지', hex(m.r16(B.MAPBUF + (B.ROW + 1) * 128 + 10)))
ok &= ours(m) == 0 and m.r16(B.MAPBUF + (B.ROW + 1) * 128 + 10) == 0x5158

# 7) 콜백 칸이 남의 함수면 안 건드리고 메인 루프 셈(1회 = 2)
m = fresh(); m.w32(B.VBL_SLOT, 0x06012340); req(m, 28)
e = m.r32(B.STATE + 8); n = 0
while m.r32(B.STATE) and n < 999:
    S.run(m, lab['srv'], calls=CALLS); n += 1
print('콜백 남의 것: 칸 유지', hex(m.r32(B.VBL_SLOT)), '· 메인 루프', n, '회에 끝(기대 약 %d)' % ((e + 1) // 2))
ok &= m.r32(B.VBL_SLOT) == 0x06012340 and abs(n - (e + 1) // 2) <= 1

# 8) 받아들여지지 않은 요청(바쁨)은 자막 안 바꿈
m = fresh(); req(m, 72); a = ours(m); m.w16(0x06023616, 1); m.w16(0x06023F3A, 0); req(m, 29)
print('바쁠 때 요청: 72 자막 유지', ours(m) == a and m.r32(B.STATE) == 1); ok &= ours(m) == a

# 9) 보스 체력 바(2행)가 있어도 기본 자리 4‥7행에 그림, 남의 칸은 그대로
# 10) 기본 자리가 막히면 1‥4행
m = fresh()
for c in range(10, 31): m.w16(B.MAPBUF + 2 * 128 + c * 2, 0x01CC)
req(m, 28)
r47 = sum(1 for rr in range(B.ROW, B.ROW + 4) for c in range(B.COLS) if m.r16(B.MAPBUF + rr * 128 + c * 2) & 0xFF80 == B.MAPV)
bar = all(m.r16(B.MAPBUF + 2 * 128 + c * 2) == 0x01CC for c in range(10, 31))
print('보스 체력 바: 기본 자리 우리 칸', r47, '· 체력 바 유지', bar); ok &= r47 > 0 and bar
preview(m, os.path.join(ROOT, 'work', 'pv_subs_boss.png'))
end = m.r32(B.STATE + 8)
for f in range(end + 3): frame(m)
print('  끝 뒤 우리 칸', ours(m), '· 체력 바 유지', all(m.r16(B.MAPBUF + 2 * 128 + c * 2) == 0x01CC for c in range(10, 31))); ok &= ours(m) == 0

m = fresh(); m.w16(B.MAPBUF + 5 * 128 + 10, 0x5158); req(m, 28)
r14 = sum(1 for rr in range(1, 4) for c in range(B.COLS) if m.r16(B.MAPBUF + rr * 128 + c * 2) & 0xFF80 == B.MAPV)
free14 = all(fresh().r16(B.MAPBUF + rr * 128 + c * 2) == 0 for rr in range(1, 5) for c in range(B.COLS))
print('기본 자리 막힘: 1‥4행 우리 칸', r14, '(1‥4행이 비어 있으면 >0, 아니면 0 기대)'); ok &= (r14 > 0) == free14

print('전부 통과' if ok else '★실패 있음')
