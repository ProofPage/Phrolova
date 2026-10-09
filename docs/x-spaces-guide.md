# Twitter(X) Spaces 설정 가이드

## 개요

Twitter(X) Spaces 기능은 세 가지로 구성됩니다:

| 기능 | 방법 |
|------|------|
| **Space 감지** | Discord `/capture-space` 커맨드로 수동 캡처 |
| **아카이브 다운로드** | Archive 탭 또는 Discord `/download-space` |
| **쿠키 만료 알림** | 쿠키 만료 감지 시 Discord 자동 알림 |

> **왜 자동 감지가 아닌가?**
> Twitter 비공식 API(UserTweets 타임라인)는 레이트 리밋이 매우 엄격합니다.
> 자동 폴링 시 429 오류로 차단될 수 있어 수동 캡처 방식을 기본으로 사용합니다.

---

## 1단계: Twitter(X) 쿠키 파일 준비

### 방법 A: 브라우저 확장 프로그램 (권장)

1. Chrome/Edge에서 [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) 확장 프로그램을 설치합니다.

2. [x.com](https://x.com)에 로그인합니다.

3. 확장 프로그램 아이콘 클릭 → **Export** 버튼 클릭 → `x.com.txt` 파일 저장.

4. 파일을 열어 `auth_token`과 `ct0` 항목이 있는지 확인합니다:
   ```
   .x.com	TRUE	/	TRUE	...	auth_token	...
   .x.com	TRUE	/	TRUE	...	ct0	...
   ```

### 방법 B: 개발자 도구 직접 추출

1. [x.com](https://x.com) 로그인 후 개발자 도구(F12) 열기.
2. **Application** → **Cookies** → `https://x.com` 선택.
3. `auth_token`과 `ct0` 값을 메모합니다.
4. 아래 형식으로 `x_cookies.txt` 파일을 직접 작성합니다:
   ```
   # Netscape HTTP Cookie File
   .x.com	TRUE	/	TRUE	9999999999	auth_token	YOUR_AUTH_TOKEN
   .x.com	TRUE	/	TRUE	9999999999	ct0	YOUR_CT0_TOKEN
   ```

---

## 2단계: 쿠키 파일 업로드

1. Phrolova 웹 UI에서 **Settings** 페이지로 이동합니다.
2. **인증** 탭 → **Twitter(X) Spaces** 섹션을 찾습니다.
3. 쿠키 파일(`.txt`)을 업로드합니다.
4. **저장** 버튼 클릭.

쿠키가 유효하면 인증 상태가 ✅로 표시됩니다.

---

## 3단계: X Spaces 채널 등록

1. **Dashboard** 페이지 → **채널 추가** 버튼 클릭.
2. **플랫폼**: `Twitter(X) Spaces` 선택.
3. **채널 ID**: Twitter 핸들 입력 (예: `elonmusk`, `@` 없이 입력).
4. 추가 완료.

> 쿠키가 설정되지 않은 상태에서 채널을 추가하면 자물쇠 아이콘(🔒)으로 표시됩니다.

---

## 4단계: Space 수동 캡처

### Discord 커맨드 사용

Space가 라이브 중일 때 Discord에서 다음 커맨드를 실행합니다:

```
/capture-space username:elonmusk
```

성공 시 다음 정보가 반환됩니다:
- Space 제목
- master_playlist.m3u8 URL
- 저장된 백업 파일 경로

### 자동 캡처 (등록된 채널)

등록된 채널이 Space를 시작하면 폴링 주기(최대 5분)마다 자동으로 감지하고:
- master URL을 `{저장경로}/x_spaces_urls/{채널}_{spaceId}_{날짜}.txt`에 저장
- Discord에 알림 발송

---

## 5단계: Space 다운로드

### Archive 탭에서 다운로드

1. 웹 UI → **Archive** 탭 → **X Spaces** 섹션.
2. 캡처된 URL 목록에서 다운로드 버튼 클릭.

### Discord 커맨드로 다운로드

캡처된 master URL 또는 Space URL로 직접 다운로드:

```
/download-space url:https://prod-fastly-*.video.pscp.tv/.../master_playlist.m3u8
```
또는 Space URL로:
```
/download-space url:https://x.com/i/spaces/1BdGYyg...
```

다운로드 완료 후 Discord에 완료 알림이 발송됩니다.

---

## 쿠키 만료 대응

### 만료 감지 알림

쿠키 유효성을 24시간마다 자동 검증합니다. 만료 감지 시 Discord에 알림이 발송됩니다.

### 쿠키 갱신 방법

1. 브라우저에서 x.com에 재로그인합니다.
2. 1단계를 반복하여 새 쿠키 파일을 추출합니다.
3. Settings → 인증 탭에서 새 파일을 업로드합니다.

### 쿠키 상태 수동 확인

```
GET /api/settings/cookie-status
POST /api/settings/cookie-status/check  # 즉시 검증
```

---

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| `auth_token/ct0를 찾을 수 없습니다` | 쿠키 파일 형식 오류 | Netscape 형식 파일인지 확인, `auth_token` 항목 있는지 확인 |
| `401 쿠키 인증 만료` | 쿠키 만료 | 브라우저에서 쿠키 재추출 후 업로드 |
| `429 레이트 리밋` | 단시간 과다 요청 | 30분 후 재시도 |
| 다운로드 파일이 비어있음 | Space 녹음 만료 또는 비공개 | 백업 `.txt` 파일의 URL 확인, 쿠키 갱신 |
| `Space URL에서 space_id 추출 불가` | 잘못된 URL 형식 | `https://x.com/i/spaces/...` 형식 확인 |

---

## 백업 파일 활용

Space 감지 시 자동으로 생성되는 `.txt` 파일에는 수동 다운로드 명령어가 포함됩니다:

```
{저장경로}/x_spaces_urls/elonmusk_1AbcDef123_20260328_150000.txt
```

파일 내용 예시:
```
Channel: elonmusk
Title: AMA about X
Space ID: 1AbcDef123
Captured at: 2026-03-28T15:00:00
Master URL: https://prod-fastly-ap-northeast-2.video.pscp.tv/.../master_playlist.m3u8

# yt-dlp 수동 다운로드 명령어:
yt-dlp --cookies x.com.txt --format bestaudio "https://prod-fastly-..."
```

녹화에 실패했더라도 이 파일의 URL로 직접 다운로드할 수 있습니다 (약 30일 유효).
