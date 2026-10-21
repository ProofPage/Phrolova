<h1 align="center">Phrolova</h1>

<p align="center">
  <b>Modern, self-hosted live-stream recorder & video downloader with an eight-language web dashboard.</b>
  <br>
  Continuous channel monitoring, lossless HLS/DASH capture, CHZZK live Time Machine, and universal cookie authentication.
</p>

<p align="center">
  <a href="https://github.com/ProofPage/Phrolova/releases/latest"><img alt="Release" src="https://img.shields.io/github/v/release/ProofPage/Phrolova?style=flat-square&color=blue"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-green?style=flat-square"></a>
  <a href="https://github.com/ProofPage/Phrolova/releases/latest"><img alt="Platform" src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey?style=flat-square"></a>
  <a href="https://github.com/ProofPage/Phrolova/releases/latest"><img alt="Python" src="https://img.shields.io/badge/python-3.14%2B%20GIL--safe-blue?style=flat-square"></a>
</p>

<p align="center">
  <a href="#quick-start"><b>Download & Quick Start ↓</b></a> ·
  <a href="#key-highlights"><b>Highlights</b></a> ·
  <a href="#supported-platforms"><b>Supported Platforms</b></a> ·
  <a href="docs/release-notes/v2.2.0.md"><b>v2.2.0 Release Notes</b></a>
</p>

---

## Key Highlights

- **Automatic Live-First Channel Sorting**: Monitored channels that go live automatically float to the top of your dashboard in alphabetical order. Toggle between *Live first*, *Name*, and *Manual drag-and-drop* order with a single click.
- **Resilient Lossless Recording**: Native Streamlink and custom yt-dlp pipelines capture original HLS/DASH media without re-encoding. Dynamic handling of YouTube 302/307 edge redirects prevents stream interruptions.
- **CHZZK Time Machine & Akamai CDN**: Rewind live CHZZK broadcasts from the very start or configure offsets, with prioritized Akamai low-latency CDN connectivity.
- **Universal Cookie Management**:
  - Full compatibility with Cookie-Editor exports (automatic `#HttpOnly_` stripping).
  - One-click raw cookie header pasting (`Cookie: ...`) without saving files.
  - Direct, one-click cookie import from local browsers (Chrome, Edge, Whale, Brave, Firefox).
  - Real-time login session status verification with clean status badges.
- **Comprehensive Media Toolbox**: FFmpeg stream remuxing to MKV/MP4, automatic part file preservation, FFprobe stream integrity inspection, and retry management.
- **Modern Responsive Dashboard**: Built with React, Vite, and Tailwind CSS. Native support for 8 languages (**Korean, English, Japanese, Simplified Chinese, Traditional Chinese, German, Spanish, Russian**).
- **Persistent Analytics & Discord Alerts**: In-depth storage metrics, clean channel history aggregation, and real-time Discord bot/webhook broadcast notifications.

---

## Supported Platforms

Availability depends on stream provider policies and account privileges.

| Platform | Live Monitoring | VODs & Clips | Authentication & Notes |
| :--- | :---: | :---: | :--- |
| **Chzzk (치지직)** | ✔ | ✔ | Naver cookie/session for 1080p+ & adult streams. Supports `chzzk.naver.com` and `m.chzzk.naver.com`. |
| **YouTube (유튜브)** | ✔ | ✔ | Cookie support for member streams. Supports `/live/<id>`, `/watch?v=<id>`, `/shorts/<id>`, and `@handle`. |
| **Twitch (트위치)** | ✔ | ✔ | Netscape cookies for sub-only streams. Optional TTV-AB ad-blocking toggle. |
| **Rplay (알플레이)** | ✔ | ✔ | Session import or email login. Supports 24-char OID, `/creatorhome/<id>`, and custom `/c/<handle>`. |
| **TwitCast (트위캐스)** | ✔ | ✔ | Low-latency stream monitoring, HLS capture, login-wall dummy detection, and browser cookie auth. |
| **Kick** | ✔ | ✔ | Streamlink live capture; cookie import for sub-only qualities. |
| **Bilibili** | ✔ | ✔ | Room monitoring, HLS capture, BV/av video downloads with cookie auth. |
| **TikTok** | ✔ | ✔ | Streamlink live capture, frame previews, and short share link parsing. |
| **PandaTV (팬더티비)**| ✔ | — | Streamlink live monitoring with username/password or Netscape cookie login. |
| **PopkonTV (팝콘티비)**| ✔ | ✔ | Live monitoring, password-protected rooms, and VOD queue integration. |
| **CIME (씨미)** | ✔ | ✔ | MCO email login or cookies; granted UHD/4K quality capture. |
| **Specialized Video** | — | ✔ | MissAV, AV19 (Node.js WASM decoder), YamiKorea, and episode-based series sites. |

---

## Quick Start

### 1. Windows (Recommended Standalone Executable)

Download the pre-compiled, self-contained single binary from the latest release:

1. Download **`Phrolova-v2.2.1-windows-x64.exe`** from [GitHub Releases](https://github.com/ProofPage/Phrolova/releases/latest).
2. Run the executable. It automatically unpacks required tools and launches the background service.
3. Open your browser and navigate to **`http://127.0.0.1:8000`** to access the dashboard.

> **Security Note**: Phrolova is local-first. Keep the default binding on `127.0.0.1:8000`. Do not expose it to public networks without reverse proxy authentication.

---

### 2. Docker / Docker Compose (Recommended for NAS & Linux Servers)

Run Phrolova effortlessly in a containerized environment with all dependencies (FFmpeg, Node.js WASM decoder, Python 3.14) bundled:

```bash
# Clone the repository
git clone https://github.com/ProofPage/Phrolova.git
cd Phrolova

# Start with Docker Compose
docker compose up -d
```

The web dashboard will be available at `http://localhost:8000`. Recorded streams and database states are persisted in `./downloads` and `./data`.

---

### 3. Running from Source (Linux / macOS / Windows)

#### Prerequisites
- **Python 3.14+** (standard GIL)
- **Node.js 22+** & **npm**
- **FFmpeg** installed and accessible in `PATH`

#### Clone & Install
```bash
# Clone the repository
git clone https://github.com/ProofPage/Phrolova.git
cd Phrolova

# Setup Python backend
cd backend
python -m venv .venv
# On Windows: .venv\Scripts\activate | On Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

# Build Frontend
cd ../frontend
npm install
npm run build

# Start Phrolova
cd ../backend
python run.py
```

The web dashboard is accessible at `http://127.0.0.1:8000`.

---

## Configuration & Architecture

```
Phrolova Architecture
├── Frontend (React 19 + TypeScript + Vite + Tailwind CSS)
│   ├── Dashboard (Live channel cards, auto reorder, status filters, stream preview)
│   ├── VOD Downloader (Multi-task queue, speed controls, format selection)
│   ├── Analytics & Stats (Unified storage & channel duration metrics)
│   └── Settings (Universal cookie management, FFmpeg/Deno runtime config)
│
└── Backend (FastAPI + AsyncIO + Python 3.14)
    ├── Engine (Live stream monitors, Streamlink / yt-dlp pipelines)
    ├── Auth (Browser cookie extraction, Netscape parsers, credential vault)
    ├── Finalizer (FFmpeg remuxer, integrity verifier, disk space monitor)
    └── Storage (SQLite persistence with auto-migration, event bus)
```

---

## License

Phrolova is licensed under the [MIT License](LICENSE). Built for personal media archiving and research purposes.


For MissAV, paste an individual `/ko/<slug>` video link, not the `/dm270/ko` homepage. The integration uses the observed main-player HLS stream and standard MPEG-TS segments without stripping bytes. A short queued MP4 sample was verified; full-length downloads of every video are not certified. Access challenges, rate limits, and unobserved encryption or advertisement protocols stop with an error instead of triggering mirror or bypass attempts.

CIME (MCO), HearHeart, Animaru and Anilife support account sign-in; PandaTV and PopkonTV support username/password sign-in under **Settings → Authentication**, alongside the existing RPLAY login. Passwords are not saved and the input is cleared after each attempt. Only issued, platform-scoped cookies are registered after session verification. Existing cookies remain unchanged if login or storage fails. Social accounts, CAPTCHA and additional verification require official-site sign-in followed by cookie import. See the release notes for the current production-account validation scope.

- **Episode sources:** paste a work link in **Videos**, then select up to 100 listed episodes. Available qualities and subtitles follow the source; unavailable episodes are not guessed. See [episode adapters](docs/video-site-adapters.md) for source-specific details and validation limits.
- **Bilibili:** live rooms accept a numeric ID or `live.bilibili.com/<room>`; videos accept BV/av IDs and `b23.tv` links. `?p=2` selects one part. Advertised quality IDs are retained, and popularity is not presented as a viewer count.
- **PandaTV:** public broadcasts can work without cookies; identity- or account-required broadcasts need the appropriate account. See [PandaTV support](docs/pandalive-support.md).
- **PopkonTV:** use the full live link to retain its partner code, or `channel@partner`. Room passwords are held only until exit. Server playback denials remain errors. See [PopkonTV support](docs/popkontv-support.md).
- **RPLAY:** import session JSON or use the account login form for restricted content. Netscape cookies do not contain the site's IndexedDB session. Only server-granted, non-DRM media is downloaded. See [RPLAY support](docs/rplay-support.md).
- **YouTube:** public video extraction starts without cookies and retries recognized authentication failures with registered cookies. Channel imports skip live/upcoming entries and already queued non-error tasks. Video authentication does not establish authenticated automatic live recording. Native live capture needs supported HLS; SABR/DASH preferences do not add SABR-only or DASH-only live capture. Bot challenges and HTTP 429 can affect public content too; reduce requests and check the server connection. See [YouTube access guidance](docs/youtube-public-access.md).
- **Kick:** account cookies can expose sign-in-only qualities, but only advertised formats are offered; account authorization is not forwarded to unrelated media CDNs. See [Kick support](docs/kick-support.md).

### CHZZK live Time Machine

Time Machine records an **ongoing live broadcast**, not a separate VOD. Phrolova reads the platform's advertised replay window, saves the selected starting point, catches up and continues receiving the live broadcast.

- Where CHZZK provides a full window, up to **3,600 seconds** of earlier live media can be available. A newer broadcast can be saved from its beginning if the server still exposes that first segment.
- Use **Settings → Downloads → recording mode** to select standard playback, prefer Time Machine with standard fallback, or require Time Machine. The default is `force-timemachine`.
- The start offset is measured from the beginning of the available Time Machine window. `0` selects its earliest available segment; it does not promise a segment the platform no longer serves.
- Available history is channel-dependent and may be shorter than an hour.
- CHZZK live recording has **no fixed MB/s cap or artificial replay-speed limit**. Shared in-flight requests, bounded prefetch/recovery work and independent recording readers avoid redundant transfers and shared-thread starvation. Catch-up can temporarily use substantial bandwidth; simultaneous recordings still require sufficient network and disk capacity.
- Recovery preserves segment order. Discontinuities or initialization changes create a file boundary rather than appending incompatible bytes to an existing original.

### CHZZK encrypted playback and CIME UHD

For CHZZK VODs marked `encryptionType: "AES"`, Phrolova reads the dedicated playback manifest and uses the **advertised AES-128 HLS** rendition instead of treating DASH-SEA as a supported DASH download. Native decryption requests the provider's key through the normal account cookie jar. Live AES key requests use account credentials only on the official HTTPS CHZZK API origin, never on a media CDN. Register `NID_AUT` and `NID_SES` under **Settings → Authentication → CHZZK** when the server requires an account. Subscription/viewing decisions remain with the server; encryption alone is not a subscription check.

Actual encrypted VOD metadata and advertised 144p/720p/1080p qualities have been checked. Authenticated-key handling and exact decrypted bytes are covered by local media tests; a full account-authenticated production encrypted VOD download has not been verified in the release test environment. Unsupported protection systems are not treated as AES-128.

CIME records advertised UHD/4K qualities when the registered account is granted UHD viewing. Register that account's cookies in Phrolova, separately from signing in to a browser. The adapter obtains and renews the normal UHD playback cookies, keeps their scope restricted to the appropriate playback servers and preserves native source media.

### Recording pipeline

```text
Channel monitoring → Streamlink capture → source file
                                              ↓ after capture closes
                                  FFmpeg finalization → FFprobe inspection
                                              ↓
                                       MKV or MP4 archive
```

Phrolova prefers TS capture and preserves native fMP4/CMAF when TS is unavailable. Finalization starts after capture stops. MKV is the default final container; MP4 is also available. Source retention is configurable, and failed processing preserves recoverable source data. Download completion and media inspection have separate statuses, so a failed inspection does not delete a completed download.

## Quick start

| System | Distribution | Requirements |
| --- | --- | --- |
| Windows x64 | PyInstaller `.exe` | No separate Python installation; bundled runtime, dashboard, Streamlink and Node.js; external FFmpeg/FFprobe |
| Windows x64 | Source | Standard-GIL Python 3.14.8+, Node.js 22+ with npm, FFmpeg/FFprobe 6+ |
| Linux x64 / ARM64 | Source | Bash, Git, standard-GIL Python 3.14.8+, Node.js 22+ with npm, FFmpeg/FFprobe 6+ and `ps` |
| macOS Apple Silicon / Intel | Source | Homebrew, Git, standard-GIL Python 3.14.8+, Node.js 22+ and FFmpeg/FFprobe 6+ |
| Android / native Termux | Source | Current Termux packages and native build tools; the installer selects the Termux dependency profile |
| Linux under Termux proot | Source | Linux dependencies inside the guest; set `PHROLOVA_ENVIRONMENT=termux-proot` |

The repository distributes a Windows executable and source archives. It does not ship macOS application bundles, Android APKs or Docker images. See [platform support](docs/native-platform-support.md) for implementation and validation scope.

**Python baseline:** standard-GIL Python **3.14.8** is the supported baseline; older versions and free-threaded execution are not supported. Python **3.15 is experimental**, even though its Linux/Windows checks passed for v2.1.8. This does not guarantee future dependency compatibility. The Termux profile is checked on Linux ARM64, not on an Android device.

The repository and published release files are public. You can clone the source or download the Windows app without signing in to GitHub.

### Windows packaged app

1. Download `Phrolova-v<version>-windows-x64.exe` and `SHA256SUMS.txt` from [the latest release](https://github.com/ProofPage/Phrolova/releases/latest).
2. Place the executable in a writable folder. Install **both** `ffmpeg.exe` and `ffprobe.exe` on `PATH`, or place them in a `bin` folder beside the app.
3. Launch Phrolova. Startup checks dependencies and attempts to download `yt-dlp.exe` into `bin` if it is missing. You can place that executable there manually instead.
4. Open <http://127.0.0.1:8000> and complete setup. The tray menu opens the dashboard or exits the app.

Keep the app in that writable folder: its configuration, data, logs and tools live beside it. The packaged app does **not** need a separately installed Python. For a Windows source checkout, use the [development setup](#development) instead.

Verify the downloaded file in PowerShell, using its actual filename, and compare the result with `SHA256SUMS.txt`:

```powershell
Get-FileHash -LiteralPath (Read-Host 'Downloaded executable path') -Algorithm SHA256
```

### Linux

Install Bash, Git and curl using your distribution's package manager, then run:

```bash
git clone https://github.com/ProofPage/Phrolova.git "$HOME/Phrolova"
cd "$HOME/Phrolova"
bash scripts/manage.sh install
bash scripts/manage.sh start
```

The manager prepares dependencies, `.venv`, the production dashboard and the `phrolova` command. It supports apt, dnf/yum, pacman and apk. Distributions with an older default Python need a Python 3.14.8+ interpreter first. An active systemd installation offers optional service registration; otherwise the server runs in the foreground.

See the [Linux guide](docs/linux-guide.md) for manual installation and service management.

### macOS

Install [Homebrew](https://brew.sh), then use a regular user terminal:

```bash
brew install git python@3.14 node@22 ffmpeg
git clone https://github.com/ProofPage/Phrolova.git "$HOME/Phrolova"
cd "$HOME/Phrolova"
bash scripts/manage.sh install
bash scripts/manage.sh start
```

The manager finds versioned Homebrew Python/Node under `/opt/homebrew` or `/usr/local`. The server runs in the foreground. See the [macOS guide](docs/macos-guide.md) for manual installation, background sessions and updates.

### Android / Termux

Use a current Termux build from a source listed in the [official installation instructions](https://github.com/termux/termux-app#installation). Keep the app and virtual environment inside Termux's private home directory:

```bash
pkg update
pkg install -y git
cd "$HOME"
git clone https://github.com/ProofPage/Phrolova.git
cd Phrolova
bash scripts/install-termux.sh
bash scripts/manage.sh start
```

The installer prepares Python, Node.js LTS, FFmpeg and native build dependencies. It uses `backend/requirements-termux.txt` with plain Uvicorn, keeps Termux-managed pip intact and checks dependency imports. Some dependencies compile on the device.

Open <http://127.0.0.1:8000> in the Android browser. Use `termux-setup-storage` if media should go to shared storage; keep the app, database and cookies in private storage. The [Termux guide](docs/termux-guide.md) covers permissions, proot, background execution and Android power management.

## First run

1. Choose separate live/video folders, recording quality and the final container. Saving setup creates missing folders.
2. Choose your language in **Settings → Appearance**.
3. Configure account authentication in **Settings → Authentication** when needed: supported account login forms, platform cookies, CHZZK `NID_AUT`/`NID_SES`, or an RPLAY session JSON. Browser sign-in is separate from Phrolova's server.
4. Add channels in **Live**, review recording preferences and enable automatic recording or start manually.
5. Add links in **Videos**, choose quality and start downloading. A YouTube channel URL or `@handle` starts a background import.
6. Review **Statistics**, **Logs**, processing history and tool status in **Settings → Information**.

Files are stored on the machine running Phrolova. Folder-open actions target that host; headless systems and remote browser sessions receive the path instead of opening a local desktop folder.

## Configuration

Use the dashboard for everyday settings. For file-based setup, copy [`.env.example`](.env.example) to a **new** root `.env` and edit it. A nonempty `DOWNLOAD_DIR` marks setup complete; leave `.env` absent to use the wizard.

Source installations read root `.env`, with `backend/.env` as a legacy fallback. Packaged Windows releases use `.env` beside the executable. Environment variables take precedence. Restart after manually editing `.env` or changing server/Discord bot credentials.

| Setting | Default or purpose |
| --- | --- |
| `HOST`, `PORT` | `127.0.0.1`, `8000` |
| `FFMPEG_PATH`, `FFPROBE_PATH` | `ffmpeg`, `ffprobe`; explicit executable paths are supported |
| `DOWNLOAD_DIR` | `./recordings`; fallback storage location |
| `LIVE_DOWNLOAD_DIR`, `VOD_DOWNLOAD_DIR` | Separate live/video paths |
| `RECORDING_QUALITY`, `LIVE_FORMAT` | `best`, `mkv` |
| `MONITOR_INTERVAL`, `MAX_RECORD_RETRIES` | `60` seconds, `3` retries |
| `CHZZK_STREAM_MODE`, `CHZZK_TIME_MACHINE_OFFSET` | `force-timemachine`, `0` |
| `CHZZK_LIVE_CDN`, `CHZZK_VOD_CDN` | `akamai`; `default` selects Naver CDN |
| `VOD_MAX_CONCURRENT`, `VOD_DEFAULT_QUALITY` | `5`, `best` |
| `VOD_FORMAT`, `VOD_MAX_SPEED` | `mp4`, `0` for unlimited speed in MB/s |
| `KEEP_DOWNLOAD_PARTS` | `false` |
| `FILE_INSPECTION_TIMEOUT` | `120` seconds; allowed range 1–600 |
| `YOUTUBE_COOKIE_FILE`, `CIME_COOKIE_FILE`, `KICK_COOKIE_FILE`, `TWITCH_COOKIE_FILE`, `TIKTOK_COOKIE_FILE`, `BILIBILI_COOKIE_FILE`, `PANDALIVE_COOKIE_FILE`, `POPKONTV_COOKIE_FILE` | Optional Netscape cookie files; upload through Settings → Authentication |
| `TWITCH_PROXY_ENABLED` | `false`; optional ReYohoho live quality proxy. Enabling forwards the registered Twitch login token to third-party proxies as `auth=` in the URL. |

Use absolute media paths. Relative paths follow the working directory; the source manager starts from `backend/`. Enter actual paths in `.env` rather than relying on shell-variable expansion. Saved preferences are preserved when defaults change in a later release.


### Authentication and security

Browser sign-in does not authenticate the Phrolova server. Upload platform-scoped cookies or use a supported login form in **Settings → Authentication**. Keep cookies, session files, `.env` and backups private. Account, regional, subscription and identity restrictions remain the provider's decision; Phrolova does not bypass DRM, expired authorization or HTTP 403.

Twitch's **TTV-AB ad blocking** and **third-party quality proxy** are separate options, both off by default for new settings. Existing saved choices are preserved. Direct Twitch authentication uses the registered `auth-token`; OAuth headers are not forwarded to media CDNs.

**Quality-proxy privacy:** enabling the optional [ReYohoho-based proxy](https://github.com/reyohoho/twitch_quality_proxy/blob/userscript/twitch.user.js) sends the channel, your server's IP address and any registered Twitch `auth-token` to `proxy4.rte.net.ru`, `proxy7.rte.net.ru`, `proxy5.rte.net.ru` or `proxy6.rte.net.ru`. The token is included as `auth=` in the URL and can be retained by those operators; log masking cannot prevent this disclosure. Enable it only if you trust them. Without a cookie, proxy access is anonymous. It affects subsequent live quality lookups, previews and recordings—not running recordings or VOD/clip downloads. Unusable proxy responses fall back to direct access.

The dashboard/API has no built-in login. Keep the default loopback binding. For remote administration, use an SSH tunnel or protect access with an authenticated proxy/private network; do not expose an unprotected public endpoint:

```bash
ssh -N -L 8000:127.0.0.1:8000 user@server
```

Platform cookies and Discord command allowlists do not authenticate dashboard users.

## Updates and backups

Finish active recordings/downloads, stop Phrolova and back up configuration and data before updating.

- **Windows:** Replace the executable in the same folder. Keep `.env`, `data/`, `logs/`, `bin/` and media directories.
- **Source:** Run `phrolova update`, then start again for foreground installations. Updates track `main`. If local source changes block an update, the manager can stash them and reports the saved stash.
- **Legacy installations:** Databases are migrated through SQLite's backup API. Keep originals until you have verified the migration.

| Data | Source installation | Packaged Windows |
| --- | --- | --- |
| Configuration | Root `.env`; legacy `backend/.env` fallback | Adjacent `.env` |
| Database / uploaded cookies | `backend/data/` | Adjacent `data/` |
| Logs | Root `logs/` | Adjacent `logs/` |
| Media | Configured live/video folders | Configured live/video folders |

For a consistent backup, stop the server and copy the whole data directory. SQLite uses WAL; copying only `phrolova.db` while running can omit committed data. Interrupted video tasks return as retryable errors; continuation depends on the downloader and retained parts. An incompatible virtual environment is preserved in `.venv-backups/` before recreation.

### Source management commands

| Command | Action |
| --- | --- |
| `phrolova start` | Start the service or run in the foreground |
| `phrolova stop` | Stop this installation gracefully |
| `phrolova restart` | Wait for shutdown, then start again |
| `phrolova status` / `status --full` | Show server status / read-only diagnostics |
| `phrolova logs` | Follow the service journal or `logs/service.log` |
| `phrolova update` | Update source, dependencies and the dashboard |
| `phrolova service install` / `remove` | Manage Linux systemd registration when systemd is running |

Use `bash scripts/manage.sh <command>` if the registered command is outside `PATH`. macOS and native Termux use foreground execution or a session manager such as `tmux`.

## Discord

Configure the bot/webhook in **Settings → Notifications**. Invite the bot with `bot` and `applications.commands` scopes and permissions to send messages and embeds.

Commands: `/status`, `/list`, `/start channel_id`, `/stop channel_id`, `/rescan`, `/diag`, `/notify-test`. `/start` enables automatic recording for a channel; `/stop` disables it.

Set `DISCORD_COMMAND_USER_IDS` for a user allowlist and `DISCORD_COMMAND_CHANNEL_ID` for a channel restriction. If both are set, both must match. If neither is configured, the notification channel is used; commands are denied without an authorization setting. Failed bot delivery can fall back to the webhook, and queued notifications survive restarts until their TTL expires. See [`.env.example`](.env.example) for all options.

## Development

The backend uses **Python, FastAPI, Uvicorn and SQLite**. The dashboard uses **React 19, TypeScript, Vite and Tailwind CSS 4**. Streamlink captures live media; yt-dlp handles video extraction/downloads; FFmpeg/FFprobe finalize and inspect files.

With Python 3.14.8+ (standard GIL), Node.js 22+, npm and FFmpeg/FFprobe installed:

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
(cd frontend && npm ci && npm run build)
(cd backend && ../.venv/bin/python run.py)
```

On Windows, use a standard-GIL Python 3.14.8+ interpreter with `py -3.14 -m venv .venv`, then `.venv\Scripts\python.exe` for pip and the backend. Run `npm ci` and `npm run build` inside `frontend/` before starting `backend/run.py` from `backend/`. Older Python versions are rejected. Native Termux uses rolling system `python` and `backend/requirements-termux.txt`; install test tools separately if needed. `ffmpeg-python` does not install FFmpeg/FFprobe. Node.js remains needed for YouTube JavaScript processing after the dashboard is built.

For hot reload, run the backend and `npm run dev` in `frontend/` separately. Vite proxies `/api` and `/health` to port 8000. Production builds go directly into `backend/app/static`, served by FastAPI. Fixture previews test the interface without real recordings/downloads.

Before submitting changes:

```bash
(cd backend && ../.venv/bin/python -m pytest -q)
(cd frontend && npm run i18n:check && npm run i18n:test)
(cd frontend && npx tsc --noEmit -p tsconfig.json && npm run build)
bash -n scripts/manage.sh
bash -n scripts/install-termux.sh
bash -n scripts/healthcheck.sh
```

For v2.1.8, [all nine CI jobs passed](https://github.com/ProofPage/Phrolova/actions/runs/39541641103): Python 3.14.8 on Linux x64/ARM64, Windows x64 and macOS Apple Silicon/Intel; the Termux requirements profile on Linux ARM64/Python 3.14; experimental Python 3.15 on Linux and Windows; and frontend checks/build. These checks are not complete live-source certification. The Termux profile is not Android ABI or device validation. See the [release notes](docs/release-notes/v2.1.8.md) for release-build verification.

Build the Windows executable after the production dashboard:

```powershell
python -m pip install -r backend/requirements.txt pyinstaller pillow pystray
python -m PyInstaller --clean --noconfirm phrolova.spec
```

The build produces `dist/Phrolova.exe`, bundles Node.js and application icons, and leaves FFmpeg/FFprobe external. Release publication includes a Windows Defender scan and SHA-256 checksum file.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Dashboard is missing | Build `frontend/`; `backend/app/static/index.html` must exist |
| Tool is missing or fails | Inspect status and path in Settings → Information; install both FFmpeg and FFprobe |
| yt-dlp is missing | Install it in the app environment or put its executable in the adjacent `bin` folder |
| YouTube needs a JavaScript runtime | Keep Node.js 22+ available; restart after changing `PATH` |
| CHZZK Time Machine does not start at the broadcast beginning | Check recording mode, start offset and the window actually returned by CHZZK; some broadcasts expose less than an hour |
| Other recordings slow down during catch-up | Check network/disk capacity and concurrent work; CHZZK catch-up is uncapped, but duplicate media requests and unbounded recovery queues are avoided |
| CHZZK encrypted video needs an account | Register valid Naver cookies in Phrolova; a signed-in browser does not provide the server's key-request cookies |
| CIME UHD is missing | Register the account granted UHD viewing, then refresh available qualities; do not substitute a browser-only login |
| Folder does not open | Use the returned path on the machine running Phrolova |
| Port is in use | Check `phrolova status`, stop the old instance and wait for shutdown |
| Update check returns HTTP 404 | Confirm the release and repository URL, then retry in Settings → Information or use the public GitHub Releases page |
| Termux build fails | Check build tools, free space and the [Termux guide](docs/termux-guide.md) |

## Documentation

[Linux](docs/linux-guide.md) · [macOS](docs/macos-guide.md) · [Termux](docs/termux-guide.md) · [Platform support](docs/native-platform-support.md) · [Release history](docs/release-notes/README.md)

When following platform-specific instructions, use the Python baseline and validation scope documented above. The repository and release downloads are public.

FFmpeg/FFprobe are installed separately and follow their own licenses.
