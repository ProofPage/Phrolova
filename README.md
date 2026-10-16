# Phrolova

**Record live streams. Download videos. Manage your archive.**

Phrolova is a self-hosted recorder and video downloader for **CHZZK, YouTube, SOOP, CIME, Kick, Twitch, TikTok and Bilibili**. Monitor channels, preview broadcasts, manage downloads and verify saved media in one web dashboard. Run the packaged app on Windows, or install from source on Linux, macOS or Android with Termux.

[Download](https://github.com/ProofPage/Phrolova/releases/latest) · [Release notes](docs/release-notes/README.md) · [Changelog](docs/CHANGELOG.md)

## Features

| Area | What it provides |
| --- | --- |
| Live | Automatic/manual recording, channel tags and filters, per-channel preferences, CHZZK Time Machine and recording conditions |
| Previews | In-dashboard HLS playback or refreshed frames, with loading states and retry controls; TikTok shares the recording input while recording |
| Videos | VODs, clips, supported external links, YouTube channel imports, quality selection, queues, speed limits and task controls |
| Media processing | FFmpeg finalization to MKV/MP4, FFprobe inspection, processing history, source preservation on failure and retry actions |
| Statistics | Recording duration and size, download totals, channel activity, recent sessions, disk usage and separate live/video paths |
| Logs | Original files, severity counts and filters, search, live updates, auto-scroll and full-file export |
| Notifications | In-app alerts, Discord bot/webhook delivery, command access rules and a persistent delivery queue |
| Settings | Storage, filenames, authentication, appearance, updates, and the status, version and path of Streamlink, yt-dlp, FFmpeg and FFprobe |

The interface supports **Korean, English, Japanese, Spanish, German, Simplified Chinese, Traditional Chinese and Russian**. Korean is the default. Choose a language in **Settings → Appearance**; the browser remembers it and formats dates, numbers and quantities accordingly. Paths, filenames, user content and technical logs retain their original text.

### Supported sources

| Source | Live | Videos | Authentication when required |
| --- | --- | --- | --- |
| CHZZK | Monitoring, preview, manual/automatic recording and Time Machine | VODs and clips | Naver account cookies |
| YouTube | Monitoring, preview and manual/automatic recording | Videos and channel imports | Uploaded cookies for authenticated video access |
| SOOP | Monitoring, preview and manual/automatic recording | VODs and multi-part videos | Platform cookies |
| CIME | Monitoring, preview and manual/automatic recording | VODs and clips | Platform cookies |
| Kick | Streamlink monitoring integration, preview and manual/automatic recording | VODs and clips via yt-dlp | Optional Kick cookies; required for sign-in-only qualities |
| Twitch | Monitoring, preview and manual/automatic recording via Streamlink | VODs and individual clips via yt-dlp | Optional Twitch Netscape cookies |
| TikTok | Monitoring, frame previews and manual/automatic recording via Streamlink | Individual videos and short share links via yt-dlp | Optional TikTok Netscape cookies |
| Bilibili | Room monitoring, HLS previews and manual/automatic recording via Streamlink | BV/av videos, selected parts and b23.tv share links via yt-dlp | Optional Bilibili Netscape cookies |
| Anilife / Linkani / Ohli24 | — | Work/episode links, episode selection, HLS videos and VTT subtitles | Normal site playback session |
| TVWiki (티비위키) | — | Work/episode selection and HLS videos at tvwiki54.net | Normal guest playback session |
| TVChak (티비착) | — | Work/episode selection and original MP4 videos at tvchak208.com | Optional browser cookie file for site access checks |
| Animaru (애니마루) | — | Work/episode selection, HLS videos and provided VTT subtitles at animaru1.com | Public reader/player API |
| Ani365 (애니365) | — | Work/episode selection, HLS quality variants and provided VTT subtitles at v2.ohli365.org | Public catalog/playback API and MegaPlay delivery |

Bilibili live rooms accept a numeric room ID or `https://live.bilibili.com/<room>`. The recorder prefers MPEG-TS HLS, tries alternate CDNs and preserves native fMP4 HLS when needed. Available native quality IDs are retained; a stream with no advertised quality ID is shown as Original rather than an inferred resolution. Bilibili's popularity metric is identified separately from viewer counts. Videos accept BV/av IDs and `b23.tv` links; `?p=2` selects a single part. Separate DASH video and audio tracks are merged into the configured container. Cropped videos display both the provider's quality tier and actual pixel dimensions. Register a Netscape cookie file under **Settings → Authentication → Bilibili** when account access or additional qualities are needed. Cookies remain scoped to `bilibili.com`.

For episode-based sources, paste a work link in **Videos** and select up to 100 episodes. These sources use the existing queue, quality controls and media inspection. See [episode source adapters](docs/video-site-adapters.md) for URL formats and validation details.

External links use yt-dlp's supported extractors. Available formats and access follow the source platform. YouTube imports skip live/upcoming entries and videos already queued in a non-error state. Authenticated YouTube video downloads/imports are separate from automatic live recording; authenticated automatic YouTube live recording is not established by cookie registration.

YouTube uses the same Python yt-dlp dependency for video metadata, downloads and isolated live-extraction workers. Public requests start without account cookies, even if a saved cookie path has become stale. Node.js/EJS options are applied to metadata as well as downloads. Private, members-only and age-restricted content still uses explicit account authentication.

A server-side bot challenge or HTTP 429 is reported separately from content permissions. These restrictions can affect public videos; the app reports them as connection or rate-limit errors instead of a successful download. Check the server connection and any VPN/proxy, wait before retrying, and reduce simultaneous requests. See [YouTube extractor guidance](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#youtube) and the [official client update](https://github.com/yt-dlp/yt-dlp/pull/17805).

### Recording pipeline

```text
Channel monitoring → Streamlink capture → source file
                                              ↓ after capture closes
                                  FFmpeg finalization → FFprobe inspection
                                              ↓
                                       MKV or MP4 archive
```

Phrolova prefers TS capture and preserves native fMP4/CMAF when TS is unavailable. Finalization starts after capture stops. MKV is the default final container; MP4 is also available. Source retention is configurable, and failed processing preserves recoverable source data. Download completion and media inspection have separate statuses, so a failed inspection does not delete a completed download.

## Installation

| System | Distribution | Requirements |
| --- | --- | --- |
| Windows x64 | Packaged `.exe` | External FFmpeg and FFprobe; Python, Streamlink, the dashboard and Node.js are bundled |
| Linux x64 / ARM64 | Source | Bash, Git, Python 3.12+, Node.js 22+ with npm, FFmpeg/FFprobe 6+ and `ps` |
| macOS Apple Silicon / Intel | Source | Homebrew, Git, Python 3.12+, Node.js 22+ and FFmpeg/FFprobe 6+ |
| Android / native Termux | Source | Current Termux packages and native build tools; the installer selects the Termux dependency profile |
| Linux under Termux proot | Source | Linux dependencies inside the guest; set `PHROLOVA_ENVIRONMENT=termux-proot` |

The repository distributes a Windows executable and source archives. It does not ship macOS application bundles, Android APKs or Docker images. See [platform support](docs/native-platform-support.md) for implementation and validation scope.

**Repository access:** This repository currently requires an authorized GitHub account. Clone with an authenticated credential helper or SSH key. Anonymous raw-file install links cannot access a private repository.

### Windows

1. Download `Phrolova-v<version>-windows-x64.exe` and `SHA256SUMS.txt` from [the latest release](https://github.com/ProofPage/Phrolova/releases/latest).
2. Place the executable in a writable folder. Install **both** `ffmpeg.exe` and `ffprobe.exe` on `PATH`, or place them in a `bin` folder beside the app.
3. Launch Phrolova. Startup checks dependencies and attempts to download `yt-dlp.exe` into `bin` if it is missing. You can place that executable there manually instead.
4. Open <http://127.0.0.1:8000> and complete setup. The tray menu opens the dashboard or exits the app.

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

The manager prepares dependencies, `.venv`, the production dashboard and the `phrolova` command. It supports apt, dnf/yum, pacman and apk. Distributions with an older default Python need a Python 3.12+ interpreter first. An active systemd installation offers optional service registration; otherwise the server runs in the foreground.

See the [Linux guide](docs/linux-guide.md) for manual installation and service management.

### macOS

Install [Homebrew](https://brew.sh), then use a regular user terminal:

```bash
brew install git python@3.12 node@22 ffmpeg
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
3. Upload Netscape-format cookies in **Settings → Authentication** for content requiring sign-in. Public content can be used without cookies.
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
| `YOUTUBE_COOKIE_FILE`, `SOOP_COOKIE_FILE`, `CIME_COOKIE_FILE`, `KICK_COOKIE_FILE`, `TWITCH_COOKIE_FILE`, `TIKTOK_COOKIE_FILE`, `BILIBILI_COOKIE_FILE`, `TVCHAK_COOKIE_FILE` | Optional Netscape cookie files; upload through Settings → Authentication |

Use absolute media paths. Relative paths follow the working directory; the source manager starts from `backend/`. Enter actual paths in `.env` rather than relying on shell-variable expansion. Saved preferences are preserved when defaults change in a later release.

TVChak accepts work and episode links under `tvchak208.com/index.php/vod/`. Site access checks can require a browser cookie export from the same internet connection as the server. Register it under **Settings → Authentication → TVChak**. The application reports access checks explicitly and keeps those cookies scoped to the site; it does not solve challenges.

Animaru, TVChak, TVWiki and Anilife also accept changing numeric domain suffixes (`animaru[0-9]+.com`, `tvchak[0-9]+.com`, `tvwiki[0-9]+.net`, `anilife[0-9]+.tv`). Paste the current work/episode address; its hostname is preserved throughout selection and downloading. Website redirects stay within the same domain family, and cookies remain scoped to each original domain.

CHZZK account cookies use `NID_AUT` and `NID_SES`. YouTube, SOOP, CIME, Kick, Twitch, TikTok and Bilibili use their corresponding `*_COOKIE_FILE` settings. Kick uses registered cookies for both live quality resolution and VOD extraction so sign-in-only qualities can appear. Register a Netscape cookie file under Settings → Authentication → Kick, then refresh the quality list or retry video metadata. Only advertised qualities are offered; explicitly requested 1080p is never silently replaced with 720p. Kick cookies and API authorization stay scoped to Kick and are not forwarded to unrelated media CDNs.

Twitch accepts channel IDs and channel URLs for live monitoring, `/videos/<id>` URLs for VODs, and `clips.twitch.tv/<slug>` or channel clip URLs for clips. Register an optional cookie file under Settings → Authentication → Twitch when account access is needed. The `auth-token` cookie is passed through Streamlink's Twitch API option; OAuth headers are not forwarded to media CDNs. The recorder uses the Twitch-specific HLS reader for stream transitions. Deleted, unavailable or restricted videos remain errors. See the [Streamlink Twitch documentation](https://streamlink.github.io/cli/plugins/twitch.html) for authentication and client-integrity requirements.

TikTok live URLs use `https://www.tiktok.com/@username/live`. The Streamlink plugin supplies FLV inputs, which the recorder remuxes to TS with FFmpeg using stream copy; it does not re-encode the video or audio. FFmpeg reads local pipes rather than upstream URLs. Live previews use refreshed images because the input is FLV. During recording, previews reuse a bounded in-memory keyframe buffer so opening the preview does not create a competing CDN connection or read a growing recording file. Complete FLV packets are preserved, and connection interruptions are reported separately from decoder errors. Video downloads accept `@username/video/<id>`, `vm.tiktok.com`, `vt.tiktok.com` and `tiktok.com/t/` links. Live share links are rejected from the video queue. TikTok is separate from Douyin. Register cookies under Settings → Authentication → TikTok when access requires an account.

YouTube video extraction first tries public access and retries recognized authentication failures with registered cookies.

The dashboard/API has no built-in login. Keep the default loopback binding for local use. For remote administration, use an SSH tunnel or an authenticated proxy/private network:

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

With Python 3.12+, Node.js 22+, npm and FFmpeg/FFprobe installed:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
(cd frontend && npm ci && npm run build)
(cd backend && ../.venv/bin/python run.py)
```

On Windows, use `py -3.12 -m venv .venv` and `.venv\Scripts\python.exe`. Native Termux uses `python` and `backend/requirements-termux.txt`; install test tools separately if needed. `ffmpeg-python` does not install FFmpeg/FFprobe. Node.js remains needed for YouTube JavaScript processing after the dashboard is built.

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

The [CI configuration](.github/workflows/ci.yml) defines Linux x64/ARM64, Windows x64, macOS Apple Silicon/Intel and Linux ARM64/Python 3.14 with the Termux dependency profile. That profile checks dependencies on Linux; Android compilation and power-management behavior need device testing. Consult workflow runs and release notes for checks completed for a particular release.

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
| Folder does not open | Use the returned path on the machine running Phrolova |
| Port is in use | Check `phrolova status`, stop the old instance and wait for shutdown |
| Update check returns HTTP 404 | Private release metadata requires authentication; use your authorized checkout or GitHub download |
| Termux build fails | Check build tools, free space and the [Termux guide](docs/termux-guide.md) |

## Documentation

[Linux](docs/linux-guide.md) · [macOS](docs/macos-guide.md) · [Termux](docs/termux-guide.md) · [Platform support](docs/native-platform-support.md)

FFmpeg/FFprobe are installed separately and follow their own licenses.
