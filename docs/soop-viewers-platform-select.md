# 숲 현재 시청자 수 및 플랫폼 선택창 수정

2026-10-12 확인.

## 원인과 변경

- 기존 숲 player live API에는 `VIEW_CNT`/`CURRENT_VIEW_CNT`가 없고, 기존 station status API에는 누적 `total_view_cnt`만 있어 현재 시청자 수가 0으로 표시됐다.
- 공식 `https://chapi.sooplive.com/api/{channel_id}/station`의 `broad.current_sum_viewer`를 사용한다. `broad_no`가 현재 player API 방송 번호와 일치할 때만 적용하며 정상 0명도 유효한 값으로 처리한다.
- 누적 시청자·방문자 수를 현재 시청자 수로 대체하지 않는다. 오프라인은 0명, 선택 메타데이터의 일시적인 연결 실패는 방송 감지/Streamlink 연결을 막지 않는다.
- 8초 캐시와 만료 후 재조회 유지. 기존 방송 재시작 판단에 필요한 시작 시각은 새 API의 `station.broad_start`에서 보존한다.
- 라이브 선택창은 `justify-content: space-between`과 라벨의 flex 공간이 다운로드 선택창과 달랐다. 동일 `PlatformSelectTrigger`를 사용해 점·왼쪽 정렬 이름·오른쪽 화살표, 8px 간격, 10px 내부 여백, 데스크톱 34px/모바일 44px 높이를 통일한다.

## 검증

- 수정 전 백엔드 회귀: 5 failed / 2 passed로 재현. 수정 후 7 passed: 숫자·문자열·0명, 캐시 만료 갱신, 오프라인·다른 방송·누락 값·네트워크 실패, 방송 시작 시각 보존.
- 숲/씨미 통합 포함 집중 검사: 65 passed.
- 전체 backend: 873 passed, 1 skipped, 4 subtests passed. 마지막 시작 시각 보존/캐시 갱신 강화 후 해당 7개 재검증 통과.
- Ruff E9/F63/F7/F82, TypeScript/Vite build, git diff whitespace 통과.
- Chromium `frontend/tests/platform_select_geometry.py`: 4개 플랫폼 × 360/768/1440px에서 라이브/다운로드 선택창의 실제 DOM 폭·높이·이름/점/화살표 위치·글꼴·색상 동일. 메뉴 선택·Escape·키보드·포커스·가로 넘침 및 숲 카드 17,916명 fixture 표시 통과.
- 실제 공개 김민교 채널의 수정된 엔진: `is_live=True`, `viewer_count=19222`, `live_started_at='2026-10-12 14:07:32'` 반환 확인. 이 수는 조회 시점 값이다. 인증 쿠키와 스트림 URL을 기록하지 않았다.

스크린샷: 작업 산출물 `outputs/soop-viewers-platform-select/live-{360,768,1440}.png` 및 `download-{360,768,1440}.png`.

Streamlink/yt-dlp 녹화 구조, 사용자 설정/DB/녹화 파일과 플랫폼 키를 유지한다. `scripts/manage.bat`의 별도 줄바꿈 변경은 이 커밋에서 제외한다.
