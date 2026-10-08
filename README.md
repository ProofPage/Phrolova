# Phrolova

**Self-hosted live recording, video downloads, and X Spaces archiving.**

[![CI](https://github.com/ProofPage/Phrolova/actions/workflows/ci.yml/badge.svg?branch=main&event=push)](https://github.com/ProofPage/Phrolova/actions/workflows/ci.yml)

[Repository](https://github.com/ProofPage/Phrolova) · [Releases](https://github.com/ProofPage/Phrolova/releases) · [Changelog](docs/CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [MIT License](LICENSE)

Phrolova monitors CHZZK and YouTube channels, records live broadcasts, and manages video downloads through a browser-based dashboard. It also provides cookie-authenticated X Spaces capture and audio archiving, with Discord commands and notifications for remote operation.

Run it on your own computer or server to keep media, channel settings, and recording history together. The backend writes files to storage you control; the dashboard provides a shared view of live activity, downloads, chat logs, and settings.

## Contents

- [Features](#features)
- [Supported platforms](#supported-platforms)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Discord integration](#discord-integration)
- [Storage and backups](#storage-and-backups)
- [Architecture](#architecture)
- [Project structure](#project-structure)
- [Development](#development)
- [Limitations and troubleshooting](#limitations-and-troubleshooting)
- [Additional documentation](#additional-documentation)
- [Contributing](#contributing)
- [License and attribution](#license-and-attribution)

## Features

### Live monitoring and recording

- Monitor registered CHZZK and YouTube channels and automatically record detected broadcasts when enabled for each channel.
- Organize channels with tags, filters, and adjustable display order. Inspect live status, recording duration, output size, and errors.
- Select a preferred recording quality and TS, MKV, or MP4 output. Use separate live and video download directories and customizable filenames.
- Preview CHZZK and YouTube streams independently of recording, subject to upstream playback availability.
- For CHZZK, choose standard streaming or time-machine playback, optionally save a preview image, and record all broadcasts, only matching watch-alongs, or broadcasts excluding watch-alongs.
- Optionally archive CHZZK chat alongside recordings as JSONL files and browse or search those logs in the dashboard.
- Retry interrupted CHZZK and YouTube recordings while the broadcast remains live, up to the configured retry limit.

Manual start/stop controls are implemented, but the current YouTube web control route has a limitation; see [Known limitations](#known-limitations).

### Video downloads

- Download CHZZK VODs and clips, and individual YouTube videos.
- Import available videos from a YouTube channel into the download queue in the background. Import skips entries identified as live or upcoming and avoids duplicates already represented by non-error tasks.
- Track progress, speed, and estimated time where the downloader reports them. Pause, resume, cancel, and retry supported tasks.
- Limit concurrent downloads and configure a download speed limit. Reorder the displayed task list and retain completed and failed task history.
- For CHZZK VODs, alternate between Akamai and Naver CDN sources on retries and check downloaded duration with FFprobe to detect incomplete output.

### X Spaces

- Capture playlist URLs for registered X accounts using authenticated, unofficial X APIs.
- Download captured playlists as M4A audio through the X Spaces page.
- Request one-time capture or start a download from Discord, including a direct Space URL workflow that does not require registering its host.
- Preserve captured URL metadata and, when automatic capture obtains a master playlist, a text backup in the live download directory.

X Spaces has a separate recording path and stricter API constraints. See [X Spaces workflows](#x-spaces-workflows) before relying on it for a broadcast.

### Dashboard and automation

- Responsive **Live**, **Downloads**, **X Spaces**, **Chat history**, **Statistics**, **Logs**, and **Settings** pages.
- Korean, English, and Japanese language choices, with Korean fallback for untranslated text. Some setup, backend, and integration messages remain Korean.
- Color presets, a custom accent color, and browser-local title and favicon preferences.
- Discord slash commands, bot notifications, and webhook delivery with fallback, retry handling, and a persistent pending-notification queue.
- Automatic release checks after startup and every 24 hours, plus a manual update check. Installation updates remain a separate operation.

## Supported platforms

| Platform | Live monitoring and recording | On-demand downloads | Authentication and limits |
| --- | --- | --- | --- |
| CHZZK | Channel polling, automatic recording, manual controls, live preview, time-machine modes, and optional chat archiving | VODs and clips | Optional Naver `NID_AUT` and `NID_SES` cookies for content requiring authentication; access and available quality depend on the platform |
| YouTube | Channel polling, automatic live recording, live preview, and Discord start/stop controls | Individual videos and channel imports | Public downloads are attempted without cookies; configured cookies are used as a fallback for recognized authentication errors. Live authentication and web controls have the limitations described below |
| X Spaces | Registered-account polling, playlist capture, and a separate audio-recording path when automatic recording is enabled | Captured playlists in the web UI; direct Space URLs through Discord | X cookies containing `auth_token` and `ct0` are required for API lookups. Rate limits, expired URLs, and unavailable replays can prevent capture |

The generic download engine uses yt-dlp internally, but this does not establish support for every yt-dlp extractor. A dedicated YouTube playlist-import workflow is not documented here. TwitCasting has been removed and is rejected by the download engine.

## Requirements

| Installation method | Requirements |
| --- | --- |
| Windows release | Windows x64; a writable application directory; external FFmpeg and FFprobe. Python, the built frontend, Streamlink, and a Node.js runtime are included in the executable build. A separate yt-dlp executable is located or downloaded at startup |
| Linux management script | Bash, initial access to `curl`, network access for dependencies and GitHub, and appropriate package-installation permissions. The script manages Git, Python, Node.js, FFmpeg, frontend builds, and a Python virtual environment; systemd service registration is optional |
| Source installation | Git, Python **3.12** as used by CI and releases, Node.js **22+** with npm as the recommended common setup for builds and YouTube processing, and FFmpeg/FFprobe |

The Python requirements install `yt-dlp[default]`, `streamlink>=7.3,<9`, FastAPI, and the remaining backend dependencies. Installing the `ffmpeg-python` package does **not** install the FFmpeg executable.

Version checks differ across entry points: the Linux script accepts Python 3.10+ and Node.js 20+, while desktop startup checks Python 3.12+, CI uses Python 3.12 and Node.js 20, and Windows packaging requires Node.js 22+ and currently builds with Node.js 24. Use Python 3.12 and Node.js 22+ for a new source setup rather than treating the installer's older minimums as a tested compatibility guarantee. The Linux installer requires FFmpeg 6+.

The management script recognizes Debian/Ubuntu, Fedora/RHEL-family, and Arch-family systems and includes a Homebrew path for macOS. Dependency installation is distribution-dependent; the repository does not establish a tested minimum OS release or a macOS release package. Its Linux static FFmpeg fallback handles x86_64 and aarch64.

## Installation

### Windows release

1. Download the Windows x64 executable from [the latest release](https://github.com/ProofPage/Phrolova/releases/latest). The verified v2.0.48 asset is `Phrolova-v2.0.48-windows-x64.exe`.
2. Place it in a writable folder that will also hold its configuration, data, and logs.
3. Install FFmpeg and FFprobe. Put `ffmpeg.exe` and `ffprobe.exe` in a `bin` folder beside the Phrolova executable, or add their directory to your system `PATH`.
4. Launch the executable. Startup checks dependencies and attempts to download `yt-dlp.exe` into the adjacent `bin` folder if it is missing. This requires network access; you can also place `yt-dlp.exe` there yourself.
5. Open [http://localhost:8000](http://localhost:8000) if the browser does not open automatically, and complete setup.

FFmpeg and FFprobe are **not bundled**. Although backend settings support `FFMPEG_PATH`, the desktop launcher's initial FFmpeg check searches the adjacent `bin` folder and `PATH`; use one of those locations for the release executable.

The desktop build includes a system tray menu for opening the browser and exiting. Some tray labels and executable metadata retain the legacy name **Rookery**.

To upgrade, exit the running application and replace the executable with the new release in the same folder. Keep `.env`, `data/`, `logs/`, `bin/`, and your media directories.

### Linux management script

Run:

```bash
curl -fsSL https://raw.githubusercontent.com/ProofPage/Phrolova/main/scripts/manage.sh | bash
```

On a new installation, the script installs or checks dependencies, clones the repository, builds the frontend, creates `.venv`, installs backend requirements, and registers the `rookery` management command. It asks whether to install and start a systemd service. Without a service, use `rookery start` to run in the foreground.

The default location is `~/rookery`. Existing legacy installation locations can be reused. Running the command again updates an existing installation from `main`; this is a source-branch update, not a pinned release installation.

To choose a location, pass `INSTALL_DIR` to **Bash**, which executes the script:

```bash
curl -fsSL https://raw.githubusercontent.com/ProofPage/Phrolova/main/scripts/manage.sh | INSTALL_DIR="$HOME/Phrolova" bash
```

Available management commands:

| Command | Action |
| --- | --- |
| `rookery install` | Run installation and offer service registration |
| `rookery update` | Update from `main`, rebuild when changed, and restart an installed service |
| `rookery start` | Start the service, or run in the foreground without one |
| `rookery stop` | Stop the service; use Ctrl+C for a foreground session |
| `rookery restart` | Restart the application |
| `rookery status` | Show version, location, port, and server/service status |
| `rookery status --full` | Run the detailed health-check script |
| `rookery logs` | Follow the service journal, or the script's fallback `logs/service.log` if present |
| `rookery service install` | Register, enable, and start the systemd service |
| `rookery service remove` | Remove the systemd service |
| `rookery uninstall` | Remove the service, command links, and virtual environment; retain the repository and data |

The CLI command and systemd service are still named `rookery`. Keep that spelling in commands. If an update encounters local changes that block a pull, the script may stash them before retrying; inspect the reported stash before continuing local development.

### Manual source installation

Install the prerequisites above first. The following Bash commands build the frontend directly into `backend/app/static` and run the backend from `backend/`:

```bash
git clone https://github.com/ProofPage/Phrolova.git
cd Phrolova

python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt

cd frontend
npm ci
npm run build
cd ../backend

python run.py
```

For Windows PowerShell:

```powershell
git clone https://github.com/ProofPage/Phrolova.git
cd Phrolova

py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

cd frontend
npm ci
npm run build
cd ..\backend

..\.venv\Scripts\python.exe run.py
```

Open [http://localhost:8000](http://localhost:8000). The production frontend is served by FastAPI; a separate Vite server is unnecessary after the build. No `dist` copy step is required.

Leave `.env` absent to use the setup wizard. For file-based configuration, copy [`.env.example`](.env.example) to `.env` at the repository root and review [Configuration](#configuration), including the outdated entries in that template. A nonempty `DOWNLOAD_DIR` in `.env` marks setup as complete and suppresses the wizard.

The current repository has no Dockerfile or Compose configuration; Docker installation is not provided.

## Quick start

1. **Complete initial setup.** Choose separate live and video download directories, a live output format, and recording quality, then review and save. The wizard suggests `Downloads/Phrolova/Live` and `Downloads/Phrolova/Video` under the server user's home directory.
2. **Set your interface language.** In **Settings → Appearance**, select English if desired. Some messages remain untranslated.
3. **Add authentication when needed.** Use **Settings → Authentication** for CHZZK cookies and YouTube or X cookie files.
4. **Add a channel in Live.** Choose CHZZK, YouTube, or X Spaces. Use a CHZZK channel URL/ID, a YouTube `@handle` or `UC` channel ID, or an X account handle. Enable automatic recording if you want recording to begin when a live session is detected.
5. **Review recording options.** Configure global quality, format, and filenames in Settings. CHZZK channels can inherit or override the automatic recording condition. Tags help organize the list separately from those conditions.
6. **Download a video.** Open **Downloads**, add a CHZZK VOD/clip or YouTube video link, and watch its task status. A YouTube channel URL or `@handle` starts background channel import. Stopping an import stops collection; videos already queued remain.
7. **Review results.** Use **Downloads** for video task history, **Chat history** for saved CHZZK chat, **Statistics** for recording/download summaries, and **Logs** for failures and diagnostics. Media is saved on the backend host.

### X Spaces workflows

Upload a Netscape-format X cookie file containing `auth_token` and `ct0` before using account discovery or direct Space lookups.

- **Registered account:** add its handle in Live. The current conductor polls X accounts every **300 seconds**, independently of `MONITOR_INTERVAL`. Detection can capture a playlist and start the separate Spaces recording process if automatic recording is enabled. This path does not share CHZZK/YouTube's stalled-recording retry loop.
- **One-time lookup:** use Discord `/capture-space` with the `username` argument set to a registered handle, without `@`. This performs an immediate lookup and returns a captured playlist when available.
- **Captured playlist:** paste a captured Periscope CDN master-playlist URL into the **X Spaces** page and start the download. This uses the video task queue and writes M4A audio to the video download directory.
- **Direct Space URL:** use Discord `/download-space` with the `url` argument set to the Space's actual `https://x.com/i/spaces/…` address. This performs a dedicated authenticated lookup and starts a separate subprocess, saving to the live download directory. It does not require channel registration and is not tracked as a normal Downloads queue task.

The web form advertises direct Space URLs, but its current backend path expects playlist content and does not resolve a Space page first. Use a captured playlist in the web UI or the dedicated Discord command for a Space page URL.

X API changes, HTTP 429 responses, cookie expiry, and unavailable recordings can interrupt these workflows. A captured URL is not a permanent archive, and no fixed replay-retention period is guaranteed.

## Configuration

Settings are loaded through Pydantic Settings from environment variables and `.env`. Environment variables override `.env` values. The application uses:

- **Source:** repository-root `.env`, with `backend/.env` as a legacy fallback when the root file is absent.
- **Windows executable:** `.env` beside the executable.

The web settings pages write to the same resolved `.env` file. Restart after editing it manually, changing host/port or Discord bot credentials, changing download concurrency, or changing the monitoring interval for already-running channels. Some other settings take effect immediately or on the next task.

Prefer absolute media paths for a service. Relative paths are resolved from the process working directory; the Linux service and the source commands above run from `backend/`, so `./recordings` means `backend/recordings` in those cases.

### Server and media settings

These defaults come from the current settings implementation, rather than older guide text.

| Variable | Default | Purpose |
| --- | --- | --- |
| `HOST` | `0.0.0.0` | Server bind address; use `127.0.0.1` for local-only access |
| `PORT` | `8000` | HTTP port |
| `FFMPEG_PATH` | `ffmpeg` | Backend FFmpeg executable path; adjacent `bin/` and `PATH` are also searched |
| `DOWNLOAD_DIR` | `./recordings` | Fallback media directory and setup-completion setting |
| `LIVE_DOWNLOAD_DIR` | Empty | Live output directory; falls back to `DOWNLOAD_DIR` |
| `VOD_DOWNLOAD_DIR` | Empty | Common video output directory; otherwise legacy directory rules apply |
| `MONITOR_INTERVAL` | `60` | CHZZK/YouTube polling interval in seconds; Settings accepts 5–300 |
| `RECORDING_QUALITY` | `best` | Live preference: `best`, `1080p`, `720p`, or `480p` |
| `LIVE_FORMAT` | `ts` | Live container: `ts`, `mkv`, or `mp4` |
| `MAX_RECORD_RETRIES` | `3` | Automatic retries after an established CHZZK/YouTube recording stalls while live |
| `CHZZK_STREAM_MODE` | `request-timemachine` (effective default) | `standard`, `request-timemachine`, or `force-timemachine` |
| `CHZZK_TIME_MACHINE_OFFSET` | `0` (effective default) | Seconds skipped from the available time-machine stream's beginning; clamped to 0–86400 |
| `SAVE_LIVE_PREVIEW` | `false` | Save a CHZZK preview image when recording starts |
| `LIVE_DOWNLOAD_CONDITION` | `all` | CHZZK default: `all`, `watchalong`, or `exclude_watchalong` |
| `WATCHALONG_TAGS` | Platform's Korean watch-along marker | Comma- or newline-separated matching tags for watch-along-only recording; editable in Settings |
| `CHAT_ARCHIVE_ENABLED` | `false` | Save CHZZK chat alongside live recordings |
| `VOD_MAX_CONCURRENT` | `3` | Simultaneous video tasks; Settings accepts 1–10; restart to apply |
| `VOD_DEFAULT_QUALITY` | `best` | Default video quality selection in the dashboard |
| `VOD_FORMAT` | `mp4` | Preferred video merge container: `mp4`, `mkv`, or `ts` |
| `VOD_MAX_SPEED` | `0` | yt-dlp download limit in MB/s; `0` means unlimited |
| `KEEP_DOWNLOAD_PARTS` | `false` | Retain partial video files on supported cancellation/failure paths |

`request-timemachine` tries CHZZK time-machine playback and falls back to the standard stream. `force-timemachine` fails if that playback cannot be obtained. Availability is controlled by CHZZK; these modes do not promise access to an entire broadcast.

Video output format is a merge preference, not a universal conversion guarantee. Single-file downloads, clips, and Spaces use different paths; Spaces output is M4A. Quality requests are constrained by the formats exposed upstream.

**Template compatibility:** `.env.example` still contains `OUTPUT_FORMAT`, which the current settings model ignores. Use `LIVE_FORMAT` and `VOD_FORMAT`. Its old live filename default is automatically migrated. Its comments about bundled FFmpeg and Docker do not describe the current release. Existing `SPLIT_DOWNLOAD_DIRS`, `VOD_CHZZK_DIR`, and `VOD_EXTERNAL_DIR` values remain legacy fallbacks when `VOD_DOWNLOAD_DIR` is empty.

### Filename templates

The current defaults include seconds and use filesystem-safe separators:

```dotenv
LIVE_FILENAME_TEMPLATE="[{name}] {title} {live_date_year}-{live_date_month}-{live_date_day} {live_date_hour}-{live_date_minute}-{live_date_second}"
VOD_FILENAME_TEMPLATE="[{name}] {title} {date_year}-{date_month}-{date_day} {date_hour}-{date_minute}-{date_second}"
```

For live recording, `{name}`, `{title}`, `{channel_uid}`, `{category}`, and `{quality}` are available, together with `live_date_*` and `download_date_*` date/time fields. `live_date_*` uses the broadcast start time when available, otherwise the recording start time. The extension is appended if absent, invalid filename characters are sanitized, and collisions receive a numeric suffix.

Video templates accept `{name}`, `{title}`, `{id}`, `{extractor}`, `{upload_date}`, `{quality}`, `{download_date}`, and `{date_year}`, `{date_month}`, `{date_day}`, `{date_hour}`, `{date_minute}`, `{date_second}`. The `date_*` fields describe the download's naming timestamp, not the original broadcast time. The extension is added automatically. These templates are validated for supported tokens and filename characters. Spaces uses its own filenames.

### Authentication

| Platform | Setting | How it is used |
| --- | --- | --- |
| CHZZK | `NID_AUT`, `NID_SES` | Enter your own Naver session cookies through Settings when authenticated access is required |
| YouTube | `YOUTUBE_COOKIE_FILE` | Upload a Netscape-format cookie file in Settings. Downloads and channel imports retry with it after recognized authentication errors; preview resolution also reads it |
| X Spaces | `X_COOKIE_FILE` | Upload a Netscape-format file containing X `auth_token` and `ct0` cookies for account and Space API lookups |

Cookie-file paths refer to files on the backend host. Uploaded files are stored under the application's data directory. Cookies do not grant access beyond the account's permissions. Automatic YouTube live recording currently does not receive `YOUTUBE_COOKIE_FILE`; do not assume authenticated video downloads imply authenticated live recording support.

The dashboard and API have no built-in user login or access-control layer. Because the default host binds all interfaces and the API can control recordings, settings, and server directories, keep access restricted to trusted users or protect it with an authenticated reverse proxy or private network. Treat cookies, bot tokens, and webhook URLs as secrets.

## Discord integration

Configure Discord in **Settings → Notifications** or through `.env`. Invite your application bot with the `bot` and `applications.commands` scopes, and allow it to view the intended channel, send messages, and embed links. Restart after setting or replacing the bot token.

| Variable | Purpose |
| --- | --- |
| `DISCORD_BOT_TOKEN` | Bot token; enables the bot connection |
| `DISCORD_NOTIFICATION_CHANNEL_ID` | Destination channel for bot notifications; also the command-channel fallback when no explicit command restrictions are set |
| `DISCORD_COMMAND_USER_IDS` | Comma-separated user IDs allowed to run commands |
| `DISCORD_COMMAND_CHANNEL_ID` | Channel in which commands are allowed |
| `DISCORD_WEBHOOK_URL` | Notification-only delivery, or fallback when bot delivery is unavailable |
| `DISCORD_NOTIFY_EVENTS` | `all` (default), `none`, or a comma-separated list of event identifiers |
| `DISCORD_MENTION_EVENTS` | Event identifiers that should include a mention; empty by default |
| `DISCORD_MENTION_TARGET` | `@here` (default), `@everyone`, or a Discord role mention |
| `DISCORD_NOTIFY_TTL` | Maximum pending-notification age in seconds; default `3600` |

**Command authorization:** if both a user allowlist and a command channel are configured, both must match. A user allowlist alone restricts users without imposing a channel condition. If neither explicit restriction is configured, the notification channel becomes the allowed channel. With none of these configured, commands are denied. A channel-only restriction permits any user who can invoke the bot in that channel; set a user allowlist when tighter control is needed.

### Slash commands

Argument names below are the exact registered Discord option names.

| Command | Arguments | Behavior |
| --- | --- | --- |
| `/status` | None | Show recording and system status |
| `/list` | None | List registered channels |
| `/start` | `channel_id` | Start a registered channel and enable automatic recording |
| `/stop` | `channel_id` | Stop a registered channel and disable automatic recording |
| `/rescan` | None | Request an immediate scan of registered channels |
| `/diag` | None | Inspect notification queue and transport status |
| `/notify-test` | None | Enqueue a test notification of kind `system` |
| `/spaces` | None | Show captured Spaces URLs |
| `/capture-space` | `username` | Look up a registered X handle once; omit `@` |
| `/download-space` | `url` | Start a direct Space URL download or enqueue a captured playlist URL |

Use `/list` to obtain channel identifiers. Avoid repeatedly rescanning X accounts when rate-limited.

### Notification events

Supported event identifiers are `live_detected`, `recording_started`, `recording_completed`, `recording_failed`, `space_detected`, `vod_completed`, `vod_failed`, `cookie_expired`, `update_available`, and `system`.

Notifications are queued and attempted through the bot first, then the webhook. Pending notifications are persisted and expire after the configured TTL. Event coverage varies by execution path: not every download failure emits `vod_failed`, and direct Discord Space-URL downloads report subprocess completion in logs rather than normal video task notifications. Use Logs and task status to investigate missing completion or failure messages.

## Storage and backups

SQLite stores channels, automatic recording options, tags, recording sessions, live-detection history, completed/failed video tasks, pending notifications, and a derived chat-file index. Media and chat JSONL files remain ordinary files outside the database.

| Data | Source installation | Windows executable |
| --- | --- | --- |
| Settings | `.env` at repository root | `.env` beside executable |
| Database | `backend/data/rookery.db` | `data/rookery.db` beside executable |
| Uploaded cookie files | `backend/data/` | `data/` beside executable |
| Application logs | `logs/` at repository root | `logs/` beside executable |
| Media and chat | Configured live/video directories | Configured live/video directories |

The filename `rookery.db` remains an implementation identifier. Existing `signal_recorder.db` files are migrated when appropriate. Legacy JSON state is imported once into empty destination tables, and successfully handled source files are retained with a `.migrated` suffix.

For a straightforward backup, stop Phrolova cleanly, then copy `.env`, the entire data directory, and the media directories you need. SQLite uses WAL mode and checkpoints on normal shutdown; do not copy only the main database file while it is running and assume that all recent changes are included. Preserve cookie backups privately.

Only completed and failed video task history is restored at startup. Queued, active, and paused downloads and channel-import jobs are not a durable restart queue. Keeping `.part` files does not guarantee automatic continuation after a restart.

## Architecture

Phrolova runs a FastAPI backend with a React single-page frontend. In a production build, FastAPI serves the frontend and HTTP API from the same process. Server-sent events update live channel state; the download UI also retrieves task status.

| Component | Responsibility |
| --- | --- |
| Python, FastAPI, and Uvicorn | API routes, settings, application lifecycle, and static frontend serving |
| React 19, TypeScript, Vite, and Tailwind CSS 4 | Dashboard, forms, responsive layout, frontend development, and builds |
| Recorder service and conductor | Registered-channel state, polling, recording orchestration, retries, and event broadcasts |
| Platform engines | CHZZK metadata/time-machine resolution, YouTube live detection, and X Spaces API access |
| yt-dlp | Stream URL/metadata extraction, video downloads, channel enumeration, and separate Spaces subprocesses |
| Streamlink | HLS/DASH stream reception for the live recording pipeline |
| FFmpeg and FFprobe | Live stream muxing, media merging, Spaces playlist output, and downloaded-duration validation |
| SQLite repository layer | Persistent application state and schema/legacy-data migrations |
| discord.py and notification service | Slash commands, bot delivery, webhook fallback, and queued notifications |

The main CHZZK/YouTube recording pipeline resolves a stream, receives its segments through Streamlink, and feeds FFmpeg. Video downloads use a concurrency-limited task engine. X Spaces has dedicated capture and subprocess paths as well as playlist downloads through the task engine. These paths have different progress reporting and control capabilities.

## Project structure

| Path | Contents |
| --- | --- |
| `backend/app/api/` | FastAPI routes for live channels, downloads, settings, Spaces, chat, statistics, and logs |
| `backend/app/core/` | Settings, paths, HTTP helpers, logging, and filename handling |
| `backend/app/engine/` | Conductor, platform engines, live pipelines, video downloads, chat capture, and release checks |
| `backend/app/services/` | Recorder facade, Discord bot, and notification delivery |
| `backend/app/store/` | SQLite access, repositories, and migrations |
| `backend/app/version.py` | Application version source |
| `backend/run.py` | Server and desktop startup |
| `backend/tests/` | Backend tests |
| `backend/requirements.txt` | Runtime Python dependencies |
| `frontend/src/` | React pages, components, hooks, contexts, and API client |
| `frontend/tests/` | Browser regression scripts and fixtures |
| `frontend/package.json` | Frontend dependencies and npm commands |
| `scripts/` | Linux/Windows management and health-check scripts |
| `docs/` | Changelog and technical guides |
| `assets/` | Icons and screenshots |
| `.github/` | CI, Windows releases, and issue/PR templates |
| `.env.example` | Environment template; see the compatibility notes above |
| `rookery.spec` | Windows PyInstaller packaging configuration |

`backend/app/static/` is generated by the frontend build and is not committed. The npm package name `rookery`, PyInstaller specification, `dist/Rookery.exe` build output, database filename, and Linux command/service retain legacy identifiers. Published release assets use **Phrolova**.

## Development

Set up the source installation first. From the repository root, activate its virtual environment and install the development requirements:

```bash
source .venv/bin/activate
python -m pip install -r backend/requirements-dev.txt
```

On Windows, use `.\.venv\Scripts\python.exe` in place of the activated `python` command, or activate the environment with `.\.venv\Scripts\Activate.ps1`.

Run the backend in one terminal:

```bash
cd backend
python run.py
```

Run the frontend in another terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Vite proxies `/api` and `/health` to `http://127.0.0.1:8000`. Keep the backend at that address during development unless you also intentionally adjust the development proxy. `run.py` does not enable automatic backend reload; restart it after backend changes.

### Validation commands

Run backend tests from the repository root:

```bash
python -m pytest -c backend/pytest.ini backend/tests
```

Run type checking and the production frontend build from `frontend/`:

```bash
npx tsc --noEmit -p tsconfig.json
npm run build
```

These are the checks requested by the contribution guide. CI runs backend pytest and frontend type checking/builds. Static test-count baselines in older documents differ; consult the actual test output and current CI results rather than treating a historical count as a current result. Browser regression instructions are in [frontend/tests/README.md](frontend/tests/README.md).

### Windows executable build

On Windows, use Python 3.12 and Node.js 22+ available on `PATH`. From the repository root with the Python virtual environment active:

```powershell
cd frontend
npm ci
npm run build
cd ..
python -m pip install -r backend/requirements.txt pyinstaller pillow pystray
python -m PyInstaller --clean --noconfirm rookery.spec
```

The result is `dist/Rookery.exe`. The release workflow renames it to a versioned Phrolova Windows x64 asset. The specification bundles Node.js and retrieves its matching license during the build; network access is required. FFmpeg and FFprobe remain external dependencies.

## Limitations and troubleshooting

### Known limitations

- **YouTube web start/stop:** the current `/api/stream/record/…` route does not preserve the `youtube:` channel prefix. Use automatic recording or Discord `/start` and `/stop`, which call the conductor with the correct composite key. Do not assume the visible web buttons work for YouTube.
- **YouTube live authentication:** uploaded YouTube cookies are wired into downloads, imports, and preview resolution, but are not passed by the conductor into automatic live recording. Restricted live broadcasts may fail even when video downloads work with cookies.
- **X Spaces:** detection depends on unofficial APIs and available metadata. Its live recording process lacks the CHZZK/YouTube stalled-recording retry path. Direct Space URLs should use Discord; the web path needs a captured playlist.
- **Download controls:** pause/resume is implemented through yt-dlp progress callbacks. The direct FFmpeg Spaces replay path does not implement equivalent pause/cancel handling, granular progress, or the yt-dlp speed limit. Paused yt-dlp tasks retain their concurrency slot.
- **Task order and persistence:** display reordering does not reschedule already-created download coroutines. Active queues and imports are not restored across restarts.
- **Availability:** a quality setting, cookie, retry, or captured URL cannot recover media that the upstream platform no longer supplies. No guarantee of gap-free recordings or complete platform coverage is made.

### Common issues

| Symptom | What to check |
| --- | --- |
| FFmpeg not found | Install FFmpeg and FFprobe together. For the executable, use adjacent `bin/` or `PATH`; for backend operation, a valid `FFMPEG_PATH` is also supported |
| CHZZK VOD repeatedly fails duration validation | Verify `ffprobe` is beside FFmpeg or on `PATH`, then inspect Logs for an incomplete download or CDN error |
| Missing Streamlink or another Python module | Use the intended virtual environment and reinstall `backend/requirements.txt`; for a packaged app, obtain the current release |
| yt-dlp missing at Windows startup | Check outbound GitHub access or put `yt-dlp.exe` in the adjacent `bin/` folder |
| YouTube extraction fails | Check Logs, the installed yt-dlp version, and Node.js availability. For authentication-required video downloads, re-upload valid cookies and check that the account can view the video |
| Authentication fails or cookies expire | Re-export your own current Netscape cookie file, or replace CHZZK cookie values in Settings. X API lookups require both `auth_token` and `ct0` |
| X returns HTTP 429 or no playlist | Allow time before trying again; avoid repeated scans. Check whether the Space is running or still has an accessible replay |
| Live channel is not recording | Confirm automatic recording is enabled, check CHZZK watch-along conditions and the hold message, confirm the stream is live, and inspect Logs |
| Retry limit reached | Inspect the reported failure and correct its cause before manually restarting recording or retrying a completed/failed video task |
| Browser cannot connect or port is occupied | Check `HOST` and `PORT`, stop an older instance/service, and restart. Use `/health` on the configured port to check server response |
| API works but the dashboard does not load | Run `npm ci` and `npm run build` in `frontend/`, confirm `backend/app/static/index.html` exists, and restart the backend |
| Linux service does not start | Run `rookery status --full` and `rookery logs`; check the service user's access to the application, virtual environment, and output directories |
| `rookery` command is missing | Re-run the installation one-liner to register it. If installed under `~/.local/bin`, ensure that directory is on your `PATH` |
| `rookery logs` reports no file without systemd | Use the foreground console or the dashboard's Logs page. The script's fallback `logs/service.log` is not automatically created by foreground startup |
| Cannot save settings or media | Give the backend user write access to `.env`, the data directory, logs, and configured output directories. Check free disk space and use absolute paths |
| An output folder does not open in your browser's machine | “Open location” runs on the backend host, not on a remote browser client; access the server's media directory directly |

Back up settings and data before changing installation locations. To update a Linux installation managed by the script, use `rookery update`; for Windows, replace the stopped executable. Dashboard release checks notify you of updates but do not install them.

## Additional documentation

- [Changelog](docs/CHANGELOG.md) — release history.
- [Storage guide](docs/storage.md) — SQLite and legacy JSON migration details.
- [Linux guide](docs/linux-guide.md) — additional service-management background.
- [X Spaces guide](docs/x-spaces-guide.md) — cookie setup and capture background.
- [Test guide](docs/test-guide.md) — historical manual test scenarios.
- [Browser regression tests](frontend/tests/README.md) — current frontend regression commands.

Most supporting guides are written in Korean. Some retain older installation paths, Docker references, executable names, or behavior descriptions. In particular, setup completion now uses `.env` with a nonempty `DOWNLOAD_DIR`, not `data/.setup_complete`; Vite builds directly into `backend/app/static`; and the current X conductor does poll registered accounts. Use this README's instructions where those guides disagree.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before changing code. Preserve recording behavior and compatibility with deployed clients, including API paths, field names, and payload structures. Run the backend tests, TypeScript check, and production build described above, and report the results you actually observed.

Follow the repository's existing line endings, use theme tokens and shared UI primitives, write code comments explaining why in Korean, and use English commit subjects with Korean bodies as requested by the contribution guide. Do not renormalize unrelated files.

## License and attribution

Phrolova is distributed under the [MIT License](LICENSE).

Copyright (c) 2026 Serian (github.com/eruminyu). The original author attribution is preserved in the license and package metadata. The repository also records contributions in its Git history and changelog.
