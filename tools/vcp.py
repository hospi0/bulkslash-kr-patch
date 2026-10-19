# -*- coding: utf-8 -*-
"""음성 묶음 VCP0‥6.DAT·VCDM.DAT 풀기 → work/vc/<묶음>_<번호>.aif + .wav(16 kHz, 받아쓰기용)

  python tools/vcp.py

묶음 형식: 섹터 0 = (시작 섹터, 섹터 수, 자리 크기, 실제 크기?) u32 BE × N, 시작 0 이면 끝.
클립 = AIFF(COMM·MARK·INST·APPL «ALCHENVS»·SSND), 모노 8비트 22,050 Hz, 자리 크기까지 0 채움.
"""
import glob, os, struct, subprocess, sys
sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FF = r'C:\claude\utils\ffmpeg-9.0.1-essentials_build\bin\ffmpeg.exe'


def entries(d):
    out = []
    for i in range(len(d) // 16):
        s, c, a, z = struct.unpack_from('>4I', d, i * 16)
        if s == 0:
            break
        out.append((s, c, a, z))
    return out


def ssnd(b):
    """(SSND 소리 시작, 길이, COMM 프레임 수)"""
    j = 12; fr = None
    while j < len(b) - 8:
        ck = b[j:j + 4]; ln = struct.unpack_from('>I', b, j + 4)[0]
        if ck == b'COMM':
            fr = struct.unpack_from('>I', b, j + 10)[0]
        if ck == b'SSND':
            off = struct.unpack_from('>I', b, j + 8)[0]
            return j + 16 + off, ln - 8 - off, fr
        j += 8 + ln + (ln & 1)


if __name__ == '__main__':
    od = os.path.join(ROOT, 'work', 'vc'); os.makedirs(od, exist_ok=True)
    rows = []
    for fn in sorted(glob.glob(os.path.join(ROOT, 'work', 'iso', 'VC*.DAT'))):
        tag = os.path.basename(fn)[:-4]; d = open(fn, 'rb').read()
        for i, (s, c, a, z) in enumerate(entries(d)):
            b = d[s * 2048:s * 2048 + a]
            p0, ln, fr = ssnd(b)
            pcm = b[p0:p0 + ln]
            last = len(pcm.rstrip(b'\0'))   # 실제 소리 끝(뒤 0 채움 제외)
            name = '%s_%02d' % (tag, i)
            open(os.path.join(od, name + '.aif'), 'wb').write(b)
            subprocess.run([FF, '-v', 'error', '-y', '-i', os.path.join(od, name + '.aif'),
                            '-ac', '1', '-ar', '16000', os.path.join(od, name + '.wav')], check=True)
            rows.append((name, s, c, a, z, fr, ln, last))
    with open(os.path.join(ROOT, 'work', 'vc_table.tsv'), 'w', encoding='utf-8') as f:
        f.write('name\tsector\tnsec\talloc\tfield4\tframes\tssnd\tlast_nonzero\n')
        for r in rows:
            f.write('\t'.join(map(str, r)) + '\n')
    print(len(rows), '개', '%.1f 초' % (sum(r[5] for r in rows) / 22050))
