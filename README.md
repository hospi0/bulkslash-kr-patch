# 벌크 슬래시 한글 패치 (Bulk Slash, 세가 새턴 일본판)

- 대상: Bulk Slash (Japan) — 트랙 1에 xdelta 패치 (트랙 2·3 오디오·cue 는 그대로)
- 내려받기: 릴리즈의 `BulkSlash_KR_v0.9.zip` — 안의 readme.txt 에 원본·패치 md5 와 적용 방법

| 트랙 | 원본 md5 | 패치 md5 |
|---|---|---|
| Track 1 | `F392D1F214401D8BA7377FBF9866A87B` | `2FF57B427844117430D7FF1455EB6BAB` |

## 바뀌는 것 (v0.9)
- 내비게이터 음성 자막 566개 — 원래 자막이 없는 게임이라 새로 넣음(화면 맨 위 — 보스 체력 바가 있으면 그 밑, 음성 길이에 맞춰 사라짐)
- 미션 브리핑, 내비게이터 합류 대사창(음성에 맞춰 글자가 드러나는 칸 수도 번역에 맞춤)
- 컨트롤러 설정 화면 라벨, 저장 화면 문구
- 엔딩 동영상 8편 자막(영상에 구워 넣음)

## 알려진 점
- 캐릭터 선택 화면의 음성에는 자막이 나오지 않음
- 저장 관련 긴 경고문(본체 RAM 초기화 안내 등)과 스태프 롤은 원문 그대로
- 받아쓰기로 알아듣기 어려웠던 짧은 음성 몇 개(무기 이름 등)는 자막 없음

## 저장소
- `tools/subs.py` 빌더 — 음성 자막 훅(SH-2, 1ST.BIN 두 곳만 덮음) · 코드·자막·화면 글은 KANJI.FON 의 빈 JIS 행에 · 한글은 안 쓰는 한자 칸에
- `tools/test_subs.py` SH-2 흉내기(`sh2sim.py`) 검산 · `tools/build_disc.py` 디스크 제자리 기록 · `tools/make_dist.py` 배포
- `tools/moviesub.py`/`movenc.py`/`filmcpk.py` 엔딩 동영상 자막 · `tools/retime_movie.py` 자막 시각
- `work/trans/` 번역(음성 vcp0‥6·vcdm, 화면 글 text_*) · `work/tsv/` 전체 번역표 · `work/movie/movie_subs.tsv` 엔딩 자막
- `docs/00_survey.md` 조사·설계 기록
