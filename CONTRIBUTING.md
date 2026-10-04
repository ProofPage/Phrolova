# 기여 가이드

설치와 실행 방법은 [README](README.md)에 있습니다. 이 문서는 **코드를 고칠 때 지켜야 할 규칙**만 다룹니다.

## 먼저 알아둘 것

Rookery는 실제로 방송을 녹화하는 데 쓰이고 있습니다. 동작이 깨지면 사용자의 녹화가 실패하고,
지나간 라이브는 다시 받을 수 없습니다. 리팩터링이든 기능 추가든 **기존 동작을 깨지 않는 것**이
가장 중요합니다.

## 검증

PR을 올리기 전에 세 가지를 모두 실행하고 결과를 확인하세요.

```bash
python -m pytest -c backend/pytest.ini backend/tests
```

```bash
cd frontend && npx tsc --noEmit -p tsconfig.json
```

```bash
cd frontend && npm run build
```

**기준선은 `274 passed, 29 skipped`입니다.** 통과 수가 줄었다면 무언가 깨진 것이니
그대로 올리지 마세요.

## 규칙

### API 계약을 바꾸지 않습니다

엔드포인트 경로, 필드명, 페이로드 구조를 그대로 유지하세요. **필드 추가는 괜찮습니다.**

exe로 배포된 구버전 클라이언트가 같은 API를 호출합니다. 필드명 하나만 바뀌어도
업데이트하지 않은 사용자의 화면이 깨집니다.

`backend/tests/test_api_surface.py`가 등록된 라우트 전체를 고정하고 있습니다.
라우트는 데코레이터로 등록돼서, 파일을 옮기다 빠뜨려도 파싱과 import는 그대로
성공합니다. 경로를 의도적으로 바꿨다면 그 목록도 함께 고치세요 — 그 diff가
"API를 바꿨다"는 기록이 됩니다.

### 주석은 한국어로, '왜'를 적습니다

무엇을 하는지는 코드가 이미 말하고 있습니다. 주석에는 **왜 그렇게 했는지**를 적으세요.
특히 우회 코드나 직관에 어긋나는 처리에는 배경을 남겨야 합니다.

```python
# 치지직이 ABR_HLS로 전송 방식을 바꾸면서 sourceURL 키가 사라졌다.
# yt-dlp로 넘겨 대응한다.
```

### 줄바꿈은 건드리는 파일의 방식을 따릅니다

저장소 대부분이 CRLF입니다. 파일을 열었을 때의 방식을 그대로 유지하세요.

`.gitattributes`가 두 종류만 고정합니다.

- `*.sh` → **LF**. 리눅스에서 `curl | bash`로 실행되는데, CRLF면 셔뱅이 `bash\r`로 읽혀
  설치 자체가 실패합니다.
- `*.bat` `*.cmd` `*.ps1` → **CRLF**. cmd.exe가 LF면 라벨과 명령을 잘못 파싱합니다.

### `git add --renormalize`를 쓰지 않습니다

`.gitattributes`와 무관하게 저장소 전체를 재정규화합니다. 건드리지도 않은 파일 50여 개가
줄바꿈만 바뀐 채 staged 되어 diff가 부풀고 리뷰가 불가능해집니다.

### UI는 테마 토큰을 씁니다

원시 색상(`zinc-500` 같은 것) 대신 `frontend/src/index.css`의 `@theme` 토큰을 쓰세요.

- 배경 — `bg-surface-*`
- 텍스트 — `text-ink`, `text-ink-muted`, `text-ink-faint`
- 테두리 — `border-line`, `border-line-strong`

Tailwind CSS v4라 `tailwind.config.js`가 없습니다. 토큰은 전부 `index.css`에 있습니다.

### 공통 UI는 primitives에 넣습니다

재사용할 컴포넌트는 `frontend/src/components/ui/primitives.tsx`에 추가하세요.
페이지 파일 안에서 로컬 컴포넌트를 만들면 같은 버튼이 화면마다 조금씩 달라집니다.

### 커밋

제목은 영어, 본문은 한국어로 씁니다.

```
fix(discord): surface command failures instead of hanging

명령 실행이 실패해도 예외를 삼키고 대기 상태로 남아 있어서
사용자가 원인을 알 수 없었다. 실패를 그대로 노출하도록 바꿨다.
```

## 환경에서 자주 걸리는 것

**셸에 node가 없을 때** — Windows에서 PATH에 잡히지 않는 경우가 있습니다.
`C:\Program Files\nodejs`를 직접 지정하세요.

**pytest가 무더기로 실패할 때** — `PermissionError: ...Temp\pytest-of-user`가 뜨면
코드 문제가 아니라 임시 디렉터리 권한 문제입니다. 쓰기 가능한 경로를 지정해 우회하세요.

```bash
python -m pytest -c backend/pytest.ini backend/tests --basetemp=/path/to/writable
```

## 설정과 데이터

설정은 프로젝트 루트의 `.env`에서 읽습니다
(`backend/app/core/config.py`의 `resolve_env_path`).

`.env`, `backend/data/`, `.venv`, `node_modules`, `backend/app/static/`은 gitignore 대상입니다.
`backend/app/static/`은 프론트엔드 빌드 산출물이라 커밋하지 않습니다.

## exe 빌드

`rookery.spec`이 PyInstaller 스펙입니다. 프론트엔드를 먼저 빌드해야 웹 UI가 exe에 포함됩니다.

```bash
pyinstaller rookery.spec --clean
```

ffmpeg는 라이선스 문제로 번들하지 않습니다. 실행 시 `backend/run.py`의 의존성 검사가
자동으로 감지해 안내합니다.
