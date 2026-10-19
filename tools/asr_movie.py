# -*- coding: utf-8 -*-
"""엔딩 동영상 소리 받아쓰기(낱말 시각) — work/movie/*.wav(16 kHz 모노) → work/movie/asr_words.tsv (movie·낱말 시작·끝·낱말)
   + 구간별 다시 듣기: python tools/asr_movie.py --clip METHI_ED 28 41
   C:\\claude\\utils\\whisper-venv\\Scripts\\python.exe tools/asr_movie.py"""
import glob, os, sys, wave
import numpy as np
from faster_whisper import WhisperModel
sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
m = WhisperModel('large-v3', device='cuda', compute_type='float16')


def load(name):
    w = wave.open(os.path.join(ROOT, 'work', 'movie', name + '.wav'))
    return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768


if '--clip' in sys.argv:
    i = sys.argv.index('--clip'); name, a, b = sys.argv[i + 1], float(sys.argv[i + 2]), float(sys.argv[i + 3])
    x = load(name)[int(a * 16000):int(b * 16000)]
    for beam, temp in ((5, 0.0), (10, 0.0), (5, 0.4)):
        seg, _ = m.transcribe(x, language='ja', beam_size=beam, temperature=temp, condition_on_previous_text=False,
                              vad_filter=False, word_timestamps=True)
        print('beam %d temp %.1f:' % (beam, temp), ' | '.join('%.2f %s' % (a + s.start, s.text) for s in seg))
    sys.exit()

with open(os.path.join(ROOT, 'work', 'movie', 'asr_words.tsv'), 'w', encoding='utf-8') as fo:
    fo.write('movie\tstart\tend\tword\tseg\n')
    for p in sorted(glob.glob(os.path.join(ROOT, 'work', 'movie', '*.wav'))):
        n = os.path.basename(p)[:-4]
        seg, _ = m.transcribe(load(n), language='ja', beam_size=5, condition_on_previous_text=False, vad_filter=False, word_timestamps=True)
        for k, s in enumerate(seg):
            for w in (s.words or []):
                fo.write('%s\t%.2f\t%.2f\t%s\t%d\n' % (n, w.start, w.end, w.word.strip(), k))
print('끝')
