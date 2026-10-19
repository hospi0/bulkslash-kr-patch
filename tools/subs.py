# -*- coding: utf-8 -*-
r"""벌크 슬래시 음성 자막 빌더 (2026-10-19, PoC — 1스테이지 스테이트 기준 «보수적» 설계, docs/00_survey.md)

전제(조사 결과):
  - 음성 요청 0x0600777C(1ST.BIN 상주, r4 = 클립 번호) → 받아들여지면 0x06023F38 = 번호, 0x06023F3A = 1.
  - 음성 서버 0x060071FC = 스테이지 메인 루프가 매 프레임 부름 → 프레임 훅.
  - 열린 묶음 표 0x06023F40(16 B × N) — 첫 항목 «실제 길이»(+12)로 VCP0‥6/VCDM 구별.
  - 글자 = 게임 자체 글 경로 그대로: KANJI.FON(Low RAM 0x00200000, 16×16 1비트 JIS 순) → VDP2 4비트 셀 0x25E77000(글자당 0x80, 32자)
    + NBG0 지도 RAM 버퍼 0x060B7000(메인 루프가 매 프레임 VRAM 0x25E7C000 으로 복사). 지도 값 = 0x0B80 + 글자칸×4 (+1 오른쪽, +2 아래, +3).
  - 스테이지 표지: 0x06034850(ST1‥6) 또는 0x060344FC(ST7) 에 0x060B7000 리터럴. 합류 화면 = SCYIN0 그림자 0x060FFD34 ≠ 0 → 그때는 안 그림.
  - 시계: SGL 사용자 VBlank 콜백(GBR+0x340 = 0x060FFF40)이 빈 RTS(0x0601FAC4)일 때만 우리 카운터를 끼움(음성 요청 때 확인). 아니면 메인 루프 1회 = 2 VBlank 로 셈.
  - 코드·자막 데이터 = KANJI.FON 의 빈 JIS 행 0x28‥0x2F(원본도 빈 글자, Low RAM 0x00205240‥0x0020B040).
  - 한글 글자 칸 = JIS 제2수준 한자 칸 중 «게임 원문 어디에도 안 쓰인» 칸(스태프 롤 포함 — 스태프 롤 글자는 그대로 둠).

  python tools/subs.py            # work/kr/KANJI.FON · work/kr/1ST.BIN 만들기 + 보고(디스크는 안 건드림)
"""
import glob, os, re, struct, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import sh2asm

ISO = os.path.join(ROOT, 'work', 'iso')
OUTD = os.path.join(ROOT, 'work', 'kr')
KFONT = ImageFont.truetype(r'C:\claude\utils\font\Galmuri-v2.40.3\Galmuri.ttc', 15, index=0)   # Galmuri14(버닝 레인저 메일과 같음) — 판정은 사용자

# ---- 주소 ----
FONT = 0x00200000
REGION, REGION_END = FONT + 658 * 32, FONT + 1410 * 32          # JIS 0x28‥0x2F 행(빈 글자)
STATE = REGION                                                   # 32 B: +0 켜짐 +4 지금 시각 +8 끝 +12 다음 쪽 +16 시작 VBlank +20 VBlank 수 +24 시계 방식
CODE = REGION + 32
MAPBUF = 0x060B7000; ROW = 1; COLS = 40                          # 지도 1‥4행(화면 위 8‥40 px) — 1스테이지에선 빈 행
CELLS = 0x25E77000; MAXGLYPH = 32; MAPV = 0x0B80
REQ, REQ_CONT = 0x0600777C, 0x06007788
SRV, SRV_CONT = 0x060071FC, 0x06007208
VBL_SLOT, VBL_DEFAULT = 0x060FFF40, 0x0601FAC4
SCY = 0x060FFCC0 + 0x74
SIG = [(0x06034850, 0x060B7000), (0x060344FC, 0x060B7000)]
TAB = 0x06023F40
LINGER = 30                                                      # 음성 끝 뒤 남김(0.5초)
INK, EDGE = 15, 1                                                # 팔레트 0: 15 흰색 · 1 검정(1스테이지 CRAM)
BANKS = ['VCP0', 'VCP1', 'VCP2', 'VCP3', 'VCP4', 'VCP5', 'VCP6', 'VCDM']
PUNCT = ',.!?:;)]}\'"~、。，．！？：；）］｝」』】〉》”’…‥・·～〜♪♥'


def squeeze(t):
    """문장부호 뒤 공백 1칸 지움(전 프로젝트 규칙 feedback_no_space_after_punct)"""
    return re.sub('([' + re.escape(PUNCT) + '])[ 　](?![ 　])', r'\1', t)


def half(ch):
    return ord(ch) < 0x80


# ============ 글꼴 칸 ============
def used_codes():
    """원문 어디서든 쓰일 수 있는 SJIS 2바이트 코드(넉넉히 = 안전) — 이 칸은 안 건드린다"""
    pat = re.compile(rb'(?:[\x81-\x9f\xe0-\xef][\x40-\x7e\x80-\xfc]){2,}')
    out = set()
    for fn in glob.glob(os.path.join(ISO, '*')):
        b = os.path.basename(fn)
        if b.startswith('VC') or b.endswith('.CPK'):
            continue
        d = open(fn, 'rb').read()
        for m in pat.finditer(d):
            s = m.group()
            for j in range(0, len(s), 2):
                out.add(s[j] << 8 | s[j + 1])
    return out


def jis_of(code):
    a, b = code >> 8, code & 0xFF
    a = (a - 0x70 if a < 0xA0 else a - 0xB0) * 2 - 1
    if b >= 0x9F: a += 1; b -= 0x7E
    else: b -= 0x1F if b < 0x80 else 0x20
    return a, b


def free_slots(nfont):
    used = set()
    for c in used_codes():
        try:
            a, b = jis_of(c)
        except Exception:
            continue
        if 0x21 <= a <= 0x7E and 0x21 <= b <= 0x7E:
            used.add((a - 0x21) * 94 + b - 0x21)
    lo = (0x50 - 0x21) * 94                                      # 제2수준 한자부터
    return [i for i in range(lo, nfont) if i not in used]


def glyph(ch):
    im = Image.new('L', (16, 16), 0); dr = ImageDraw.Draw(im); dr.fontmode = '1'
    dr.text((4 if half(ch) else 8, 8), ch, font=KFONT, fill=255, anchor='mm')
    a = np.array(im) > 0
    return b''.join(struct.pack('>H', int(''.join('1' if x else '0' for x in r), 2)) for r in a)


# ============ 번역 → 쪽 ============
def load_trans():
    T = {}
    for fn in sorted(glob.glob(os.path.join(ROOT, 'work', 'trans', '*.tsv'))):
        for ln in open(fn, encoding='utf-8').read().splitlines()[1:]:
            p = ln.split('\t')
            if len(p) >= 3 and p[2].strip():
                T[p[0]] = squeeze(p[2].strip())
    return T


def width(s):
    return sum(1 if half(c) else 2 for c in s)


def lines_of(t, maxw=COLS - 2):
    """띄어쓰기 자리에서 줄 나눔(번역은 안 깎음)"""
    out, cur = [], ''
    for w in t.split(' '):
        cand = (cur + ' ' + w) if cur else w
        if width(cand) <= maxw:
            cur = cand
        else:
            if cur: out.append(cur)
            cur = w
    if cur: out.append(cur)
    return out


def pages_of(t):
    ls = lines_of(t); pages = []
    while ls:
        pg = ls[:2]
        while sum(len(l.replace(' ', '')) for l in pg) > MAXGLYPH and len(pg) > 1:
            pg = pg[:1]
        pages.append(pg); ls = ls[len(pg):]
    return pages


def clip_frames(name):
    for ln in open(os.path.join(ROOT, 'work', 'vc_table.tsv'), encoding='utf-8').read().splitlines()[1:]:
        p = ln.split('\t')
        if p[0] == name:
            return int(p[4]) * 60 // 22050 + 1
    raise KeyError(name)


def record(pages, frames, slot_of):
    """u16: 끝 프레임, [쪽: 시작 프레임, 항목…, 0], 0xFFFF
       항목: 0xFFC0|열 = 새 줄(행 +2)·열 지정 · 0xFFFD = 반각 공백(1열) · 그 밖 = 글꼴 칸(bit15 = 반각 글자)"""
    total = sum(len(''.join(p).replace(' ', '')) for p in pages) or 1
    out = [frames + LINGER]; acc = 0
    for pg in pages:
        out.append(acc * frames // total)
        for l in pg:
            out.append(0xFFC0 | (COLS - width(l)) // 2)
            for ch in l:
                if ch == ' ':
                    out.append(0xFFFD)
                else:
                    s = slot_of[ch]; out.append(s | (0x8000 if half(ch) else 0))
            acc += len(l.replace(' ', ''))
        out.append(0)
    out.append(0xFFFF)
    return out


# ============ SH-2 훅 ============
def hook_asm(data_base):
    L = lambda v: '#0x%08X' % v
    return f'''
req:                        ; 0x0600777C 에서 옴 — 원래 함수를 부르고, 받아들여졌으면 자막 시작(r8‥r14 보존)
  sts.l pr,@-r15
  mov.l r8,@-r15
  mov.l r9,@-r15
  mov.l r10,@-r15
  mov.l r11,@-r15
  mov.l r12,@-r15
  mov.l r13,@-r15
  mov.l r14,@-r15
  mov.l r4,@-r15
  mov r4,r8
  mov.l #tramp,r0
  jsr @r0
  nop
  extu.w r8,r8
  mov.l {L(0x06023F3A)},r1
  mov.w @r1,r0
  cmp/eq #1,r0
  bf req_out
  mov.l {L(0x06023F38)},r1
  mov.w @r1,r0
  extu.w r0,r0
  cmp/eq r8,r0
  bf req_out
  mov.l #start,r0
  jsr @r0
  mov r8,r4
req_out:
  mov.l @r15+,r4
  mov.l @r15+,r14
  mov.l @r15+,r13
  mov.l @r15+,r12
  mov.l @r15+,r11
  mov.l @r15+,r10
  mov.l @r15+,r9
  mov.l @r15+,r8
  lds.l @r15+,pr
  rts
  nop
tramp:                      ; 원래 0x0600777C‥0x06007787 (덮인 6 명령)
  mov.l r14,@-r15
  mov r15,r14
  extu.w r4,r4
  mov.l {L(0x06023F10)},r1
  mov.w @r1,r1
  extu.w r1,r1
  mov.l {L(REQ_CONT)},r0
  jmp @r0
  nop

srv:                        ; 0x060071FC 에서 옴 — 프레임마다
  sts.l pr,@-r15
  mov.l r4,@-r15
  mov.l r5,@-r15
  mov.l r6,@-r15
  mov.l r7,@-r15
  mov.l r8,@-r15
  mov.l r9,@-r15
  mov.l r10,@-r15
  mov.l r11,@-r15
  mov.l r12,@-r15
  mov.l r13,@-r15
  mov.l r14,@-r15
  mov.l #frame,r0
  jsr @r0
  nop
  mov.l @r15+,r14
  mov.l @r15+,r13
  mov.l @r15+,r12
  mov.l @r15+,r11
  mov.l @r15+,r10
  mov.l @r15+,r9
  mov.l @r15+,r8
  mov.l @r15+,r7
  mov.l @r15+,r6
  mov.l @r15+,r5
  mov.l @r15+,r4
  lds.l @r15+,pr
  mov.l r8,@-r15            ; 원래 0x060071FC‥0x06007207
  mov.l r9,@-r15
  mov.l r10,@-r15
  mov.l r11,@-r15
  mov.l r14,@-r15
  sts.l pr,@-r15
  mov.l {L(SRV_CONT)},r0
  jmp @r0
  nop

vbl:                        ; SGL 사용자 VBlank 콜백(빈 칸일 때만 끼움) — r0·r1 만
  mov.l #{STATE + 20:#x},r0
  mov.l @r0,r1
  add #1,r1
  rts
  mov.l r1,@r0

start:                      ; r4 = 클립 번호
  sts.l pr,@-r15
  mov.l r4,@-r15
  bsr clear
  nop
  bsr stage_ok
  nop
  bf st_pop
  mov.l {L(TAB + 12)},r1
  mov.l @r1,r2
  mov.l #banks,r3
st_find:
  mov.l @r3,r1
  tst r1,r1
  bt st_pop
  cmp/eq r1,r2
  bt st_found
  bra st_find
  add #12,r3
st_found:
  mov.l @r15+,r4
  mov.l @(4,r3),r5
  mov.l @(8,r3),r6
  extu.w r4,r4
  cmp/hs r6,r4
  bt st_out
  shll r4
  add r4,r5
  mov.w @r5,r0
  extu.w r0,r0
  tst r0,r0
  bt st_out
  mov.l {L(data_base)},r1
  add r1,r0
  mov.w @r0+,r1
  extu.w r1,r1
  mov.l {L(STATE)},r8
  mov.l r1,@(8,r8)
  mov.l r0,@(12,r8)
  mov #0,r1
  mov.l r1,@(4,r8)
  ; 시계: 콜백 칸이 빈 RTS 면 우리 것으로(이미 우리 것이면 그대로)
  mov #0,r7
  mov.l {L(VBL_SLOT)},r1
  mov.l @r1,r0
  mov.l #vbl,r2
  cmp/eq r2,r0
  bt st_vok
  mov.l {L(VBL_DEFAULT)},r3
  cmp/eq r3,r0
  bf st_vset
  mov.l r2,@r1
st_vok:
  mov #1,r7
st_vset:
  mov.l r7,@(24,r8)
  mov.l @(20,r8),r1
  mov.l r1,@(16,r8)
  mov #1,r1
  mov.l r1,@r8
  bsr step
  nop
  bra st_out
  nop
st_pop:
  mov.l @r15+,r4
st_out:
  lds.l @r15+,pr
  rts
  nop

stage_ok:                   ; T=1: 스테이지 프로그램 + 게임 화면(스크롤 0)
  mov.l {L(0x060B7000)},r0
  mov.l {L(SIG[0][0])},r1
  mov.l @r1,r1
  cmp/eq r0,r1
  bt so_scy
  mov.l {L(SIG[1][0])},r1
  mov.l @r1,r1
  cmp/eq r0,r1
  bf so_out
so_scy:
  mov.l {L(SCY)},r1
  mov.w @r1,r0
  tst r0,r0
so_out:
  rts
  nop

frame:
  sts.l pr,@-r15
  mov.l {L(STATE)},r8
  mov.l @r8,r0
  tst r0,r0
  bt fr_out
  bsr stage_ok
  nop
  bf fr_clear
  mov.l @(24,r8),r0
  tst r0,r0
  bt fr_loop
  mov.l @(20,r8),r1         ; VBlank 시계: 지금 − 시작
  mov.l @(16,r8),r2
  sub r2,r1
  bra fr_have
  nop
fr_loop:
  mov.l @(4,r8),r1          ; 콜백 못 끼움: 메인 루프 1회 = 2
  add #2,r1
fr_have:
  mov.l r1,@(4,r8)
  mov.l @(8,r8),r2
  cmp/hs r2,r1
  bt fr_clear
  bsr step
  nop
  bra fr_out
  nop
fr_clear:
  bsr clear
  nop
fr_out:
  lds.l @r15+,pr
  rts
  nop

clear:                      ; 끄기 + 우리 지도 칸만 지움
  mov.l {L(STATE)},r1
  mov #0,r0
  mov.l r0,@r1
clear_map:
  mov.l {L(MAPBUF + ROW * 128)},r1
  mov #4,r2
  mov.l #0xFF80,r6
  mov.l {L(MAPV)},r7
cm_row:
  mov #{COLS},r3
  mov r1,r5
cm_col:
  mov.w @r5,r0
  and r6,r0
  cmp/eq r7,r0
  bf cm_next
  mov #0,r0
  mov.w r0,@r5
cm_next:
  dt r3
  bf/s cm_col
  add #2,r5
  mov.l #128,r0
  dt r2
  bf/s cm_row
  add r0,r1
  rts
  nop

rows_free:                  ; T=1: 지도 칸이 모두 0 이거나 우리 것
  mov.l {L(MAPBUF + ROW * 128)},r1
  mov #4,r2
  mov.l #0xFF80,r6
  mov.l {L(MAPV)},r7
rf_row:
  mov #{COLS},r3
  mov r1,r5
rf_col:
  mov.w @r5,r0
  extu.w r0,r0
  tst r0,r0
  bt rf_ok
  and r6,r0
  cmp/eq r7,r0
  bf rf_bad
rf_ok:
  dt r3
  bf/s rf_col
  add #2,r5
  mov.l #128,r0
  dt r2
  bf/s rf_row
  add r0,r1
  rts
  nop
rf_bad:
  mov #1,r0
  rts
  tst r0,r0

step:                       ; 때가 된 쪽을 그림
  sts.l pr,@-r15
  mov.l {L(STATE)},r8
  mov.l @(12,r8),r9
  mov.w @r9,r0
  extu.w r0,r0
  mov.l #0xFFFF,r1
  cmp/eq r1,r0
  bt sp_out
  mov.l @(4,r8),r1
  cmp/hs r0,r1
  bf sp_out
  add #2,r9
  bsr rows_free
  nop
  bf sp_skip
  bsr clear_map
  nop
  bsr draw_page
  nop
  bra sp_save
  nop
sp_skip:
  mov.w @r9+,r0
  extu.w r0,r0
  tst r0,r0
  bf sp_skip
sp_save:
  mov.l r9,@(12,r8)
sp_out:
  lds.l @r15+,pr
  rts
  nop

draw_page:                  ; r9 = 항목 → 끝(0) 뒤로
  sts.l pr,@-r15
  mov #0,r10
  mov.l {L(MAPBUF + ROW * 128 - 256)},r11
dp_loop:
  mov.w @r9+,r0
  extu.w r0,r0
  tst r0,r0
  bt dp_out
  mov.l #0xFFFD,r1
  cmp/eq r1,r0
  bf dp_notsp
  bra dp_loop
  add #2,r12
dp_notsp:
  mov.l #0xFFC0,r1
  mov r0,r2
  and r1,r2
  cmp/eq r1,r2
  bf dp_glyph
  mov.l #256,r1             ; 새 줄 = 지도 2행 아래
  add r1,r11
  mov #0x3F,r1
  and r1,r0
  shll r0
  mov r11,r12
  bra dp_loop
  add r0,r12
dp_glyph:
  mov r0,r13
  mov #{MAXGLYPH},r1
  cmp/hs r1,r10
  bt dp_loop
  mov.l #0x1FFF,r1
  and r1,r0
  mov r0,r4
  bsr draw_glyph
  mov r10,r5
  mov r10,r0
  shll2 r0
  mov.l {L(MAPV)},r1
  add r1,r0
  mov.w r0,@r12
  mov r12,r2
  mov.l #128,r1
  add r1,r2
  add #2,r0
  mov.w r0,@r2
  mov.l #0x8000,r1
  tst r1,r13
  bf dp_half
  add #-1,r0
  mov.w r0,@(2,r12)
  add #2,r0
  mov.w r0,@(2,r2)
  bra dp_next
  add #4,r12
dp_half:
  add #2,r12
dp_next:
  bra dp_loop
  add #1,r10
dp_out:
  lds.l @r15+,pr
  rts
  nop

draw_glyph:                 ; r4 = 글꼴 칸, r5 = 셀 칸 — 흰 글자 + 검은 테두리(8방향 1 px) · r8‥r14·pr 보존
  sts.l pr,@-r15
  mov.l r8,@-r15
  mov.l r9,@-r15
  mov.l r10,@-r15
  mov.l r11,@-r15
  mov.l r12,@-r15
  mov.l r13,@-r15
  mov.l r14,@-r15
  shll2 r4
  shll2 r4
  shll r4
  mov.l {L(FONT)},r1
  add r1,r4
  shll2 r5
  shll2 r5
  shll2 r5
  shll r5
  mov.l {L(CELLS)},r1
  add r1,r5
  mov #0,r6
  mov.w @r4+,r7
  extu.w r7,r7
  mov #16,r9
  mov #0,r14
dg_row:
  mov #0,r8
  mov r9,r0
  cmp/eq #1,r0
  bt dg_nonext
  mov.w @r4,r8
  extu.w r8,r8
dg_nonext:
  mov r6,r1
  or r7,r1
  or r8,r1
  mov r1,r2
  shll r2
  mov r1,r3
  shlr r3
  or r2,r1
  or r3,r1
  not r7,r2
  and r2,r1
  mov #0,r10
  mov.l #0x8000,r12
  mov #8,r13
  bsr dg_px
  nop
  mov r10,r11
  mov #0,r10
  mov #8,r13
  bsr dg_px
  nop
  mov r14,r0
  mov #7,r3
  and r3,r0
  shll2 r0
  mov r14,r2
  mov #8,r3
  and r3,r2
  shll2 r2
  shll r2
  add r2,r0
  add r5,r0
  mov.l r11,@r0
  add #0x20,r0
  mov.l r10,@r0
  mov r7,r6
  mov r8,r7
  add #2,r4
  add #1,r14
  dt r9
  bf dg_row
  mov.l @r15+,r14
  mov.l @r15+,r13
  mov.l @r15+,r12
  mov.l @r15+,r11
  mov.l @r15+,r10
  mov.l @r15+,r9
  mov.l @r15+,r8
  lds.l @r15+,pr
  rts
  nop
dg_px:                      ; r13 화소 → r10 (4비트씩), r12 = 지금 비트(다음 비트로 밀림)
  shll2 r10
  shll2 r10
  tst r12,r7
  bt dg_noink
  bra dg_pnext
  add #{INK},r10
dg_noink:
  tst r12,r1
  bt dg_pnext
  nop
  add #{EDGE},r10
dg_pnext:
  dt r13
  bf/s dg_px
  shlr r12
  rts
  nop
'''


def stub(target):
    """덮는 6 명령: mov.l @(1,pc),r0 / jmp @r0 / nop / nop / .long target (시작 주소가 4 의 배수라 리터럴은 +8)"""
    return bytes.fromhex('d001402b00090009') + struct.pack('>I', target)


def build():
    os.makedirs(OUTD, exist_ok=True)
    font = bytearray(open(os.path.join(ISO, 'KANJI.FON'), 'rb').read()); nfont = len(font) // 32
    exe = bytearray(open(os.path.join(ISO, '1ST.BIN'), 'rb').read())
    assert not any(font[REGION - FONT:REGION_END - FONT]), '빈 행이 비어 있지 않다'
    T = load_trans()
    # 글자 → 칸
    chars = sorted(set(c for t in T.values() for c in t if c != ' '))
    slots = free_slots(nfont)
    assert len(chars) <= len(slots), (len(chars), len(slots))
    slot_of = {c: slots[i] for i, c in enumerate(chars)}
    for c, s in slot_of.items():
        font[s * 32:s * 32 + 32] = glyph(c)
    # 자막 기록
    recs = {}
    for k, t in T.items():
        recs[k] = record(pages_of(t), clip_frames(k), slot_of)
    # 데이터: 묶음 표(12 B × 8 + 끝 0) · 묶음별 색인(u16 × N) · 기록
    tabn = {}
    for b in BANKS:
        d = open(os.path.join(ISO, b + '.DAT'), 'rb').read(); n = 0
        while struct.unpack_from('>I', d, n * 16)[0]: n += 1
        tabn[b] = (struct.unpack_from('>I', d, 12)[0], n)
    used_banks = [b for b in BANKS if any(k.startswith(b + '_') for k in recs)]
    # 코드 크기 먼저 재기(데이터 시작 주소가 코드 뒤라서 두 번 어셈블)
    code = sh2asm.assemble(hook_asm(0) + 'banks:\n  .long 0\n', CODE)
    data_base = (CODE + len(code) + 64 + 3) & ~3
    blob = bytearray()
    bank_tab = bytearray(); idx_parts = []
    off = 12 * len(used_banks) + 4
    for b in used_banks:
        fp, n = tabn[b]
        bank_tab += struct.pack('>III', fp, data_base + off, n)
        idx_parts.append((b, n, off)); off += 2 * n
    bank_tab += b'\0' * 4
    rec_off = off; recbytes = bytearray(); idx = {}
    for b, n, o in idx_parts:
        arr = [0] * n
        for i in range(n):
            k = '%s_%02d' % (b, i)
            if k in recs:
                arr[i] = rec_off + len(recbytes)
                recbytes += b''.join(struct.pack('>H', w) for w in recs[k])
        idx[b] = arr
    blob += bank_tab
    for b, n, o in idx_parts:
        blob += b''.join(struct.pack('>H', w) for w in idx[b])
    blob += recbytes
    assert max([0] + [w for a in idx.values() for w in a]) < 0x10000
    src = hook_asm(data_base).replace('#banks', '#0x%08X' % data_base)
    code = sh2asm.assemble(src, CODE)
    assert CODE + len(code) <= data_base, '코드가 데이터 자리를 넘음'
    assert data_base + len(blob) <= REGION_END, ('자리 넘침', hex(data_base + len(blob)), hex(REGION_END))
    font[STATE - FONT:STATE - FONT + 32] = b'\0' * 32
    font[CODE - FONT:CODE - FONT + len(code)] = code
    font[data_base - FONT:data_base - FONT + len(blob)] = blob
    lab = labels(src)
    # 1ST.BIN 덮기(덮이는 원래 바이트 검사)
    assert exe[REQ - 0x06004000:REQ - 0x06004000 + 12] == bytes.fromhex('2fe66ef3644dd10e6111611d')
    assert exe[SRV - 0x06004000:SRV - 0x06004000 + 12] == bytes.fromhex('2f862f962fa62fb62fe64f22')
    exe[REQ - 0x06004000:REQ - 0x06004000 + 12] = stub(lab['req'])
    exe[SRV - 0x06004000:SRV - 0x06004000 + 12] = stub(lab['srv'])
    open(os.path.join(OUTD, 'KANJI.FON'), 'wb').write(font)
    open(os.path.join(OUTD, '1ST.BIN'), 'wb').write(exe)
    print('자막 %d개 · 글자 %d자(칸 %d‥%d) · 코드 %d B · 데이터 %d B · 자리 %d / %d B' % (
        len(recs), len(chars), min(slot_of.values()) if slot_of else 0, max(slot_of.values()) if slot_of else 0,
        len(code), len(blob), data_base + len(blob) - REGION, REGION_END - REGION))
    return dict(font=font, exe=exe, code=code, lab=lab, data_base=data_base, slot_of=slot_of, recs=recs)


def labels(src):
    """sh2asm 은 라벨 주소를 안 돌려줘서 같은 규칙으로 다시 셈(명령 2 B, .long 4 B)"""
    lab = {}; pc = CODE
    for raw in src.split('\n'):
        s = raw.split(';')[0].strip()
        if not s: continue
        m = re.match(r'^(\w+):$', s)
        if m: lab[m.group(1)] = pc; continue
        pc += 4 if s.startswith('.long') else 2
    return lab


if __name__ == '__main__':
    build()
