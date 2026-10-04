# 작업 체크리스트

## v2.0.9 VOD 재시도 슬롯 교착 수정·릴리즈 준비 (2026-09-26)

- [x] 재시도가 세마포어 슬롯을 쥔 채 재귀하며 슬롯을 하나 더 얻으려는 원인 확인 (`asyncio.Semaphore`는 재진입 불가)
- [x] 실패 테스트 먼저 작성: 동시 개수 1에서 혼자 실패, 기본값 3에서 세 작업이 한꺼번에 실패 (수정 전 둘 다 5초 타임아웃)
- [x] 한 번의 시도만 슬롯을 쥐도록 `_attempt_download`로 분리하고, 슬롯을 반납한 뒤 백오프·재시도
- [x] 백오프 간격(3초·6초)·오류 메시지·취소 처리·재시도 불가 오류 즉시 중단은 그대로 유지
- [x] `test_other_failures_still_retry`에서 동시 개수를 3으로 올려 두던 우회 코드 제거
- [x] 백엔드 전체 테스트 통과 (`274 passed, 29 skipped`, 기준선 대비 새 테스트 2개)
- [x] 프런트엔드 TypeScript 검사와 프로덕션 빌드 통과
- [x] 백엔드·npm 패키지·lockfile·CHANGELOG·README 버전을 `2.0.9`로 통일, 테스트 기준선을 `274 passed`로 갱신
- [x] PyInstaller Windows one-file 실행 파일 빌드 통과
- [x] 빈 폴더에서 실행 파일의 헬스 API(`version 2.0.9`)·최초 설정 상태·내장 SPA·정적 파일·SPA 폴백 확인, 첫 실행에서 `bin/yt-dlp.exe` 자동 설치 확인
- [x] 실행 파일의 `FileVersion`·`ProductVersion`이 `2.0.9`인지 확인

빌드 산출물: `dist/Rookery.exe` (37,924,356 bytes)

SHA-256: `FE9EF4CB10F5EC1552D3B44DC3A0EACA13D8BB3C55D09F25442F0009B5F73F65`

## v2.0.8 로그인 전용 TwitCasting 아카이브 처리·릴리즈 준비 (2026-09-24)

- [x] 로그인 전용 아카이브 페이지에 영상 주소 대신 `Login required to watch` 안내만 있는 것 확인
- [x] yt-dlp가 `Failed to get m3u8 playlist`로 끝날 때만 페이지를 받아 차단 이유 판별
- [x] 로그인 전용·비밀번호 영상은 재시도 없이 한국어 이유를 남기고 실패 처리
- [x] 네트워크 오류 등 다른 실패는 기존처럼 재시도하는지 테스트로 확인
- [x] 실제 로그인 전용 아카이브로 확인: 1회 시도·약 1.6초 만에 이유 표시 (이전: 3회 재시도 후 yt-dlp 버그 제보 문구)
- [x] 백엔드·npm 패키지·lockfile·CHANGELOG·README 버전을 `2.0.8`로 통일
- [x] 백엔드 전체 테스트 통과 (`272 passed, 29 skipped`)
- [x] 프런트엔드 TypeScript 검사와 프로덕션 빌드 통과
- [x] PyInstaller Windows one-file 실행 파일 빌드 통과
- [x] 빈 폴더에서 실행 파일의 헬스 API·최초 설정 상태·내장 SPA·정적 파일 확인
- [x] 실행 파일의 `FileVersion`·`ProductVersion`이 `2.0.8`인지 확인

빌드 산출물: `dist/Rookery.exe` (37,922,532 bytes)

SHA-256: `562308081299F0800AC397EB97B358F19C43F2917D9FDF3E37FF004C38AB3399`

## v2.0.6 대시보드 플랫폼 메뉴 수정·릴리즈 준비 (2026-09-05)

- [x] `PageHeader`의 `overflow-hidden`이 플랫폼 목록을 자르는 원인 확인
- [x] 장식 배경에만 잘림을 적용하고 헤더 액션 메뉴는 밖으로 표시
- [x] 모바일에서 플랫폼 메뉴를 왼쪽 기준으로 배치하고 최대 높이·세로 스크롤 적용
- [x] 프런트엔드 TypeScript 검사와 프로덕션 빌드 통과 (`npm run build`)
- [x] 격리된 Edge 브라우저 테스트 3개 통과: 1440×900, 390×844, 640×280
- [x] 네 플랫폼 항목의 클릭 가능 영역, YouTube 선택·입력 안내 변경·메뉴 닫힘, 낮은 창의 내부 스크롤 확인
- [x] 기존 헤더 잘림 속성을 복원하면 YouTube 항목이 가려지는 것을 테스트에서 재현
- [x] 백엔드·npm 패키지·lockfile·CHANGELOG 버전을 `2.0.6`으로 통일
- [x] 백엔드 전체 테스트 통과 (`242 passed, 29 skipped`)
- [x] PyInstaller Windows one-file 실행 파일 빌드 통과
- [x] 깨끗한 폴더에서 실행 파일의 헬스 API·내장 SPA·최초 설정 상태 확인
- [x] 실행 파일의 `FileVersion`·`ProductVersion`이 `2.0.6`인지 확인

브라우저 검증은 테스트 전용 API 모의 응답으로 수행했다. 실제 채널 추가 요청이나 녹화는 실행하지 않았다.
로컬 검증 스크립트: `build/platform-menu-regression.cjs` (Git 제외, Playwright 런타임 필요).

빌드 산출물: `dist/Rookery.exe` (38,076,862 bytes)

SHA-256: `C2DCF670B93CB31FE56560F941E9690685B18D308EB8639B291E758C6AF13A4E`

## v2.0.5 릴리즈 준비 (2026-08-29)

- [x] `main`과 `origin/main`이 같은 커밋인지 확인
- [x] `v2.0.4` 이후 릴리즈 대상이 정확히 6개 커밋인지 확인
- [x] 백엔드·npm 패키지·lockfile 버전을 `2.0.5`로 통일
- [x] CHANGELOG 릴리즈 항목과 비교 링크 갱신
- [x] 릴리즈 메타데이터 일관성 회귀 테스트 추가
- [x] 백엔드 전체 테스트 통과 (`242 passed, 29 skipped`)
- [x] FastAPI `0.135.2`와 CI의 `0.141.1` 환경에서 동일한 결과 확인
- [x] 프런트엔드 TypeScript 검사와 프로덕션 빌드 통과
- [x] PyInstaller Windows one-file 실행 파일 빌드 통과
- [x] 빈 폴더에서 실행 파일의 헬스 API와 내장 프런트엔드 응답 확인
- [x] 실행 파일의 `FileVersion`·`ProductVersion`이 `2.0.5`인지 확인

빌드 산출물: `dist/Rookery.exe`

SHA-256: `1BF0E47C3AEF834B2E0CB5BE31006B8815B0BB0BA8A28C6338DA16EB56D1D868`
