# 치지직 LL-HLS·CDN 복구 적용 기록

참조: [Chzzk-Rekoda 50424e50](https://github.com/munsy0227/Chzzk-Rekoda/commit/50424e50b56fca13a1a071983a4ddecdcb0f6ff2). 적용 환경: Windows x64, Python 3.12, Streamlink 8.6.2.

## Phrolova에 적용한 구조

| 참조 변경 | Phrolova 적용 |
| --- | --- |
| 국내 CDN·LL-HLS 우선 | `chzzk_time_machine.py`의 일반 라이브 URL 선택. 명시적 Akamai 선택과 강제 타임머신 시작은 보존 |
| Streamlink 연속 수신 | `chzzk_continuity.py`의 전용 parser/worker/writer/reader. 다른 플랫폼의 HLS 수신은 유지 |
| PART 선취·검증 | 공개된 PART만 수신. 완성된 전체 구간을 한 번만 출력하며 손상·중복·GAP·길이 불일치·암호화 부분 묶음은 전체 구간으로 대체 |
| Blocking reload | 광고된 CAN-BLOCK-RELOAD 사용. 원래 서명 쿼리를 보존하고 정상 대기와 장애를 구분 |
| Akamai 예비 경로 | 알려진 두 국내 HTTPS 호스트만 `livecloud.akamaized.net` 후보로 변환. 경로·쿼리 보존. 광고된 후보도 실제 같은 구간·초기화·미디어 검증 후 준비 완료 표시 |
| 누락 구간 복구 | 국내 현재·최근 최대 1시간 과거 우선, 최초 과거 확인 2초 예산 이후 Akamai 확인. 복구 전체 90초 제한, 요청·캐시 수 제한 |
| 파일 경계·재개 | 초기화 변경·불연속 또는 확인된 공백 이후 기존 writer를 종료하고 새 파일·세션·작업에서 지정 시각부터 재개. 원본에 새 init를 이어 붙이지 않음 |
| 안전한 수신 상태 | JSON stderr 프로토콜을 FastAPI용 콜백으로 변경. URL·서명·쿠키를 제거한 이벤트 최대 64개 저장. 상세 보기에서 CDN/HLS/LL-HLS 및 예비 CDN 상태 표시 |

`chzzk_stream.py`는 CHZZK API와 위 수신 계층을 연결합니다. API 쿠키는 API 요청에만 명시적으로 전달하며, P2P `cdn_url`은 실제 HTTP CDN 주소만 추출합니다. 알 수 없는 호스트나 HTTP·자격 증명 포함 주소를 Akamai 후보로 바꾸지 않습니다.

## 녹화·후처리·설정 보존

- 라이브 수신 엔진은 Streamlink입니다. TS 호환 화질을 우선하며 fMP4 소스는 실제 형식인 `.native.mp4`로 보존합니다.
- Streamlink 종료와 파일 writer 종료가 확인된 후 기존 후처리 큐에서 fMP4 → TS → MKV/MP4를 수행하고 FFprobe로 검사합니다. 녹화 중 FFmpeg 파이프는 만들지 않습니다.
- 기본 완료 형식 MKV, 선택 형식 MP4 및 채널 우선 설정을 유지합니다.
- 파일 경계 이후 이어지는 녹화도 최초 화질·완료 형식·원본 보관 정책을 유지합니다. 녹화 중 변경은 다음 새 녹화부터 적용됩니다.
- 자동 녹화 OFF는 새로운 자동 시작·자동 재시도를 막습니다. 이미 실행 중인 녹화의 컨테이너 경계 처리는 해당 녹화의 연속 동작으로 유지합니다. 수동 중지나 서버 종료는 새 writer 시작을 차단합니다.
- 복구 기한을 넘긴 CHZZK 원본에 일반 재연결 데이터를 무리하게 이어 붙이지 않습니다. 접근 권한 오류는 사용자 조치 상태로 분류합니다.
- UUID 기반 기존 파일 경로와 SQLite 세션 멱등성을 유지합니다. 경계마다 별도 유효 파일·작업을 생성하고 완료 작업에 수신 진단을 연결합니다.

## 재현 및 검증

- 로컬 HTTP CDN + 실제 Streamlink: PART 길이·중복·손상, AES-128 전체 구간 대체, blocking reload, 느린 국내 과거 조회, 누락 구간, 토큰 갱신, 초기화·불연속 경계, 요청 상한 검사.
- 실제 생성 미디어 + FFmpeg/FFprobe: 1,000 영상 프레임과 음성 프레임·PTS 간격 보존, 손상 부분 묶음의 전체 구간 대체 확인.
- 실제 Phrolova pipeline: 초기화 변경 전 원본 종료, 지정 시각부터 새 파일 재개, 기존 원본 바이트 보존 확인.
- Conductor: 자동 OFF 상태의 진행 중 녹화 파일 경계 처리, 최초 MP4/1080p 정책 보존, 중복 활성 pipeline 방지 확인.
- 공개 실방송·쿠키 미사용: 강제 타임머신 HLS의 fMP4 원본이 1,048,576 → 90,865,299 B로 증가, 88.625초 미디어 수신. 종료 후 MKV 완료·FFprobe 통과.
- 공개 실방송·일반 모드: 국내 LL-HLS 원본이 1,310,720 → 14,344,118 B로 증가, 14.006초 미디어 수신. 실제 미디어 검사 후 Akamai LL-HLS 예비 준비 완료. 종료 후 MKV 완료·FFprobe 통과.
- 최종 전체 Python 검사: **746 passed, 6 skipped**, 추가 하위 시나리오 4개 통과. 제외는 Windows에서 Bash 실행을 요구하는 5개와 선택적 3GB 미디어 검사 1개입니다.
- 공개 수신 MKV 추가 검사: 일반 LL-HLS 영상 840프레임·음성 656프레임, 영상 PTS 최대 간격 0.017초·음성 0.022초.
- 프론트엔드: TypeScript/Vite 빌드 및 라이브 6개 너비 × 두 보기, 다운로드 7개 너비 × 두 보기의 레이아웃·상세 확장·버튼 기능 검사.

실방송 검증은 짧은 공개 수신입니다. 장시간 자연 CDN 장애 및 Linux/Termux 실기기 실행은 이번 검증에 포함하지 않았습니다. 강제 종료 이후 녹화 커서의 영구 복원은 참조 구현과 마찬가지로 별도 범위이며, 기존 원본·미완료 변환 복구는 유지합니다.

참조 코드의 MIT 고지와 라이선스는 `THIRD_PARTY_NOTICES`에 보존했고 Windows 패키지에도 포함합니다.
