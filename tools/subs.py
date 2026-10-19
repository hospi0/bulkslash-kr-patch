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
HFONT = ImageFont.truetype(r'C:\claude\utils\font\Galmuri-v2.40.3\Galmuri11-Condensed.ttf', 12)   # 반 칸 글자(숫자·!?,.) — ★원래 크기 12 px 만(15 px 로 키우면 비트맵 줄이 빠져 숫자가 깨짐, 2026-10-19) · 폭 4 px 라 테두리·여백이 반 칸 안에(Galmuri14 숫자 8 px 는 «2개»가 «27H»로 붙어 보임, 실기 2026-10-19)

# ---- 주소 ----
FONT = 0x00200000
REGION, REGION_END = FONT + 658 * 32, FONT + 1410 * 32          # JIS 0x28‥0x2F 행(빈 글자)
STATE = REGION                                                   # 48 B: +0 켜짐 +4 지금 시각 +8 끝 +12 다음 쪽 +16 시작 VBlank +20 VBlank 수 +24 시계 방식 +28 지금 쪽 +32 그린 지도 칸 수 +36 아래 자리 강제
CODE = REGION + 48
VMAP = 0x25E7C000                                                # NBG0 지도 VRAM(메인 루프가 MAPBUF 를 여기로 복사)
MAPBUF = 0x060B7000; ROW = 1; ROW2 = 3; COLS = 40               # 기본 = 지도 1‥4행(화면 y 8‥40 — 3행 이하면 STAGE CLEAR 스프라이트에 가림) · 2행에 보스 체력 바가 있으면 3‥6행(바 바로 밑) — 사용자 2026-10-19
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
    """반 칸(8 px) 글자 — 좁은 것만. «~» 같은 넓은 반각은 한 칸"""
    return ch in '0123456789!?,.:;'


# ============ 글꼴 칸 ============
def used_codes():
    """원문 어디서든 쓰일 수 있는 SJIS 2바이트 코드(넉넉히 = 안전) — 이 칸은 안 건드린다"""
    # 실제 문장만: 가나가 섞이거나(문장) 전각 공백으로 칸 맞춘(스태프 롤·메뉴) 3자 이상 연속. 데이터 바이트가 우연히 SJIS 로 읽히는 건 뺀다.
    pat = re.compile(rb'(?:[\x81-\x9f\xe0-\xef][\x40-\x7e\x80-\xfc]){3,}')
    out = set()
    for fn in glob.glob(os.path.join(ISO, '*')):
        b = os.path.basename(fn)
        if b.startswith('VC') or b.endswith('.CPK'):
            continue
        d = open(fn, 'rb').read()
        for m in pat.finditer(d):
            s = m.group()
            try: t = s.decode('cp932')
            except UnicodeDecodeError: continue
            if not re.search('[ぁ-ヿ　]', t): continue
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
    if half(ch):
        dr.text((1, 13), ch, font=HFONT, fill=255, anchor='ls')          # 한글과 기준선(13행) 맞춤
    else:
        dr.text((8, 8), ch, font=KFONT, fill=255, anchor='mm')
    a = np.array(im) > 0
    # 테두리 1 px 자리: 잉크를 1‥14행·1‥14열(반 칸은 1‥6열) 안으로 — 0행에 붙으면 위 테두리가 잘림(실기 2026-10-19)
    ys, xs = np.nonzero(a)
    if len(ys):
        dy = max(0, 1 - ys.min()) - max(0, ys.max() - 14)
        dx = max(0, 1 - xs.min()) - max(0, xs.max() - (6 if half(ch) else 14))
        a = np.roll(np.roll(a, dy, 0), dx, 1)
        ys, xs = np.nonzero(a)
        assert 1 <= xs.min() and xs.max() <= (6 if half(ch) else 14), ('글자가 칸을 넘음', ch)
    return b''.join(struct.pack('>H', int(''.join('1' if x else '0' for x in r), 2)) for r in a)


# ============ 번역 → 쪽 ============
def load_trans(prefix='', raw=False):
    """prefix '' = 음성 자막(text_*.tsv 빼고) · 'text_' = 화면 글(브리핑·합류) · raw = 부호 뒤 공백 안 지움(내보내기용)"""
    T = {}
    for fn in sorted(glob.glob(os.path.join(ROOT, 'work', 'trans', prefix + '*.tsv'))):
        if not prefix and os.path.basename(fn).startswith('text_'): continue
        for ln in open(fn, encoding='utf-8').read().splitlines()[1:]:
            p = ln.split('\t')
            if len(p) >= 3 and p[2].strip():
                T[p[0]] = p[2].strip() if raw else squeeze(p[2].strip())
    return T


def width(s):
    return sum(1 if half(c) else 2 for c in s)


def pieces_of(para):
    """(조각, 앞과 띄어 씀?) — 공백과 «부호 뒤»가 줄바꿈 자리(부호 뒤 공백은 squeeze 가 지웠으니). 가운뎃점은 안 끊음."""
    out = []
    for word in para.split(' '):
        for k, p in enumerate(re.findall('[^' + re.escape(BRK) + ']*[' + re.escape(BRK) + ']+|[^' + re.escape(BRK) + ']+', word)):
            out.append((p, k == 0))
    return out


def lines_of(t, maxw=COLS - 2):
    """줄 나눔(번역은 안 깎음). ⛔한 조각이 줄보다 길면 글자 단위로 자르지 않고 멈춤 — 사람이 고친다."""
    out, cur = [], ''
    for p, sp in pieces_of(t):
        assert width(p) <= maxw, ('한 낱말이 줄 폭을 넘음 — 번역을 고칠 것', p, t)
        cand = (cur + (' ' if sp else '') + p) if cur else p
        if width(cand) <= maxw: cur = cand
        else: out.append(cur); cur = p
    if cur: out.append(cur)
    return out


def pages_of(t):
    """« | » = 쪽 나눔(화자 바뀜 등). 그 안은 2줄씩·한 쪽 글자 32개까지."""
    pages = []
    for part in t.split('|'):
        ls = lines_of(part.strip())
        while ls:
            pg = ls[:2]
            while sum(len(l.replace(' ', '')) for l in pg) > MAXGLYPH and len(pg) > 1:
                pg = pg[:1]
            pages.append(pg); ls = ls[len(pg):]
    return pages


# ============ 화면 글(브리핑·합류) — 게임 글 루틴은 2바이트씩 찍고 N자마다 기계적으로 줄바꿈 ============
SEL_DEMO_TAB = 0x0602A53C; NBRIEF = 7; BRIEF_W = 10       # 브리핑 본문 포인터 7칸(본문 NUL 뒤에 꼬리 문장이 붙어 있어야 함)
JOIN_W, JOIN_LINES = 16, 4                                 # 합류 대사창 16자 × 4줄(원문 시가 64칸 꽉 채움)
JSTREAM_SIG = bytes([0x14, 0x0C, 0x0B, 0x00, 0x10, 0x05, 0x0B, 0x00])   # 합류 드러냄 열 시작(레오네 20·쉼12·11 / 리라 16·5·11) — 원문 글자 수와 일치
BRK = PUNCT.replace('・', '').replace('·', '')                # 줄바꿈 자리 부호(가운뎃점은 Ｍ・Ｉ・Ｓ・Ｓ 안이라 뺌)
FW = {c: chr(ord(c) + 0xFEE0) for c in '!"#$%&\'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~'}


def sjis_of_slot(s):
    a, b = 0x21 + s // 94, 0x21 + s % 94
    c1 = (a + 1) // 2 + (0x70 if a <= 0x5E else 0xB0)
    c2 = b + (0x1F if b <= 0x5F else 0x20) if a % 2 else b + 0x7E
    return bytes([c1, c2])


def enc_char(ch, slot_of):
    if ch == ' ': return b'\x81\x40'
    if ch in slot_of and not half(ch) and '가' <= ch <= '힣': return sjis_of_slot(slot_of[ch])
    b = FW.get(ch, ch).encode('cp932'); assert len(b) == 2, (ch, b); return b


def wrap_text(t, w):
    """낱말 단위로 w 자 줄을 만들고 줄 끝은 전각 공백으로 채움(원문 시와 같은 방식). '|' = 강제 줄바꿈. 줄 목록 반환."""
    lines = []
    for para in t.split('|'):
        pieces = pieces_of(para)
        cur = ''
        for p, sp in pieces:
            assert len(p) <= w, ('한 낱말이 줄 폭을 넘음 — 번역을 고칠 것', p, t)   # ⛔글자 단위로 자르지 않음
            cand = (cur + (' ' if sp else '') + p) if cur else p
            if len(cand) <= w: cur = cand
            else: lines.append(cur); cur = p
        lines.append(cur)
    return lines


def enc_text(t, w, slot_of):
    ls = wrap_text(t, w)
    body = ''.join(l.ljust(w) for l in ls[:-1]) + ls[-1]
    return b''.join(enc_char(c, slot_of) for c in body), ls


def text_patches(slot_of, base):
    """화면 글 묶음(본 주소 base 부터 놓을 바이트) + 파일별 포인터 덮기 목록"""
    TX = load_trans('text_')
    blob = bytearray(); ptr = {}; report = []
    def put(b):
        nonlocal blob
        if len(blob) % 2: blob += b'\0'
        a = base + len(blob); blob += b; return a
    for i in range(NBRIEF):
        m, ml = enc_text(TX['B%dm' % i], BRIEF_W, slot_of); t, tl = enc_text(TX['B%dt' % i], BRIEF_W, slot_of)
        ptr['B%d' % i] = put(m + b'\0' + t + b'\0'); report.append(('B%d' % i, ml + ['—'] + tl))
    streams = []
    for i in range(8):
        raw = TX['J%d' % i]
        cuts = [len(raw[:k].replace(' ', '').replace('^', '')) for k, ch in enumerate(raw) if ch == '^']   # 쉼 자리 = 앞 글자 수(공백 빼고)
        t = squeeze(raw.replace('^', ''))
        j, jl = enc_text(t, JOIN_W, slot_of)
        assert len(jl) <= JOIN_LINES, ('합류 대사 4줄 넘음', i, jl)
        ptr['J%d' % i] = put(j + b'\0'); report.append(('J%d' % i, jl))
        if i < 7:   # 드러냄 열 [n, 쉼, n, 쉼 … 0]: 쉼은 원래 값, n = 실제로 드러낼 칸 수(줄 끝 채움 포함) — 원문 글자 수 그대로면 끝이 잘림(실기 2026-10-19)
            n_cells = len(j) // 2; ends = []; seen = 0
            for pos in range(n_cells):
                if j[pos * 2:pos * 2 + 2] != b'\x81\x40': seen += 1
                if len(ends) < len(cuts) and seen == cuts[len(ends)] and j[pos * 2:pos * 2 + 2] != b'\x81\x40': ends.append(pos + 1)
            assert len(ends) == len(cuts), ('쉼 자리 못 찾음', i)
            streams.append([b - a_ for a_, b in zip([0] + ends, ends + [n_cells])])
    files = {}
    f = bytearray(open(os.path.join(ISO, 'SEL_DEMO.ALL'), 'rb').read())
    s, c, a, z = struct.unpack_from('>4I', f, 0); o = s * 2048 + SEL_DEMO_TAB - a
    orig = [0x0602B790, 0x0602B86C, 0x0602B94C, 0x0602B9F8, 0x0602BAF8, 0x0602BBF0, 0x0602BCEC]
    assert list(struct.unpack_from('>7I', f, o)) == orig, 'SEL_DEMO 브리핑 표가 예상과 다름'
    struct.pack_into('>7I', f, o, *[ptr['B%d' % i] for i in range(NBRIEF)]); files['SEL_DEMO.ALL'] = f
    j6 = 'ワタシのチカラは…アナタと共に…'.encode('cp932') + b'\0'
    for n in range(1, 8):
        fn = 'ALL.ST%d' % n; f = bytearray(open(os.path.join(ISO, fn), 'rb').read())
        s, c, a, z = struct.unpack_from('>4I', f, 0); po = s * 2048
        sa = a + f.index(j6, po) - po
        refs = [k for k in range(po, po + c * 2048, 4) if struct.unpack_from('>I', f, k)[0] == sa]
        assert len(refs) == 1, (fn, refs); tb = refs[0] - 6 * 4
        olds = struct.unpack_from('>8I', f, tb)
        assert all(f[po + p - a:po + p - a + 2] != b'\0\0' for p in olds), (fn, '표 확인')
        struct.pack_into('>8I', f, tb, *[ptr['J%d' % i] for i in range(8)])
        # 합류 대사 드러냄 열(음성 맞춤): 열 시작 = JSTREAM_SIG, 그 주소를 가리키는 포인터 7칸 표
        sa2 = a + f.index(JSTREAM_SIG, po) - po
        pt = [k for k in range(po, po + c * 2048, 4) if struct.unpack_from('>I', f, k)[0] == sa2]
        assert len(pt) == 1, (fn, '드러냄 표'); pt = pt[0]
        for q in range(7):
            o0 = struct.unpack_from('>I', f, pt + 4 * q)[0] - a + po; o = o0; orig = []
            while f[o]: orig.append(f[o]); o += 1
            assert len(orig) == 2 * len(streams[q]) - 1, (fn, q, '쉼 수가 원문과 다름 — ^ 개수 확인', orig, streams[q])
            new = []
            for zi, sz in enumerate(streams[q]):
                assert 0 < sz < 256, (q, sz); new.append(sz)
                if zi < len(streams[q]) - 1: new.append(orig[2 * zi + 1])
            f[o0:o0 + len(new)] = bytes(new)
        files[fn] = f
    # 메뉴·저장 문구(TITLE.ALL): 번역문을 옮기고 그 문자열을 가리키는 포인터를 전부 바꿈. 줄바꿈 없음 · max = 칸 수 상한(라벨 검은 바탕 = 글자 수)
    f = bytearray(open(os.path.join(ISO, 'TITLE.ALL'), 'rb').read())
    s, c, a, z = struct.unpack_from('>4I', f, 0); po = s * 2048
    mx = {ln.split('\t')[0]: int(ln.split('\t')[3]) for ln in open(os.path.join(ROOT, 'work', 'trans', 'text_menu.tsv'), encoding='utf-8').read().splitlines()[1:]}
    ja = {ln.split('\t')[0]: ln.split('\t')[1] for ln in open(os.path.join(ROOT, 'work', 'trans', 'text_menu.tsv'), encoding='utf-8').read().splitlines()[1:]}
    for k in sorted(mx):
        ob = ja[k].encode('cp932') + b'\0'
        i = f.find(ob, po); assert i > 0 and f.find(ob, i + 1) < 0, (k, '원문 위치')
        oa = a + i - po
        refs = [q for q in range(po, po + c * 2048, 4) if struct.unpack_from('>I', f, q)[0] == oa]
        assert refs, (k, '포인터 없음')
        t = TX[k]; body = b''.join(enc_char(ch, slot_of) for ch in t)
        assert len(body) // 2 <= mx[k], ('메뉴 문구 칸 수 넘음', k, t, len(body) // 2, mx[k])
        na = put(body + b'\0'); report.append((k, [t]))
        for q in refs: struct.pack_into('>I', f, q, na)
    files['TITLE.ALL'] = f
    return bytes(blob), files, report


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
VBL_FIXED = 0x00205304                                           # ★VBlank 콜백 주소 고정 — 예전 빌드 스테이트에 이 주소가 박혀 있다(옮기면 스테이트 불러올 때 멈춤)


def hook_asm(data_base, vblpad=0):
    L = lambda v: '#0x%08X' % v
    VBLPAD = ('  nop' + chr(10)) * vblpad
    return f'''
{VBLPAD}vbl:                        ; SGL 사용자 VBlank 콜백(빈 칸일 때만 끼움) — r0·r1 만
  mov.l #{STATE + 20:#x},r0
  mov.l @r0,r1
  add #1,r1
  rts
  mov.l r1,@r0

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
  mov #0,r1
  mov.l r1,@(28,r8)
  mov.l r1,@(32,r8)
  mov.l r1,@(36,r8)
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
  .pool                     ; 앞 리터럴(코드가 1 KB 넘어 끝 풀까지 못 닿음)

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
  bsr keep
  nop
  bsr sync_vram
  nop
  bra fr_out
  nop
fr_clear:
  bsr clear
  nop
  bsr stage_ok              ; 스테이지 화면에서 끝났을 때만 VRAM 의 우리 칸도 지움
  nop
  bf fr_out
  bsr sync_vram
  nop
fr_out:
  lds.l @r15+,pr
  rts
  nop

clear:                      ; 끄기 + 우리 지도 칸만 지움
  mov.l {L(STATE)},r1
  mov #0,r0
  mov.l r0,@r1
clear_map:                  ; 두 후보 자리(1‥7행)에서 우리 칸만 지움
  mov.l {L(MAPBUF + min(ROW, ROW2) * 128)},r1
  mov #{abs(ROW2 - ROW) + 4},r2
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

sync_vram:                  ; 1‥6행: 버퍼나 VRAM 한쪽이 우리 칸인데 다르면 버퍼 값을 VRAM 에 바로 씀 — 게임오버 화면은 메인 루프 지도 복사(0x06034830)를 안 부름
  mov.l {L(MAPBUF + min(ROW, ROW2) * 128)},r1
  mov.l {L(VMAP - MAPBUF)},r4
  mov #{abs(ROW2 - ROW) + 4},r2
  mov.l #0xFF80,r6
  mov.l {L(MAPV)},r7
sv_row:
  mov #{COLS},r3
  mov r1,r5
sv_col:
  mov.w @r5,r11
  mov r5,r10
  add r4,r10
  mov.w @r10,r12
  cmp/eq r11,r12
  bt sv_next
  mov r11,r0
  and r6,r0
  cmp/eq r7,r0
  bt sv_w
  mov r12,r0
  and r6,r0
  cmp/eq r7,r0
  bf sv_next
sv_w:
  mov.w r11,@r10
sv_next:
  dt r3
  bf/s sv_col
  add #2,r5
  mov.l #128,r0
  dt r2
  bf/s sv_row
  add r0,r1
  rts
  nop

rows_free:                  ; r1 = 지도 행 주소 → T=1: 4행이 모두 0 이거나 우리 것
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
  mov.l r9,@(28,r8)         ; 지금 쪽(다시 그리기용)
  bsr place_page
  nop
  mov.l r9,@(12,r8)
sp_out:
  lds.l @r15+,pr
  rts
  nop

keep:                       ; 지금 쪽이 지도에서 지워졌으면(게임이 구역을 통째로 비움 — 숫자 그림 지울 때) 다시 그림
  sts.l pr,@-r15
  mov.l {L(STATE)},r8
  mov.l @(28,r8),r9
  tst r9,r9
  bt kp_out
  bsr count_ours            ; 그린 칸이 하나라도 사라졌으면(컨티뉴 화면은 체력 바 자리 2행을 매 프레임 0 으로) 아래 자리로 옮겨 다시
  nop
  mov.l @(32,r8),r1
  cmp/eq r1,r0
  bt kp_out
  cmp/pl r1                 ; 그렸다가 지워진 경우만 아래 자리 강제(못 그렸던 쪽(−1)은 같은 규칙으로 다시 시도)
  bf kp_place
  mov #1,r0
  mov.l r0,@(36,r8)
kp_place:
  bsr place_page
  nop
kp_out:
  lds.l @r15+,pr
  rts
  nop

count_ours:                 ; r0 = 1‥6행의 우리 칸 수
  mov #0,r4
  mov.l {L(MAPBUF + min(ROW, ROW2) * 128)},r1
  mov #{abs(ROW2 - ROW) + 4},r2
  mov.l #0xFF80,r6
  mov.l {L(MAPV)},r7
ho_row:
  mov #{COLS},r3
  mov r1,r5
ho_col:
  mov.w @r5,r0
  and r6,r0
  cmp/eq r7,r0
  bf ho_no
  add #1,r4
ho_no:
  dt r3
  bf/s ho_col
  add #2,r5
  mov.l #128,r0
  dt r2
  bf/s ho_row
  add r0,r1
  rts
  mov r4,r0

place_page:                 ; r9 = 쪽 항목 → 비었으면 두 자리 중 하나에 그림 · r9 = 끝(0) 뒤
  sts.l pr,@-r15
  bsr clear_map
  nop
  mov.l {L(STATE)},r1
  mov.l @(36,r1),r0
  tst r0,r0
  bf pp_try2
  mov.l {L(MAPBUF + ROW * 128)},r1
  bsr rows_free
  nop
  bt pp_row1
pp_try2:
  mov.l {L(MAPBUF + ROW2 * 128)},r1
  bsr rows_free
  nop
  bf pp_skip
  mov.l {L(MAPBUF + ROW2 * 128 - 256)},r11
  bra pp_draw
  nop
pp_row1:
  mov.l {L(MAPBUF + ROW * 128 - 256)},r11
pp_draw:
  bsr draw_page
  nop
  bra pp_out
  nop
pp_skip:
  mov.l {L(STATE)},r1
  mov #-1,r0
  mov.l r0,@(32,r1)          ; 못 그림 → keep 이 계속 다시 시도
pp_sk:
  mov.w @r9+,r0
  extu.w r0,r0
  tst r0,r0
  bf pp_sk
pp_out:
  lds.l @r15+,pr
  rts
  nop


draw_page:                  ; r9 = 항목 → 끝(0) 뒤로
  sts.l pr,@-r15
  mov #0,r10                ; r11 = 첫 줄 지도 주소 − 256(step 이 정함)
  mov #0,r14                ; 그린 지도 칸 수
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
  add #2,r14
  bra dp_next
  add #4,r12
dp_half:
  add #2,r12
dp_next:
  add #2,r14
  bra dp_loop
  add #1,r10
dp_out:
  mov.l {L(STATE)},r1
  mov.l r14,@(32,r1)
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
    # 같은 소리(같은 묶음·같은 섹터) 번호에 번역 넘겨주기 — 내보낸 표는 첫 번호만 싣는다(tools/export_tsv.py)
    tab = [ln.split('\t') for ln in open(os.path.join(ROOT, 'work', 'vc_table.tsv'), encoding='utf-8').read().splitlines()[1:]]
    sec = {p[0]: (p[0].split('_')[0], p[1]) for p in tab}
    for k in list(T):
        for n, key in sec.items():
            if key == sec.get(k) and n not in T: T[n] = T[k]
    # 글자 → 칸
    TX = load_trans('text_')
    chars = sorted(set(c for t in list(T.values()) + list(TX.values()) for c in t if c not in ' |^'))
    chars = [c for c in chars if '가' <= c <= '힣' or any(c in t for t in T.values())]   # 화면 글의 부호는 원래 전각 글자 그대로
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
    vblpad = (VBL_FIXED - labels(hook_asm(0))['vbl']) // 2
    assert vblpad >= 0, ('VBlank 함수 앞 코드가 고정 주소를 넘음', hex(labels(hook_asm(0))['vbl']))
    code = sh2asm.assemble(hook_asm(0, vblpad) + 'banks:\n  .long 0\n', CODE)
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
    if len(blob) % 2: blob += b'\0'
    tblob, tfiles, treport = text_patches(slot_of, data_base + len(blob))
    blob += tblob
    src = hook_asm(data_base, vblpad).replace('#banks', '#0x%08X' % data_base)
    code = sh2asm.assemble(src, CODE)
    assert labels(src)['vbl'] == VBL_FIXED, hex(labels(src)['vbl'])
    assert CODE + len(code) <= data_base, '코드가 데이터 자리를 넘음'
    assert data_base + len(blob) <= REGION_END, ('자리 넘침', hex(data_base + len(blob)), hex(REGION_END))
    font[STATE - FONT:STATE - FONT + 48] = b'\0' * 48
    font[CODE - FONT:CODE - FONT + len(code)] = code
    font[data_base - FONT:data_base - FONT + len(blob)] = blob
    lab = labels(src)
    # 1ST.BIN 덮기(덮이는 원래 바이트 검사)
    assert exe[REQ - 0x06004000:REQ - 0x06004000 + 12] == bytes.fromhex('2fe66ef3644dd10e6111611d')
    assert exe[SRV - 0x06004000:SRV - 0x06004000 + 12] == bytes.fromhex('2f862f962fa62fb62fe64f22')
    exe[REQ - 0x06004000:REQ - 0x06004000 + 12] = stub(lab['req'])
    exe[SRV - 0x06004000:SRV - 0x06004000 + 12] = stub(lab['srv'])
    open(os.path.join(OUTD, 'KANJI.FON'), 'wb').write(font)
    with open(os.path.join(ROOT, 'work', 'slot_map.tsv'), 'w', encoding='utf-8') as fo:   # 미리보기·검산용 글자 → 칸
        fo.write(''.join(c + chr(9) + str(n) + chr(10) for c, n in slot_of.items()))
    open(os.path.join(OUTD, '1ST.BIN'), 'wb').write(exe)
    for fn, d in tfiles.items():
        open(os.path.join(OUTD, fn), 'wb').write(d)
    with open(os.path.join(ROOT, 'work', 'text_layout.txt'), 'w', encoding='utf-8') as fo:
        for k, ls in treport:
            fo.write('[%s]\n' % k + '\n'.join('  |' + l + '|' for l in ls) + '\n')
    print('화면 글 %d B(브리핑 %d·합류 8) → work/text_layout.txt' % (len(tblob), NBRIEF))
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
