# -*- coding: utf-8 -*-
"""소닉 팀 PRS 압축 (0.BIN 0x06006240 근처 해제 루틴과 같은 형식) — 풀기·싸기 (2026-10-10)
   깃발 비트는 바이트 단위, 낮은 비트부터 하나씩:
     1            → 문자 그대로 1바이트
     0 0 b b      → 짧은 복사: 길이 bb+2, 거리 = 다음 바이트 − 256
     0 1          → 긴 복사: u16(LE) — 위 13비트 거리(−8192‥−1), 아래 3비트 길이−2 (0 이면 다음 바이트 = 길이−1)
                    u16 = 0 이면 끝"""


class _Bits:
    def __init__(s, d): s.d = d; s.i = 0; s.f = 0; s.n = 0
    def bit(s):
        if s.n == 0: s.f = s.d[s.i]; s.i += 1; s.n = 8
        b = s.f & 1; s.f >>= 1; s.n -= 1; return b
    def byte(s): v = s.d[s.i]; s.i += 1; return v


def decompress(d):
    r = _Bits(d); out = bytearray()
    while True:
        if r.bit():
            out.append(r.byte()); continue
        if r.bit():
            lo = r.byte(); hi = r.byte(); w = lo | hi << 8
            if w == 0: break
            off = (w >> 3) - 8192; n = w & 7
            n = r.byte() + 1 if n == 0 else n + 2
        else:
            n = (r.bit() << 1 | r.bit()) + 2; off = r.byte() - 256
        for _ in range(n): out.append(out[off])
    return bytes(out), r.i


class _W:
    def __init__(s): s.out = bytearray(); s.fpos = None; s.nb = 8
    def bit(s, b):
        if s.nb == 8: s.fpos = len(s.out); s.out.append(0); s.nb = 0
        s.out[s.fpos] |= b << s.nb; s.nb += 1
    def byte(s, v): s.out.append(v)


def compress(d, chain=512):
    """최적 파싱(비트 수 최소 DP, 뒤에서 앞으로). 결과는 decompress 로 검산할 것"""
    n = len(d); INF = 1 << 60
    heads = {}; cands = [None] * n
    for i in range(n):
        lst = []
        if i + 1 < n:
            key = d[i:i + 2]; prev = heads.get(key, [])
            best_len = 1
            for j in reversed(prev[-chain:]):
                dist = i - j
                if dist > 8191: break
                L = 2
                while L < 256 and i + L < n and d[j + L] == d[i + L]: L += 1
                if L > best_len or (dist <= 256 and L <= 5 and not any(x[1] <= 256 for x in lst)):
                    lst.append((L, dist)); best_len = max(best_len, L)
            prev.append(i); heads[key] = prev
        cands[i] = lst
    cost = [INF] * (n + 1); cost[n] = 0; how = [None] * (n + 1)
    for i in range(n - 1, -1, -1):
        c = 9 + cost[i + 1]; h = (1, 0)
        for L, dist in cands[i]:
            for l in (list(range(2, min(L, 9) + 1)) + ([10, L] if L >= 10 else [])):
                if dist <= 256 and l <= 5: b = 12
                elif l >= 3 and l <= 9: b = 18
                elif l >= 10: b = 26
                else: continue
                v = b + cost[i + l]
                if v < c: c = v; h = (l, dist)
        cost[i] = c; how[i] = h
    w = _W(); i = 0
    while i < n:
        L, dist = how[i]
        if L == 1:
            w.bit(1); w.byte(d[i])
        elif dist <= 256 and L <= 5:
            w.bit(0); w.bit(0); w.bit((L - 2) >> 1 & 1); w.bit((L - 2) & 1); w.byte(256 - dist)
        else:
            v = (8192 - dist) << 3
            if L <= 9: v |= L - 2; w.bit(0); w.bit(1); w.byte(v & 0xFF); w.byte(v >> 8)
            else: w.bit(0); w.bit(1); w.byte(v & 0xFF); w.byte(v >> 8); w.byte(L - 1)
        i += L
    w.bit(0); w.bit(1); w.byte(0); w.byte(0)
    return bytes(w.out)


def compress_greedy(d):
    """탐욕 LZ(해시 사슬) — 옛 판"""
    w = _W(); i = 0; n = len(d); heads = {}
    while i < n:
        best = (0, 0)
        if i + 2 < n:
            key = d[i:i + 3]
            for j in reversed(heads.get(key, [])[-64:]):
                if i - j > 8191: break
                L = 0
                while L < 256 and i + L < n and d[j + L] == d[i + L]: L += 1
                if L > best[0]: best = (L, i - j)
                if L == 256: break
        L, dist = best
        if L >= 2 and dist <= 256 and L <= 5:
            w.bit(0); w.bit(0); w.bit((L - 2) >> 1 & 1); w.bit((L - 2) & 1); w.byte(256 - dist)
        elif L >= 3:
            v = ((8192 - dist) << 3)
            if L <= 9: v |= L - 2; w.bit(0); w.bit(1); w.byte(v & 0xFF); w.byte(v >> 8)
            else: w.bit(0); w.bit(1); w.byte(v & 0xFF); w.byte(v >> 8); w.byte(L - 1)
        else:
            L = 1; w.bit(1); w.byte(d[i])
        for k in range(i, min(i + L, n - 2)):
            heads.setdefault(d[k:k + 3], []).append(k)
        i += L
    w.bit(0); w.bit(1); w.byte(0); w.byte(0)
    return bytes(w.out)
