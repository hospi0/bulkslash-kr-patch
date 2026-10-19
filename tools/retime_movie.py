# -*- coding: utf-8 -*-
"""엔딩 자막 시각 다시 잡기 — work/movie/movie_subs.tsv 의 시작·끝을 위스퍼 낱말 시각(work/movie/asr_words.tsv) + 소리 크기로 맞춤.
   1) 낱말 가운데 시점이 원래 [시작, 끝) 안인 낱말만 그 줄 것(앞 줄 꼬리 낱말을 집지 않게) → 첫 낱말 시작·마지막 낱말 끝
   2) 시작은 실제 소리가 커지는 지점으로(첫 낱말 −0.3‥+0.1초, 앞 줄 끝보다 앞으로는 안 감, 20 ms 창 RMS 가 그 영상 말소리 중앙값의 25% 를 넘는 첫 곳)
   3) 앞 줄 끝과 겹치면 앞 줄 끝을 당김. 원래 표는 movie_subs.orig.tsv 로 한 번만 보관.
   python tools/retime_movie.py"""
import os, shutil, sys, wave
import numpy as np
sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, 'work', 'movie')
TSV = os.path.join(D, 'movie_subs.tsv'); ORIG = os.path.join(D, 'movie_subs.orig.tsv')
if not os.path.exists(ORIG):
    shutil.copyfile(TSV, ORIG)
words = {}
for ln in open(os.path.join(D, 'asr_words.tsv'), encoding='utf-8').read().splitlines()[1:]:
    n, a, b, w, k = ln.split('\t'); words.setdefault(n, []).append((float(a), float(b), w))
rms = {}


def energy(n):
    if n not in rms:
        w = wave.open(os.path.join(D, n + '.wav')); x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)
        hop = 320; e = np.sqrt(np.array([np.mean(x[i:i + hop] ** 2) for i in range(0, len(x) - hop, hop)]))
        rms[n] = (e, np.median(e[e > np.percentile(e, 60)]))
    return rms[n]


def onset(n, t, floor=0.0):
    e, ref = energy(n); thr = 0.25 * ref
    lo, hi = max(0, int(max(t - 0.3, floor) * 50)), int((t + 0.1) * 50)
    for i in range(lo, min(hi, len(e))):
        if e[i] > thr: return i / 50
    return t


rows = [ln.split('\t') for ln in open(ORIG, encoding='utf-8').read().split('\n')]
out = [rows[0]]; prev = None; log = []
for r in rows[1:]:
    if len(r) < 5 or r[0].startswith('#'):
        out.append(r); continue
    n, s, e = r[0], float(r[1]), float(r[2])
    W = [w for w in words.get(n, []) if s <= (w[0] + w[1]) / 2 < e]
    floor = float(prev[2]) if prev is not None and prev[0] == n else 0.0
    if W:
        ns, ne = onset(n, W[0][0], floor), max(w[1] for w in W)
    else:
        ns, ne = s, e
    if prev is not None and prev[0] == n and float(prev[2]) > ns - 0.05:
        prev[2] = '%.2f' % max(float(prev[1]) + 0.3, ns - 0.05)
    r = r[:]; r[1], r[2] = '%.2f' % ns, '%.2f' % max(ne, ns + 0.5)
    log.append('%-9s %6.2f→%6.2f  %6.2f→%6.2f  %s' % (n, s, ns, e, float(r[2]), r[4][:24]))
    out.append(r); prev = r
open(TSV, 'w', encoding='utf-8', newline='\n').write('\n'.join('\t'.join(r) for r in out))
print('\n'.join(log))
