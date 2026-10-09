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
