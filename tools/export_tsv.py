# -*- coding: utf-8 -*-
"""전체 번역표 내보내기 → work/tsv/bulkslash_NN.tsv (UTF-8, 머리줄 포함 20 KB 이하로 나눔 — feedback_tsv_split_by_29kb)
   열: id · who(화자) · kind(분류) · sec(길이) · ja(음성 = 위스퍼 받아쓰기, 틀릴 수 있음 / 화면 글 = 원문) · ko(번역) · note
   - 음성: 같은 소리(같은 섹터)는 첫 번호만 싣고 note 에 같은 번호들을 적음.
   - ko 는 지금 들어간 번역(work/trans/*.tsv)을 채워 둠. 비우면 자막 없음. 음성 ko 의 « | » = 쪽 나눔.
   - 화면 글(B*·J*) ko 의 « | » = 강제 줄바꿈(브리핑 10자·합류 16자 줄, 합류는 4줄까지).
   python tools/export_tsv.py"""
import os, struct, sys
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import subs
LIMIT = 20 * 1024
NAV = ['레오네', '리라', '메티컬', '나이라', '루피아', '코론', '키나']
SLOT = [(0, 2, '발진'), (3, 5, '타깃'), (6, 6, '미확인 물체'), (7, 9, '전투'), (10, 12, '비명'), (13, 15, '칭찬'),
        (16, 19, '깨우기'), (20, 22, '반응'), (23, 23, '접근'), (24, 27, '아이템'), (28, 31, '방향'), (32, 38, '적 공격 경고'),
        (39, 42, '질책·격려'), (43, 43, '남은 수(다음에 숫자 클립)'), (44, 54, '개수'), (55, 66, '시 방향'), (67, 67, '시간 초과'),
        (68, 73, '잡담'), (74, 74, '선택됨'), (75, 76, '합류 인사(화면 글과 같음 — 자막 안 넣음)')]
VCDM_KIND = ['선택됨', '스테이지 고르기', '이름 묻기', '이름 반응', '나쁜 이름 반응', '꾸중', '꾸중', '꾸중']


def kind_of(name):
    b, i = name.split('_'); i = int(i)
    if b == 'VCDM':
        if i < 56: return NAV[i // 8], '캐릭터 선택: ' + VCDM_KIND[i % 8]
        return '리젠·크레스', '이야기 장면(긴 대화 — 쪽 나눔 « | » 권장)'
    who = NAV[int(b[3])]
    for a, z, k in SLOT:
        if a <= i <= z: return who, k
    return who, ''


def main():
    asr = {}
    for ln in open(os.path.join(ROOT, 'work', 'asr.tsv'), encoding='utf-8'):
        k, sec, ja = ln.rstrip('\n').split('\t'); asr[k] = (sec, ja)
    tab = [ln.split('\t') for ln in open(os.path.join(ROOT, 'work', 'vc_table.tsv'), encoding='utf-8').read().splitlines()[1:]]
    T = subs.load_trans(raw=True); TX = subs.load_trans('text_', raw=True)
    first = {}; same = {}
    for p in tab:
        key = (p[0].split('_')[0], p[1])
        if key in first: same.setdefault(first[key], []).append(p[0])
        else: first[key] = p[0]
    rows = []
    order = ['VCP%d' % i for i in range(7)] + ['VCDM']
    for b in order:
        for p in tab:
            n = p[0]
            if not n.startswith(b + '_') or first[(b, p[1])] != n: continue
            sec, ja = asr[n]
            if not ja.strip(): ja = '(받아쓰기 빈칸 — 들어 보고 채울 것)'
            who, kd = kind_of(n)
            note = ('같은 소리: ' + ', '.join(same[n])) if n in same else ''
            rows.append('\t'.join([n, who, kd, sec, ja.replace('\t', ' '), T.get(n, ''), note]))
    # 화면 글 원문(SEL_DEMO 브리핑 · ALL.ST1 합류) + 지금 번역
    orig = {}
    for ln in open(os.path.join(ROOT, 'work', 'trans', 'text_brief.tsv'), encoding='utf-8').read().splitlines()[1:] + \
              open(os.path.join(ROOT, 'work', 'trans', 'text_join.tsv'), encoding='utf-8').read().splitlines()[1:]:
        p = ln.split('\t'); orig[p[0]] = p[1]
    for i in range(7):
        for s, kd in (('m', '브리핑 본문'), ('t', '브리핑 꼬리(…혼잣말)')):
            k = 'B%d%s' % (i, s); rows.append('\t'.join([k, '사령관', '스테이지 %d %s' % (i + 1, kd), '', orig[k], TX.get(k, ''), '10자 줄']))
    for i in range(8):
        k = 'J%d' % i; rows.append('\t'.join([k, (NAV + ['(시)'])[i], '합류 대사창', '', orig[k], TX.get(k, ''), '16자 × 4줄까지']))
    head = 'id\twho\tkind\tsec\tja\tko\tnote'
    out = os.path.join(ROOT, 'work', 'tsv'); os.makedirs(out, exist_ok=True)
    for f in os.listdir(out):
        if f.startswith('bulkslash_') and f.endswith('.tsv'): os.remove(os.path.join(out, f))
    parts, cur = [], []
    for r in rows:
        if cur and len(('\n'.join([head] + cur + [r]) + '\n').encode('utf-8')) > LIMIT:
            parts.append(cur); cur = []
        cur.append(r)
    if cur:
        if parts and len(('\n'.join([head] + parts[-1] + cur) + '\n').encode('utf-8')) <= LIMIT: parts[-1] += cur   # 자투리는 합침
        else: parts.append(cur)
    for i, p in enumerate(parts, 1):
        open(os.path.join(out, 'bulkslash_%02d.tsv' % i), 'w', encoding='utf-8', newline='\n').write('\n'.join([head] + p) + '\n')
    print('%d줄 → %s (%d개)' % (len(rows), out, len(parts)))


if __name__ == '__main__':
    main()
