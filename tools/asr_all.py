# -*- coding: utf-8 -*-
"""work/vc/*.wav 전부 받아쓰기(위스퍼 large-v3) → work/asr.tsv (이름·실제 길이·문장)
   C:\\claude\\utils\\whisper-venv\\Scripts\\python.exe tools/asr_all.py"""
import glob, os, sys, wave
import numpy as np
from faster_whisper import WhisperModel
sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
m = WhisperModel('large-v3', device='cuda', compute_type='float16')
real = {l.split('\t')[0]: int(l.split('\t')[4]) for l in open(os.path.join(ROOT, 'work', 'vc_table.tsv'), encoding='utf-8')
        if not l.startswith('name')}
out = os.path.join(ROOT, 'work', 'asr.tsv')
done = set()
if os.path.exists(out):
    done = {l.split('\t')[0] for l in open(out, encoding='utf-8')}
fo = open(out, 'a', encoding='utf-8')
for p in sorted(glob.glob(os.path.join(ROOT, 'work', 'vc', '*.wav'))):
    k = os.path.basename(p)[:-4]
    if k in done:
        continue
    w = wave.open(p); a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    seg, _ = m.transcribe(a, language='ja', beam_size=5, condition_on_previous_text=False, vad_filter=False)
    t = ''.join(s.text.strip() for s in seg)
    fo.write('%s\t%.2f\t%s\n' % (k, real[k] / 22050, t)); fo.flush()
print('끝')
