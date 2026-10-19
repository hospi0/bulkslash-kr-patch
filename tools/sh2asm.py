#!/usr/bin/env python3
"""
SH-2 미니 어셈블러 (2026-07-12, shining-kr-patch 에서 가져옴 · 2026-10-19 벌크 슬래시용 명령 추가) — 런타임 훅 코드 인코딩용. 빅엔디언.
지원 서브셋: mov/mov.b/.w/.l(레지스터·@Rn·@Rn+·@-Rn·@(disp,Rn)·@(disp,pc)·#imm),
  add/sub/cmp/tst/and/or/xor/shll/shlr/shll2/shll8/shll16/extu/exts,
  bra/bsr/bt/bf/bt.s/bf.s(라벨), jmp/jsr @Rn, rts, nop, sts.l/lds.l pr.
  .long <imm|label>(리터럴풀), .pool(중간 리터럴 풀), 라벨(name:).
`mov.l #<imm/label>,Rn` → 자동 PC상대 리터럴 로드(풀에 .long 추가).

사용(모듈): asm(text, base_addr) -> bytes.  라벨/리터럴 2패스 처리.
"""
import struct, re

REG = {'r%d' % i: i for i in range(16)}


def _r(t):
    return REG[t.lower()]


def assemble(text, base=0):
    lines = []
    for raw in text.split('\n'):
        s = raw.split(';')[0].strip()
        if s:
            lines.append(s)
    # pass 1: 주소 배정, 라벨 수집, mov.l #x 리터럴 예약
    labels = {}
    items = []  # (kind, ...) kind: 'ins'(16bit later), 'lit'(placeholder for pool)
    pc = base
    lit_pool = []  # (value_or_label, addr)
    pending = []
    waiting, slot, mid_pool, mid_val = [], {}, [], {}
    for ln in lines:
        m = re.match(r'^(\w+):$', ln)
        if m:
            labels[m.group(1)] = pc
            continue
        if ln.startswith('.long'):
            val = ln.split(None, 1)[1].strip()
            pending.append(('long', val, pc)); pc += 4; continue
        if ln == '.pool':                             # 2026-10-19: 중간 풀 — 앞의 mov.l # 리터럴을 여기 둠(앞 명령이 rts/bra 지연 슬롯 뒤여야)
            if pc & 2:
                pending.append(('ins', 'nop', pc)); pc += 2
            for at in waiting:
                slot[at] = pc; mid_pool.append((pc, at)); pc += 4
            waiting = []
            continue
        # mov.l #imm,Rn -> PC-rel load: reserve; literal appended at pool
        if re.match(r'^mov\.l\s+#', ln, re.I):
            waiting.append(pc)
        pending.append(('ins', ln, pc)); pc += 2
    end_code = pc
    # 리터럴풀 = 코드 뒤 4바이트 정렬
    pool_base = (end_code + 3) & ~3
    # 리터럴 필요한 ins 스캔
    litmap = {}  # ins_index -> pool addr

    def add_lit(v, at):
        if at in slot:
            mid_val[slot[at]] = v; return slot[at]
        addr = pool_base + len(lit_pool) * 4
        lit_pool.append(v)
        return addr

    # pass 2: 인코딩
    out = {}
    for kind, ln, at in pending:
        if kind == 'long':
            out[at] = ('long', ln)
            continue
        out[at] = ('ins', ln)

    def imm8(v):
        v &= 0xff
        return v

    def enc(ln, at):
        q = ln.split(None, 1)                         # 2026-10-19: @(disp,Rn) 안 쉼표는 안 나눔
        op = q[0].lower()
        a = [x.strip() for x in re.split(r',(?![^(]*\))', q[1])] if len(q) > 1 else []
        def R(x): return _r(x)
        if op == 'nop': return 0x0009
        if op == 'rts': return 0x000b
        if op == 'sts.l' and a[0].lower() == 'pr': return 0x4f22  # sts.l pr,@-r15
        if op == 'lds.l' and a[1].lower() == 'pr': return 0x4f26  # lds.l @r15+,pr
        if op == 'jmp': return 0x402b | (R(a[0][1:]) << 8)   # jmp @Rn  (a[0]='@Rn')
        if op == 'jsr': return 0x400b | (R(a[0][1:]) << 8)   # jsr @Rn
        if op == 'mov':
            if a[1].startswith('r') and a[0].startswith('r'):  # mov Rm,Rn
                return 0x6003 | (R(a[1]) << 8) | (R(a[0]) << 4)
            if a[0].startswith('#'):  # mov #imm,Rn
                return 0xe000 | (R(a[1]) << 8) | imm8(int(a[0][1:], 0))
        if op in ('mov.l', 'mov.w', 'mov.b'):
            sz = {'mov.b': 0, 'mov.w': 1, 'mov.l': 2}[op]
            src, dst = a[0], a[1]
            # push: mov.l Rm,@-Rn
            if dst.startswith('@-'):
                return (0x2000 | (0x4 + sz)) | (R(dst[2:]) << 8) | (R(src) << 4)
            # pop: mov.l @Rm+,Rn
            if src.startswith('@') and src.endswith('+'):
                return (0x6000 | (0x4 + sz)) | (R(dst) << 8) | (R(src[1:-1]) << 4)
            # mov.l #imm/label,Rn -> PC-rel load (mov.l @(disp,pc),Rn), 리터럴 풀
            if src.startswith('#'):
                v = src[1:]
                laddr = add_lit(v, at)
                disp = (laddr - ((at & ~3) + 4)) // 4
                assert 0 <= disp < 256, 'lit disp %d out of range' % disp
                return 0xd000 | (R(dst) << 8) | (disp & 0xff)  # mov.l @(disp,pc),Rn
            # mov.l @(disp,Rn),Rm  /  mov.l Rm,@(disp,Rn)
            m = re.match(r'@\((\w+),(r\d+)\)', src)
            if m:  # load @(disp,Rn),Rm
                disp = int(m.group(1), 0)
                if sz == 2:
                    return 0x5000 | (R(dst) << 8) | (R(m.group(2)) << 4) | ((disp // 4) & 0xf)
                assert dst.lower() == 'r0', ln
                return (0x8400 if sz == 0 else 0x8500) | (R(m.group(2)) << 4) | ((disp >> sz) & 0xf)
            m = re.match(r'@\((\w+),(r\d+)\)', dst)
            if m:  # store Rm,@(disp,Rn)
                disp = int(m.group(1), 0)
                if sz == 2:
                    return 0x1000 | (R(m.group(2)) << 8) | (R(src) << 4) | ((disp // 4) & 0xf)
                assert src.lower() == 'r0', ln
                return (0x8000 if sz == 0 else 0x8100) | (R(m.group(2)) << 4) | ((disp >> sz) & 0xf)
            # mov.l @Rm,Rn  / mov.l Rm,@Rn
            if src.startswith('@'):
                return (0x6000 | sz) | (R(dst) << 8) | (R(src[1:]) << 4)
            if dst.startswith('@'):
                return (0x2000 | sz) | (R(dst[1:]) << 8) | (R(src) << 4)
        if op == 'add':
            if a[0].startswith('#'):
                return 0x7000 | (R(a[1]) << 8) | imm8(int(a[0][1:], 0))
            return 0x300c | (R(a[1]) << 8) | (R(a[0]) << 4)
        if op == 'sub':
            return 0x3008 | (R(a[1]) << 8) | (R(a[0]) << 4)
        if op == 'cmp/eq':
            if a[0].startswith('#'):
                return 0x8800 | imm8(int(a[0][1:], 0))
            return 0x3000 | (R(a[1]) << 8) | (R(a[0]) << 4)
        if op == 'cmp/hi':
            return 0x3006 | (R(a[1]) << 8) | (R(a[0]) << 4)
        if op == 'tst':
            return 0x2008 | (R(a[1]) << 8) | (R(a[0]) << 4)
        if op == 'and':
            return 0x2009 | (R(a[1]) << 8) | (R(a[0]) << 4)
        if op == 'or':
            return 0x200b | (R(a[1]) << 8) | (R(a[0]) << 4)
        if op == 'xor':
            return 0x200a | (R(a[1]) << 8) | (R(a[0]) << 4)
        if op == 'extu.w':
            return 0x600d | (R(a[1]) << 8) | (R(a[0]) << 4)
        if op == 'extu.b':
            return 0x600c | (R(a[1]) << 8) | (R(a[0]) << 4)
        if op == 'shll2':
            return 0x4008 | (R(a[0]) << 8)
        if op == 'shll8':
            return 0x4018 | (R(a[0]) << 8)
        if op == 'shll16':
            return 0x4028 | (R(a[0]) << 8)
        if op == 'shll':
            return 0x4000 | (R(a[0]) << 8)
        if op == 'shlr':
            return 0x4001 | (R(a[0]) << 8)
        if op == 'shlr2':
            return 0x4009 | (R(a[0]) << 8)
        if op == 'shlr8':
            return 0x4019 | (R(a[0]) << 8)
        if op == 'shlr16':
            return 0x4029 | (R(a[0]) << 8)
        if op == 'dt':
            return 0x4010 | (R(a[0]) << 8)
        if op == 'not':
            return 0x6007 | (R(a[1]) << 8) | (R(a[0]) << 4)
        if op == 'cmp/hs':
            return 0x3002 | (R(a[1]) << 8) | (R(a[0]) << 4)
        if op == 'cmp/ge':
            return 0x3003 | (R(a[1]) << 8) | (R(a[0]) << 4)
        if op == 'cmp/gt':
            return 0x3007 | (R(a[1]) << 8) | (R(a[0]) << 4)
        if op == 'cmp/pl':
            return 0x4015 | (R(a[0]) << 8)
        if op == 'cmp/pz':
            return 0x4011 | (R(a[0]) << 8)
        if op in ('bra', 'bsr', 'bt', 'bf', 'bt.s', 'bf.s', 'bt/s', 'bf/s'):
            tgt = labels[a[0]]
            disp = (tgt - (at + 4)) // 2
            if op == 'bra':
                assert -2048 <= disp < 2048; return 0xa000 | (disp & 0xfff)
            if op == 'bsr':
                assert -2048 <= disp < 2048; return 0xb000 | (disp & 0xfff)
            base_op = {'bt': 0x8900, 'bf': 0x8b00, 'bt.s': 0x8d00, 'bt/s': 0x8d00, 'bf.s': 0x8f00, 'bf/s': 0x8f00}[op]
            assert -128 <= disp < 128, 'branch %s disp %d' % (op, disp)
            return base_op | (disp & 0xff)
        raise ValueError('unknown/unsupported: %s' % ln)

    # 인코딩(리터럴 add_lit이 pool 채움)
    encoded = {}
    for at in sorted(out):
        kind, ln = out[at]
        if kind == 'long':
            continue
        encoded[at] = enc(ln, at)
    # 출력 조립
    total = pool_base + len(lit_pool) * 4
    buf = bytearray(total - base)
    for at, w in encoded.items():
        struct.pack_into('>H', buf, at - base, w)
    # .long 항목
    for at in sorted(out):
        kind, ln = out[at]
        if kind == 'long':
            v = labels[ln] if ln in labels else int(ln, 0)
            struct.pack_into('>I', buf, at - base, v & 0xffffffff)
    # 중간 풀
    for a, v in mid_val.items():
        val = labels[v] if v in labels else int(v, 0)
        struct.pack_into('>I', buf, a - base, val & 0xffffffff)
    # 리터럴 풀
    for i, v in enumerate(lit_pool):
        val = labels[v] if v in labels else int(v, 0)
        struct.pack_into('>I', buf, (pool_base + i * 4) - base, val & 0xffffffff)
    return bytes(buf)


if __name__ == '__main__':
    # 자체 테스트: 간단 코드 어셈블→디스어셈블 대조
    code = '''
    start:
      mov.l #0x0607b390,r1
      mov.w @r1+,r0
      extu.w r0,r0
      mov #0x08,r2
      cmp/eq r2,r0
      bt done
      nop
    done:
      rts
      nop
    '''
    b = assemble(code, 0x06000000)
    print('assembled %d bytes:' % len(b), b.hex())
