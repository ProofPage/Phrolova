# UI 회귀 검사

제품 의존성에 테스트 도구를 추가하지 않고 별도 Python 환경에서 실행합니다.
`playwright`와 Chromium, preview 검사용 `ffmpeg`가 필요합니다.

```bash
python -m pip install playwright
python -m playwright install chromium
cd frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 3000
```

별도 터미널에서 저장소 루트를 기준으로 실행합니다.

```bash
python frontend/tests/filtered_reorder.py
PHROLOVA_PREVIEW_WIDTHS=390 PHROLOVA_PREVIEW_ONLY=1 python frontend/tests/preview_layout.py
```

- `filtered_reorder.py`: Live와 Downloads 필터의 보이는 이웃 이동, 첫/마지막 항목 비활성화, 숨은 항목 순서와 기존 payload 보존을 확인합니다.
- `preview_layout.py`: 상태 그룹 중앙 정렬, compact offline/error, 실제 HLS 재생과 player 크기를 확인합니다. 1440px 검사에서는 resize/reorder 후 동일 video 요소를 유지하는지도 확인합니다.
- `PHROLOVA_PREVIEW_WIDTHS`: 쉼표로 구분한 대표 폭을 선택합니다. 기본값은 320/390/820/1024/1440입니다.
- `PHROLOVA_PREVIEW_ONLY=1`: 변경되지 않은 Downloads 화면 검사를 생략합니다.
- `PHROLOVA_TEST_URL`, `PHROLOVA_TEST_OUTPUT`: 서버 주소와 결과 위치를 지정합니다. 기본 결과 위치는 시스템 임시 디렉터리이며 스크린샷/영상 산출물은 커밋하지 않습니다.

검사는 샘플 API 응답과 로컬 HLS 영상을 사용합니다. 실제 플랫폼 인증·녹화·다운로드 동작을 대체하는 검사는 아닙니다.

CHZZK VOD 준비 목록 검사는 같은 개발 서버에서 실행합니다.

```bash
python frontend/tests/vod_preparation.py
```

- `vod_preparation.py`: 390/1440px에서 여러 URL 등록, URI/plain/HTML 드롭, 중복·잘못된 주소, 영상별 화질, 개별/전체 시작, 정보 재조회, 일시정지·재개·취소·재시도, 새로고침 유지, 완료/개별 이력 정리 및 영어·일본어 표시를 확인합니다. API는 모의 응답입니다.
- `PHROLOVA_CHROMIUM_EXECUTABLE`: 이미 설치된 Chromium의 실행 파일을 지정할 수 있습니다. 생략하면 Playwright의 기본 Chromium을 사용합니다. 기존 회귀 검사도 같은 변수를 지원합니다.


녹화 복구 및 CDN 설정 회귀 검사:

```bash
PHROLOVA_TEST_URL=http://127.0.0.1:3000 PHROLOVA_TEST_OUTPUT=/tmp/phrolova-repair python frontend/tests/recording_repair.py
```

- 360/390/768/1024/1440/1920px에서 그리드·목록 정렬과 가로 넘침을 확인합니다.
- 파일 없는 시작 실패의 수치·버튼 상태, 반복 이력 묶음과 목록 정리 요청을 검사합니다.
- 라이브·다운로드 CDN 선택을 각각 저장하고 새로고침 후 복원하는 API 연결을 검사합니다.
- 브라우저 검사는 모의 API를 사용합니다. 실제 파일 검사·Streamlink 녹화·종료 후 변환은 `backend/tests/test_recording_log_regressions.py`에서 검증합니다.

초기 기본 설정 마법사 회귀 검사:

```bash
python frontend/tests/setup_wizard.py
```

- `setup_wizard.py`: 320/390/640/1440px와 844×390 가로 화면에서 기본 경로의 34/44px 높이·텍스트 중앙 정렬과 창 크기에 따른 자동 줄바꿈, 긴 한글 저장 경로, 폴더 선택과 키보드 초점, 공용 화질·형식 선택 상자의 키보드 조작, 이전/다음, 빈 경로, 저장 중 조작 잠금과 실패 후 재시도를 확인합니다. 설정·폴더 API는 모의 응답이며 실제 설정이나 폴더를 변경하지 않습니다.

다국어 검사는 [구현·검증 기록](../../docs/i18n.md)을 참고하세요.

다운로드 설정의 통합 저장 회귀 검사:

```bash
PHROLOVA_TEST_OUTPUT=/tmp/phrolova-unified-settings python frontend/tests/settings_consistency.py
```

- 세 영역의 변경사항을 한 버튼으로 저장하고 변경된 영역만 순서대로 요청하는지 확인합니다.
- 저장 중 중복 요청과 입력 변경 방지, 숫자 범위 검증, 부분 실패 후 실패한 영역만 재시도, 탭 이동 경고와 새로고침 복원을 검사합니다.
- 6개 창 크기와 8개 언어에서 하단 오른쪽 버튼의 고정 위치·잘림·가로 넘침과 ‘저장됨’ 문구가 표시되지 않는지 확인합니다.

```bash
cd frontend
npm run i18n:check
npm run i18n:test
cd ..
python frontend/tests/i18n_regression.py
```

- `i18n:check`: 8개 언어의 키·빈 값·중복·변수, 현재 UI의 의미 키와 하드코딩된 한국어 JSX/접근성 문구를 검사합니다.
- `i18n:test`: 로케일 호환·폴백, 날짜/숫자/바이트, 변수·복수형과 기존 메시지 재번역을 검사합니다.
- `i18n_regression.py`: 격리된 브라우저와 모의 API에서 8개 언어·전체 페이지·설정 하위 탭, 320/390/1440px, 즉시 전환과 새로고침 복원, 기본 설정/녹화 팝업·자동 녹화/시작/중지 요청을 검사합니다.

- `i18n_hmr.py`: Vite 개발 서버에 연결하여 번역 리소스 자동 갱신과 복원 중 Context 오류/빈 화면이 발생하지 않는지 확인합니다. 원본 JSON을 `finally`에서 복원하며 다른 번역 파일 편집/제품 빌드와 동시에 실행하지 마세요.

로그 대시보드 회귀 검사:

```bash
python frontend/tests/logs_dashboard.py
```

- 8개 언어·4개 화면 폭에서 파일 요약, 오류·경고 분류와 검색 조합, 아이콘 제거 및 화면 높이를 확인합니다.
- 실시간 갱신의 중지·재개, 이전 내용을 유지하는 실패 처리, 파일 전환 중 요청 취소, 줄 수 변경, 원문 내보내기, 좌우 패널 높이, 빈 로그 및 초기화 확인·취소를 검사합니다.
- 모든 로그와 초기화 요청은 격리된 모의 API를 사용합니다.
