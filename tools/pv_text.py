# -*- coding: utf-8 -*-
"""화면 글 미리보기(게임 글꼴) — 원문(원본 KANJI.FON) | 번역(work/kr/KANJI.FON + work/slot_map.tsv) → work/pv_menu.png
   python tools/pv_text.py   (먼저 tools/subs.py)"""
import os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import subs as B
orig = open(os.path.join(ROOT, 'work', 'iso', 'KANJI.FON'), 'rb').read()
new = open(os.path.join(ROOT, 'work', 'kr', 'KANJI.FON'), 'rb').read()
slot = {l.split('\t')[0]: int(l.split('\t')[1]) for l in open(os.path.join(ROOT, 'work', 'slot_map.tsv'), encoding='utf-8').read().splitlines()}
TX = B.load_trans('text_')


def idx(b2):
    a, b = B.jis_of(b2[0] << 8 | b2[1]); return (a - 0x21) * 94 + b - 0x21


def draw(font, data):
    n = len(data) // 2; im = np.zeros((18, max(n, 1) * 16 + 2, 3), np.uint8)
    for i in range(n):
        g = font[idx(data[i * 2:i * 2 + 2]) * 32:][:32]
        for r in range(16):
            v = int.from_bytes(g[r * 2:r * 2 + 2], 'big')
            for c in range(16):
                if v >> (15 - c) & 1: im[1 + r, 1 + i * 16 + c] = (255, 255, 255)
    return Image.fromarray(im)


rows = [l.split('\t') for l in open(os.path.join(ROOT, 'work', 'trans', 'text_menu.tsv'), encoding='utf-8').read().splitlines()[1:]]
W = 900; H = 24 * len(rows) + 30
out = Image.new('RGB', (W, H), (0, 100, 0)); d = ImageDraw.Draw(out)
F = ImageFont.truetype(r'C:\claude\utils\font\nanum-gothic\NanumGothicBold.ttf', 12)
d.text((4, 4), 'id   원문(게임 글꼴)                      번역(게임 글꼴 · 새 KANJI.FON)', font=F, fill=(255, 255, 0))
y = 26
for k, ja, ko, mx in rows:
    d.text((4, y + 3), k, font=F, fill=(255, 255, 255))
    out.paste(draw(orig, ja.encode('cp932')), (40, y))
    out.paste(draw(new, b''.join(B.enc_char(c, slot) for c in TX[k])), (470, y))
    y += 24
out.resize((W * 2, H * 2), Image.NEAREST).save(os.path.join(ROOT, 'work', 'pv_menu.png'))
