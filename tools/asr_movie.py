# -*- coding: utf-8 -*-
"""엔딩 동영상 소리 받아쓰기(구간 시각 포함) — work/movie/*.wav(16 kHz 모노, ffmpeg 로 뽑음) → work/movie/asr_movie.tsv
   C:\\claude\\utils\\whisper-venv\\Scripts\\python.exe tools/asr_movie.py"""
import glob, os, sys, wave
import numpy as np
from faster_whisper import WhisperModel
sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
m = WhisperModel('large-v3', device='cuda', compute_type='float16')
with open(os.path.join(ROOT, 'work', 'movie', 'asr_movie.tsv'), 'w', encoding='utf-8') as fo:
    fo.write('movie\tstart\tend\tja\n')
    for p in sorted(glob.glob(os.path.join(ROOT, 'work', 'movie', '*.wav'))):
        w = wave.open(p); a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        seg, _ = m.transcribe(a, language='ja', beam_size=5, condition_on_previous_text=False, vad_filter=False)
        for s in seg:
            fo.write('%s\t%.2f\t%.2f\t%s\n' % (os.path.basename(p)[:-4], s.start, s.end, s.text.strip())); fo.flush()
print('끝')
