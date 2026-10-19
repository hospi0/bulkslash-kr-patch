# -*- coding: utf-8 -*-
"""작은 SH-2(빅 엔디언) 흉내기 — 우리가 넣는 훅 코드를 PC 에서 돌려 결과를 검산한다 (2026-10-10).
   메모리는 dict 구역 [(시작, bytearray)…]. 지원 명령은 훅이 쓰는 것만. 모르는 명령이면 멈춤."""
import struct

M32 = 0xFFFFFFFF


def s8(v): v &= 0xFF; return v - 0x100 if v & 0x80 else v
def s16(v): v &= 0xFFFF; return v - 0x10000 if v & 0x8000 else v
def s32(v): v &= M32; return v - (1 << 32) if v & 0x80000000 else v


class Mem:
    def __init__(s): s.regions = []
    def add(s, base, size, data=None):
        b = bytearray(size)
        if data: b[:len(data)] = data
        s.regions.append((base & 0x0FFFFFFF, b)); return b
    def _f(s, a):
        a &= 0x0FFFFFFF
        for base, b in s.regions:
            if base <= a < base + len(b): return b, a - base
        raise KeyError('주소 0x%08X' % a)
    def r8(s, a): b, o = s._f(a); return b[o]
    def r16(s, a):
        assert a % 2 == 0, '정렬 0x%X' % a; b, o = s._f(a); return b[o] << 8 | b[o + 1]
    def r32(s, a):
        assert a % 4 == 0, '정렬 0x%X' % a; b, o = s._f(a); return struct.unpack_from('>I', b, o)[0]
    def w8(s, a, v): b, o = s._f(a); b[o] = v & 0xFF
    def w16(s, a, v):
        assert a % 2 == 0, '정렬 0x%X' % a; b, o = s._f(a); b[o] = v >> 8 & 0xFF; b[o + 1] = v & 0xFF
    def w32(s, a, v):
        assert a % 4 == 0, '정렬 0x%X' % a; b, o = s._f(a); struct.pack_into('>I', b, o, v & M32)


def run(mem, pc, regs=None, stop=0xDEAD0000, calls=None, limit=5_000_000):
    """pc 부터 실행, stop 주소로 돌아오면 끝. calls = {주소: 파이썬 함수(r, mem)} — JSR/JMP 대상 흉내."""
    r = [0] * 16; r[15] = 0x060FF000
    if regs: r[:len(regs)] = regs
    pr = stop; T = 0; macl = 0; delay = None; n = 0
    while True:
        n += 1
        if n > limit: raise RuntimeError('너무 오래 돔 pc=0x%08X' % pc)
        if delay is None and pc in (calls or {}):
            calls[pc](r, mem); pc = pr; continue
        if delay is None and pc == stop:
            return r, n
        op = mem.r16(pc); nn = op >> 8 & 15; m = op >> 4 & 15; npc = pc + 2; d = None
        h = op >> 12; lo4 = op & 15; lo8 = op & 0xFF
        if op == 0x0009: pass
        elif op == 0x000B: d = pr
        elif op & 0xF0FF == 0x400B: d = r[nn]; pr = pc + 4
        elif op & 0xF0FF == 0x402B: d = r[nn]
        elif op & 0xF0FF == 0x4022: r[nn] = (r[nn] - 4) & M32; mem.w32(r[nn], pr)
        elif op & 0xF0FF == 0x4026: pr = mem.r32(r[nn]); r[nn] = (r[nn] + 4) & M32
        elif op & 0xF0FF == 0x001A: r[nn] = macl
        elif h == 0xD: r[nn] = mem.r32(((pc + 4) & ~3) + lo8 * 4)
        elif h == 0x9: r[nn] = s16(mem.r16(pc + 4 + lo8 * 2)) & M32
        elif h == 0xE: r[nn] = s8(op) & M32
        elif h == 0x7: r[nn] = (r[nn] + s8(op)) & M32
        elif h == 0x2:
            if lo4 == 0: mem.w8(r[nn], r[m])
            elif lo4 == 1: mem.w16(r[nn], r[m])
            elif lo4 == 2: mem.w32(r[nn], r[m])
            elif lo4 == 6: r[nn] = (r[nn] - 4) & M32; mem.w32(r[nn], r[m])
            elif lo4 == 8: T = int(r[nn] & r[m] == 0)
            elif lo4 == 9: r[nn] &= r[m]
            elif lo4 == 0xA: r[nn] ^= r[m]
            elif lo4 == 0xB: r[nn] |= r[m]
            else: raise SystemExit('모름 %04X @%08X' % (op, pc))
        elif h == 0x6:
            if lo4 == 0: r[nn] = s8(mem.r8(r[m])) & M32
            elif lo4 == 1: r[nn] = s16(mem.r16(r[m])) & M32
            elif lo4 == 2: r[nn] = mem.r32(r[m])
            elif lo4 == 3: r[nn] = r[m]
            elif lo4 == 4: v = s8(mem.r8(r[m])) & M32; r[m] = (r[m] + 1) & M32; r[nn] = v
            elif lo4 == 5: v = s16(mem.r16(r[m])) & M32; r[m] = (r[m] + 2) & M32; r[nn] = v
            elif lo4 == 6: v = mem.r32(r[m]); r[m] = (r[m] + 4) & M32; r[nn] = v
            elif lo4 == 0xC: r[nn] = r[m] & 0xFF
            elif lo4 == 0xD: r[nn] = r[m] & 0xFFFF
            elif lo4 == 0xB: r[nn] = (-r[m]) & M32
            elif lo4 == 0x7: r[nn] = (~r[m]) & M32
            else: raise SystemExit('모름 %04X @%08X' % (op, pc))
        elif h == 0x3:
            if lo4 == 0: T = int(r[nn] == r[m])
            elif lo4 == 2: T = int(r[nn] >= r[m])
            elif lo4 == 3: T = int(s32(r[nn]) >= s32(r[m]))
            elif lo4 == 6: T = int(r[nn] > r[m])
            elif lo4 == 7: T = int(s32(r[nn]) > s32(r[m]))
            elif lo4 == 8: r[nn] = (r[nn] - r[m]) & M32
            elif lo4 == 0xC: r[nn] = (r[nn] + r[m]) & M32
            else: raise SystemExit('모름 %04X @%08X' % (op, pc))
        elif h == 0x4:
            if lo8 == 0x00: T = r[nn] >> 31; r[nn] = (r[nn] << 1) & M32
            elif lo8 == 0x01: T = r[nn] & 1; r[nn] >>= 1
            elif lo8 == 0x08: r[nn] = (r[nn] << 2) & M32
            elif lo8 == 0x09: r[nn] >>= 2
            elif lo8 == 0x18: r[nn] = (r[nn] << 8) & M32
            elif lo8 == 0x19: r[nn] >>= 8
            elif lo8 == 0x28: r[nn] = (r[nn] << 16) & M32
            elif lo8 == 0x29: r[nn] >>= 16
            elif lo8 == 0x10: r[nn] = (r[nn] - 1) & M32; T = int(r[nn] == 0)
            elif lo8 == 0x11: T = int(s32(r[nn]) >= 0)
            elif lo8 == 0x15: T = int(s32(r[nn]) > 0)
            else: raise SystemExit('모름 %04X @%08X' % (op, pc))
        elif h == 0x0:
            if lo4 == 0x7: macl = (s32(r[nn]) * s32(r[m])) & M32
            elif lo4 == 0xC: r[nn] = s8(mem.r8((r[0] + r[m]) & M32)) & M32
            elif lo4 == 0xD: r[nn] = s16(mem.r16((r[0] + r[m]) & M32)) & M32
            elif lo4 == 0xE: r[nn] = mem.r32((r[0] + r[m]) & M32)
            elif lo4 == 0x4: mem.w8((r[0] + r[nn]) & M32, r[m])
            elif lo4 == 0x5: mem.w16((r[0] + r[nn]) & M32, r[m])
            elif lo4 == 0x6: mem.w32((r[0] + r[nn]) & M32, r[m])
            else: raise SystemExit('모름 %04X @%08X' % (op, pc))
        elif h == 0x1: mem.w32((r[nn] + lo4 * 4) & M32, r[m])
        elif h == 0x5: r[nn] = mem.r32((r[m] + lo4 * 4) & M32)
        elif h == 0x8:
            sub = op >> 8 & 15
            if sub == 0x0: mem.w8((r[m] + lo4) & M32, r[0])
            elif sub == 0x1: mem.w16((r[m] + lo4 * 2) & M32, r[0])
            elif sub == 0x4: r[0] = s8(mem.r8((r[m] + lo4) & M32)) & M32
            elif sub == 0x5: r[0] = s16(mem.r16((r[m] + lo4 * 2) & M32)) & M32
            elif sub == 0x8: T = int((r[0] & M32) == (s8(lo8) & M32))
            elif sub == 0x9:
                if T: npc = pc + 4 + s8(lo8) * 2
            elif sub == 0xB:
                if not T: npc = pc + 4 + s8(lo8) * 2
            elif sub == 0xD:                     # bt/s
                if T: d = pc + 4 + s8(lo8) * 2
            elif sub == 0xF:                     # bf/s
                if not T: d = pc + 4 + s8(lo8) * 2
            else: raise SystemExit('모름 %04X @%08X' % (op, pc))
        elif h == 0xC:
            sub = op >> 8 & 15
            if sub == 0x8: T = int(r[0] & lo8 == 0)
            elif sub == 0x9: r[0] &= lo8
            elif sub == 0xA: r[0] ^= lo8
            elif sub == 0xB: r[0] |= lo8
            else: raise SystemExit('모름 %04X @%08X' % (op, pc))
        elif h == 0xA:
            dd = op & 0xFFF; dd = dd - 0x1000 if dd & 0x800 else dd; d = pc + 4 + dd * 2
        elif h == 0xB:
            dd = op & 0xFFF; dd = dd - 0x1000 if dd & 0x800 else dd; d = pc + 4 + dd * 2; pr = pc + 4
        else:
            raise SystemExit('모름 %04X @%08X' % (op, pc))
        if delay is not None:
            pc, delay = delay, None; continue
        if d is not None:
            delay = d; pc = npc; continue
        pc = npc
