# Phrolova

Self-hosted live recording and video downloads for **CHZZK, YouTube, SOOP and CIME**. Manage channels, preview broadcasts, verify recorded files, and review activity in one web dashboard.

[![CI](https://github.com/ProofPage/Phrolova/actions/workflows/ci.yml/badge.svg?branch=main&event=push)](https://github.com/ProofPage/Phrolova/actions/workflows/ci.yml)

[Releases](https://github.com/ProofPage/Phrolova/releases) · [Changelog](docs/CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [MIT License](LICENSE)

**Install:** [Windows](#windows) · [Linux](#linux) · [macOS](#macos) · [Android / Termux](#android--termux)

## What you can do

- **Live:** register channels, organize them with tags and filters, monitor broadcast status, and start recordings manually or automatically. Review viewers, recording duration, size, bitrate, retries and errors.
- **Videos:** download VODs, clips and supported external links; import a YouTube channel's available videos; select quality, limit concurrency/speed, and pause, resume, cancel or retry supported tasks.
- **Playback and verification:** preview broadcasts independently of recording, open completed files, inspect media with FFprobe and review verification separately from download completion.
- **Statistics:** see completed recording time/size, download totals, channel activity, recent sessions, disk capacity and separate live/video storage locations.
- **Logs:** browse original files, search/filter severity, follow live output and export a complete log file.
- **Settings:** configure storage, quality, filenames, containers, authentication, notifications and appearance. Tool versions and installation paths appear in Information.
- **Discord:** slash commands, bot/webhook notifications, retries and a persistent notification queue.
- **Eight languages:** 한국어 (default), English, 日本語, Español, Deutsch, 简体中文, 繁體中文 and Русский. Settings → Appearance applies the selected language immediately and remembers it in that browser; dates, numbers and quantities follow the locale. User content and technical logs retain their original text.

### Platforms

| Platform | Live monitoring / recording / preview | Video downloads | Authentication |
| --- | --- | --- | --- |
| CHZZK | Automatic/manual recording; standard and time-machine modes | VODs and clips | Naver cookies for content requiring authentication |
| YouTube | Automatic/manual recording and preview | Videos and channel imports | Netscape-format cookies for authenticated video access |
| SOOP | Automatic/manual recording and preview | VODs and multi-part videos | Platform cookies when required |
| CIME | Automatic/manual recording and preview | VODs and clips | Platform cookies when required |

The external-video option follows the extractors supported by yt-dlp. Playback, formats and account access depend on the source platform. YouTube channel import skips live/upcoming entries and avoids already queued non-error duplicates.

### Recording pipeline

**Live detection → Streamlink capture → TS → FFmpeg finalization → MKV (default) or MP4 → FFprobe verification.**

Streamlink preserves native fMP4/CMAF when the source cannot supply TS; after capture closes, FFmpeg normalizes it before finalization. Existing explicit format/quality preferences are preserved. The dashboard retains **MKV - Matroska** and **MP4 - MPEG-4** labels. Source TS retention is configurable; failed finalization preserves recoverable source data. Downloading uses the existing platform engines and yt-dlp.

## Requirements

| Environment | Installation and runtime |
| --- | --- |
| Windows x64 | Packaged `.exe`; external FFmpeg/FFprobe. Python, Streamlink, frontend and Node are bundled; startup locates or downloads `yt-dlp.exe` |
| Linux x86_64 / ARM64 | Source installation; Bash, Git, Python **3.12+**, Node.js **22+** with npm, FFmpeg and FFprobe **6+**, and `ps` |
| macOS Apple Silicon / Intel | Source installation with Homebrew, Bash, Git, Python **3.12+**, Node.js **22+**, FFmpeg/FFprobe **6+** |
| Native Android Termux | Termux packages plus `requirements-termux.txt`; Python **3.12+**, Node.js **22+**, FFmpeg/FFprobe **6+** and native build tools |
| Termux proot Linux | Linux dependencies and `requirements.txt` inside the guest; no systemd service unless systemd is actually running |

Python dependencies include `streamlink>=8.6.2,<9`, `yt-dlp[default]`, FastAPI, Uvicorn and discord.py. `ffmpeg-python` does **not** install FFmpeg or FFprobe. Node remains necessary for YouTube JavaScript processing after the UI build; [yt-dlp requires Node 22+](https://github.com/yt-dlp/yt-dlp/wiki/EJS).

Windows is the packaged release target. Linux, macOS and Termux run from source; this repository does not ship `.app`, `.dmg`, `.apk` or Docker images. See [platform implementation and validation](docs/native-platform-support.md) for the test matrix and device-test scope.

## Installation

The repository is currently **private**. Clone/download using a GitHub account with access. Configure a Git credential helper or use an authorized SSH key; anonymous `raw.githubusercontent.com` install links cannot access a private repository.

### Windows

1. Download `Phrolova-v<version>-windows-x64.exe` and `SHA256SUMS.txt` from [Releases](https://github.com/ProofPage/Phrolova/releases/latest).
2. Place the executable in a writable folder. Put `ffmpeg.exe` and `ffprobe.exe` in its adjacent `bin/` folder or on `PATH`.
3. Launch it. If `yt-dlp.exe` is missing, startup attempts to download it into `bin/`; it can also be placed there manually.
4. Open <http://127.0.0.1:8000> and complete setup. The tray menu opens the dashboard or exits the app.

To update, exit the app and replace the executable in the same folder. Retain `.env`, `data/`, `logs/`, `bin/` and media directories.

### Linux

Install Bash, Git and curl using your distribution's package manager, then:

```bash
git clone https://github.com/ProofPage/Phrolova.git "$HOME/Phrolova"
cd "$HOME/Phrolova"
bash scripts/manage.sh install
bash scripts/manage.sh start
```

The script prepares dependencies, `.venv`, the production frontend and the `phrolova` command. It supports apt, dnf/yum, pacman and apk. Python must be available at version 3.12+; older distributions require a suitable interpreter before installation. GNU/Linux static FFmpeg fallback is restricted to x86_64/ARM64 glibc environments; macOS, Android and Alpine use their own packages.

An active systemd installation offers optional `phrolova.service` registration. Otherwise `start` runs in the foreground; use Ctrl+C or `stop` from another terminal. See the [Linux guide](docs/linux-guide.md).

### macOS

Install [Homebrew](https://brew.sh), then use a regular user terminal:

```bash
brew install git python@3.12 node@22 ffmpeg
git clone https://github.com/ProofPage/Phrolova.git "$HOME/Phrolova"
cd "$HOME/Phrolova"
bash scripts/manage.sh install
bash scripts/manage.sh start
```

The manager resolves versioned Homebrew runtimes on both `/opt/homebrew` and `/usr/local`, including Node that is not linked into the default PATH. No GNU `readlink -f`, Linux `/proc` or systemd is needed. The server runs in the foreground; macOS Finder opens local completed-file locations using `open` / `open -R`.

See the [macOS guide](docs/macos-guide.md) for manual installation, background sessions and updates.

### Android / Termux

Use a current Termux installation from the sources listed in the [official Termux documentation](https://github.com/termux/termux-app#installation). Keep the repository and virtual environment in Termux's private `$HOME`:

```bash
pkg update
pkg install -y git
cd "$HOME"
git clone https://github.com/ProofPage/Phrolova.git
cd Phrolova
bash scripts/install-termux.sh
bash scripts/manage.sh start
```

The installer uses Termux's Python/pip, FFmpeg, Node.js LTS, Clang/Rust and other build dependencies. It selects `requirements-termux.txt` with plain Uvicorn rather than Linux-only standard extras, validates imports and registers the management command. It does not download Linux/Windows binaries or upgrade Termux-managed pip. Some Python dependencies compile on the device.

Open <http://127.0.0.1:8000> in the Android browser. Folder-open actions return the saved path rather than launching `xdg-open`. Use `termux-setup-storage` only if media should go to shared storage; keep the application, SQLite database and cookies inside private HOME.

For Ubuntu/Debian via proot-distro, set `PHROLOVA_ENVIRONMENT=termux-proot` inside the guest and follow the Linux installation. See the [Termux guide](docs/termux-guide.md) for background execution, shared storage and recovery.

### Manual source installation

On Linux/macOS with dependencies already installed:

```bash
cd "$HOME/Phrolova"
python3.12 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
.venv/bin/python -m pip check
(cd frontend && npm ci && npm run build)
cd backend
../.venv/bin/python run.py
```

On macOS, add `$(brew --prefix node@22)/bin` to PATH first and use `$(brew --prefix python@3.12)/bin/python3.12` if the versioned Python is not on PATH. Native Termux uses `python` and `backend/requirements-termux.txt` instead.

For Windows PowerShell source development:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
npm ci --prefix frontend
npm run build --prefix frontend
cd backend
..\.venv\Scripts\python.exe run.py
```

Vite builds directly into `backend/app/static`; there is no manual `dist` copy step. FastAPI serves the UI and API together at port 8000.

## First use

1. Complete the setup wizard with separate live/video paths, recording quality and final container. Missing folders are created when settings are saved.
2. Select your language in **Settings → Appearance**.
3. Register platform cookies in **Settings → Authentication** when the content requires them.
4. Add channels in **Live**, review recording preferences and enable automatic recording or start manually.
5. Add links in **Videos**, select quality and start downloading. A YouTube channel URL or `@handle` imports available videos in the background.
6. Review output in **Statistics**, **Logs** and **Settings → Information**. Media is stored on the server running Phrolova.

## Configuration

Use the dashboard for normal configuration. For file-based setup, copy [`.env.example`](.env.example) to a new root `.env` and edit it. A nonempty `DOWNLOAD_DIR` marks setup complete and skips the wizard; leave `.env` absent to use the wizard. Never overwrite an existing `.env` during installation/update.

Source installations resolve root `.env` first, then legacy `backend/.env`. Windows releases use `.env` beside the executable. Environment variables override file settings. Restart after manually editing `.env` or changing server/Discord bot credentials.

| Setting | Default / purpose |
| --- | --- |
| `HOST`, `PORT` | `127.0.0.1`, `8000` |
| `FFMPEG_PATH`, `FFPROBE_PATH` | `ffmpeg`, `ffprobe`; explicit paths, adjacent `bin/` and PATH are supported |
| `DOWNLOAD_DIR` | `./recordings`; fallback media path |
| `LIVE_DOWNLOAD_DIR`, `VOD_DOWNLOAD_DIR` | Separate live/video paths; existing fallback rules apply when empty |
| `RECORDING_QUALITY`, `LIVE_FORMAT` | `best`, `mkv`; MP4 can be selected |
| `MONITOR_INTERVAL`, `MAX_RECORD_RETRIES` | `60` seconds, `3` retries |
| `CHZZK_STREAM_MODE`, `CHZZK_TIME_MACHINE_OFFSET` | `force-timemachine`, `0`; settings expose available modes |
| `CHZZK_LIVE_CDN`, `CHZZK_VOD_CDN` | `akamai`; `default` selects Naver CDN |
| `VOD_MAX_CONCURRENT`, `VOD_DEFAULT_QUALITY` | `5`, `best`; concurrency changes apply without stopping active tasks |
| `VOD_FORMAT`, `VOD_MAX_SPEED` | `mp4`, `0` (unlimited MB/s) |
| `KEEP_DOWNLOAD_PARTS` | `false`; optional partial-file preservation |
| `FILE_INSPECTION_TIMEOUT` | `120` seconds; accepts 1–600 |

Use **absolute media paths** for consistent storage. Relative paths resolve against the working directory; the source manager starts from `backend/`. Existing media paths and saved preferences are preserved. Manual `.env` values should contain actual paths rather than assuming shell variable expansion.

For authentication, CHZZK uses `NID_AUT` / `NID_SES`; YouTube, SOOP and CIME use their corresponding `*_COOKIE_FILE` settings. Upload Netscape-format files in Settings. YouTube video downloads/imports retry with cookies after recognized authentication failures; this does not establish authenticated automatic YouTube live recording.

The dashboard/API has no built-in web login. The default loopback address is suitable for local use. For remote administration, keep that binding and use an SSH tunnel:

```bash
ssh -N -L 8000:127.0.0.1:8000 user@server
```

An externally exposed dashboard needs access control through an authenticated proxy or private network. Platform cookies and Discord command allowlists do not authenticate web API users.

## Management, updates and backup

| Command | Action |
| --- | --- |
| `phrolova start` | Start an installed service or run in the foreground |
| `phrolova stop` | Stop this installation's server gracefully |
| `phrolova restart` | Wait for stop, then start; slow shutdown prevents a duplicate restart |
| `phrolova status` / `status --full` | Server status / read-only diagnostics |
| `phrolova logs` | Follow service journal or `logs/service.log` |
| `phrolova update` | Pull `main`, rebuild changed source and refresh dependencies |
| `phrolova service install` / `remove` | Linux systemd registration/removal when systemd is running |

The same commands work as `bash scripts/manage.sh <command>` if the registered link is outside PATH. macOS and Termux do not receive a systemd service. For background sessions use `tmux`; Android additionally needs appropriate battery settings and optionally `termux-wake-lock`.

Before updating, finish active work and stop the server. Keep a backup, then run `phrolova update` and start again when using a foreground installation. The manager may stash local source changes blocking an update and reports the stash; inspect it if you maintain custom patches. Updates track `main`, rather than a pinned release tag.

An incompatible Python virtual environment is moved into `.venv-backups/` before recreation. Configuration, database, cookies and media stay in place.

| Data | Source installation | Windows release |
| --- | --- | --- |
| Configuration | Root `.env`; legacy `backend/.env` fallback | Adjacent `.env` |
| Database / uploaded cookies | `backend/data/` | Adjacent `data/` |
| Logs | Root `logs/` | Adjacent `logs/` |
| Media | Configured live/video directories | Configured live/video directories |

For backup, stop cleanly and copy `.env`, the whole data directory and needed media. SQLite uses WAL; copying only `phrolova.db` while running can omit committed WAL data. Existing legacy databases are migrated through SQLite backup while originals are retained. Interrupted video tasks restore as retryable errors; continuation depends on the downloader and remaining partial files.

## Discord

Configure the bot/webhook in **Settings → Notifications**. Invite the bot with `bot` and `applications.commands` scopes and channel permissions for messages/embeds.

Commands: `/status`, `/list`, `/start channel_id`, `/stop channel_id`, `/rescan`, `/diag`, `/notify-test`. `/start` enables automatic recording; `/stop` disables it for the selected channel.

`DISCORD_COMMAND_USER_IDS` sets a user allowlist; `DISCORD_COMMAND_CHANNEL_ID` sets the allowed channel. When both are configured both must match. If neither is explicit, the notification channel is used; with no authorization setting, commands are denied. Bot delivery falls back to the webhook and pending notifications survive restart until their TTL expires. See the full variable list in [`.env.example`](.env.example).

## Development and validation

The backend uses **Python, FastAPI, Uvicorn and SQLite**. The dashboard uses **React 19, TypeScript, Vite and Tailwind CSS 4**. Platform engines live in `backend/app/engine/`; API routes in `backend/app/api/`; common paths/settings/runtime handling in `backend/app/core/`; UI and eight locale resources in `frontend/src/`.

```bash
.venv/bin/python -m pip install -r backend/requirements-dev.txt
(cd backend && ../.venv/bin/python -m pytest -q)
(cd frontend && npm ci && npm run i18n:check && npm run i18n:test)
(cd frontend && npx tsc --noEmit -p tsconfig.json && npm run build)
bash -n scripts/manage.sh
bash -n scripts/install-termux.sh
bash -n scripts/healthcheck.sh
```

CI runs backend tests on Linux x64/ARM64, Windows x64 and macOS Apple Silicon/Intel, plus Python 3.14 with the Termux dependency profile on Linux ARM64. That profile checks dependency compatibility; Android-native build/install and device endurance require a real Termux device. Frontend CI checks locale resources, formatting, TypeScript and the production build.

For development, run `python run.py` from `backend/` and `npm run dev` from `frontend/` in separate terminals. Vite proxies `/api` and `/health` to the backend. Preview fixture mode is for interface development; it does not run real recordings/downloads or prove platform playback access.

## Troubleshooting

- **UI missing:** build `frontend/`; output must exist in `backend/app/static`.
- **Python too old:** install Python 3.12+ and rerun installation. Older Debian/RHEL defaults may not meet the requirement.
- **YouTube runtime missing:** keep Node 22+ or a supported Deno installed; check PATH after restarting the server.
- **FFmpeg/FFprobe not found:** inspect resolved paths in Information; both are separate executables.
- **Folder cannot open:** file-manager actions execute on the server. Headless Linux and Termux provide the path; use a file manager on that host.
- **Address already in use:** check `phrolova status`, stop the existing instance and wait for finalization before starting another.
- **Private repository update check fails:** anonymous GitHub release checks cannot read private release metadata; update through an authorized Git checkout or download.
- **Termux build fails:** verify Clang/Rust/native packages and available storage; consult [Termux installation details](docs/termux-guide.md). Do not substitute Linux wheels for Android dependencies.

## Documentation and contributing

[Linux](docs/linux-guide.md) · [macOS](docs/macos-guide.md) · [Termux](docs/termux-guide.md) · [Platform validation](docs/native-platform-support.md) · [Changelog](docs/CHANGELOG.md) · [Contribution guide](CONTRIBUTING.md)

Preserve API contracts, user data, recording/download behavior and existing line endings when contributing. Report checks actually run; do not restore retired functionality during unrelated work.

## License

[MIT](LICENSE). Copyright (c) 2026 Serian (github.com/eruminyu). Original author attribution is preserved; subsequent contributions are recorded in Git history and the changelog.
