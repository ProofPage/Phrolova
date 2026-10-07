<div align="center">

# Phrolova

**A self-hosted app for monitoring live channels, recording broadcasts, and downloading VODs and clips.**

[![Latest release](https://img.shields.io/github/v/release/ProofPage/Phrolova?display_name=tag&label=latest%20release)](https://github.com/ProofPage/Phrolova/releases/latest)
[![CI](https://github.com/ProofPage/Phrolova/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ProofPage/Phrolova/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-MIT-64748B)](LICENSE)

[Windows download](https://github.com/ProofPage/Phrolova/releases/latest) · [Getting started](#getting-started) · [Changelog](docs/CHANGELOG.md) · [Report an issue](https://github.com/ProofPage/Phrolova/issues)

</div>

Phrolova runs locally or on a private server and provides a web dashboard for live recording and media downloads. Add channels to monitor, record broadcasts automatically or on demand, and manage existing videos in a download queue. It is designed for people who want to keep broadcasts and media they are authorized to access.

The app uses **recording** for saving a live broadcast and **downloading** for retrieving an existing VOD, clip, video, or supported audio replay.

## Features

- Monitor supported channels and record live broadcasts automatically or manually.
- Apply recording conditions to CHZZK channels, including watch-along tags.
- Download CHZZK VODs and clips, YouTube videos and channel uploads, and other supported media URLs.
- Reorder queued downloads, pause and resume them, cancel tasks, and retry failures.
- Configure recording and download quality, file formats, filename rules, and separate save locations.
- Optionally save CHZZK live chat as JSONL beside a recording.
- Review recording and download history, statistics, application logs, and disk usage.
- Send event notifications through a Discord bot or webhook.

## Supported services

Access to content and quality options depends on the service and your account permissions.

| Service | Live monitoring and recording | Existing media downloads | Notes |
| --- | --- | --- | --- |
| CHZZK | Yes | VODs and clips | Optional chat archiving. Cookies may be needed for age checks or some quality levels. |
| YouTube | Yes | Videos and channel uploads | Add a channel by handle or ID. Cookies may be needed for restricted videos. |
| X Spaces | Detects Spaces and records live audio | Replay audio captured by Phrolova | Requires an X cookie file. Captured replay links are temporary. |
| Other yt-dlp sites | No | Supported media URLs | Downloads depend on site and video availability; these URLs do not enable live monitoring. |

## Installation

### Windows

Download the Windows x64 executable from the [latest release](https://github.com/ProofPage/Phrolova/releases/latest).

1. Save <code>Phrolova-v*-windows-x64.exe</code> in a folder where you have write access.
2. Run it and complete the initial setup in your browser.
3. If the browser does not open, visit <code>http://127.0.0.1:8000</code>.

The executable includes the application runtime and Node.js, but not FFmpeg. At startup, Phrolova checks for FFmpeg and offers to install it if needed. It can download yt-dlp automatically when yt-dlp is unavailable. When updating, keep the <code>.env</code> file, <code>data/</code> directory, and media folders beside the executable.

### Linux and macOS

Use the repository's installation and management script. Homebrew is required on macOS. The script prepares the application environment and can register a systemd service on Linux.

~~~bash
curl -fsSL https://raw.githubusercontent.com/ProofPage/Phrolova/main/scripts/manage.sh | bash
~~~

After installation, use the <code>rookery</code> command:

~~~bash
rookery status
rookery start
rookery stop
rookery logs
rookery update
~~~

On macOS, start and stop the app with these commands; systemd is Linux-only. The installer checks for Python 3.10 or later, Node.js 20 or later, and FFmpeg 6 or later. Its static FFmpeg setup supports Linux x86_64 and ARM64 (<code>aarch64</code>).

## Getting started

1. Open **Live Dashboard** and add a channel from a supported service.
2. Enable automatic recording for that channel, or start a manual recording when needed.
3. To download existing media, open **Video Downloads** and enter a supported URL. YouTube channel handles and IDs can add channel videos to the queue.
4. Add any required credentials in **Settings**, then monitor your recordings and downloads in the dashboard and queue.

For X Spaces, set up an X cookie file and add the account or channel to monitor. Phrolova captures a Space while it is live; its audio replay can be downloaded from the X Spaces page afterward.

## Configuration and data

Most options are managed in the web interface. No environment variables are required for basic use. Optional server settings can be set in <code>.env</code>:

| Variable | Default | Purpose |
| --- | --- | --- |
| <code>HOST</code> | <code>0.0.0.0</code> | Address the web server listens on. |
| <code>PORT</code> | <code>8000</code> | Web server port. |
| <code>FFMPEG_PATH</code> | <code>ffmpeg</code> | FFmpeg executable name or path. |
| <code>MONITOR_INTERVAL</code> | <code>60</code> | Channel check interval in seconds. |

The Windows executable reads <code>.env</code> beside itself; source installs read it from the repository root. Recording and download folders can be configured separately in the app. Channel and task data are stored in <code>data/rookery.db</code> beside the Windows executable or <code>backend/data/rookery.db</code> when running from source. Back up the database, <code>.env</code>, and media folders before moving an installation.

Credentials are needed only for services or content that require them:

- **CHZZK:** NID_AUT and NID_SES cookies for age-restricted access or some quality levels.
- **YouTube:** a Netscape-format cookie file for videos requiring an authenticated account.
- **X Spaces:** a Netscape-format X cookie file to monitor and capture Spaces.
- **Discord notifications:** a bot token and channel ID, or a webhook URL.

Phrolova has no user accounts or access control. By default, the server listens on all network interfaces. On a server or shared network, restrict access with a firewall or reverse proxy and do not expose the app directly to the public internet. Never include cookies, tokens, or client secrets in issue reports.

## Troubleshooting

- **Recording does not start:** Check the channel's automatic-recording setting, conditions, and status in the dashboard.
- **FFmpeg is missing:** Install FFmpeg or set <code>FFMPEG_PATH</code> to its executable. The Windows executable does not include FFmpeg.
- **A video cannot be inspected or downloaded:** Confirm that the video is available to your account and supported by the downloader. Add cookies for restricted content, then check the application logs.
- **An X Spaces replay is unavailable:** Only replays captured by Phrolova can be downloaded, and captured replay links expire.

When reporting an issue, include the app version, service, reproduction steps, and relevant logs with credentials removed. Use the [issue tracker](https://github.com/ProofPage/Phrolova/issues).

## Development

The frontend uses React, TypeScript, Vite, and Tailwind CSS. The backend uses FastAPI. Streamlink, yt-dlp, and FFmpeg handle live recording and media downloads.

For source development, use Python 3.12 or later, Node.js 20 or later, and FFmpeg. From the repository root:

~~~bash
git clone https://github.com/ProofPage/Phrolova.git
cd Phrolova
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
~~~

Start the backend in one terminal:

~~~bash
backend/.venv/bin/python backend/run.py
~~~

Start the frontend in another terminal:

~~~bash
cd frontend
npm ci
npm run dev
~~~

Open the Vite URL shown in the terminal. The development server proxies API requests to the backend on port 8000. To serve a production frontend through FastAPI, run <code>npm run build</code> in <code>frontend</code>, then start the backend.

In Windows PowerShell, create the environment with <code>py -3.12 -m venv backend/.venv</code>, install dependencies with <code>backend/.venv/Scripts/python -m pip install -r backend/requirements-dev.txt</code>, and run the backend with <code>backend/.venv/Scripts/python backend/run.py</code>.

See the [contribution guide](CONTRIBUTING.md) for test and frontend-check commands. GitHub Actions runs CI for changes to <code>main</code> and pull requests. Pushing a <code>v*.*.*</code> tag builds and publishes a Windows x64 release.

### Building the Windows executable

The release workflow uses Python 3.12 and Node.js 24. The PyInstaller specification requires Node.js 22 or later. From the repository root, install the packaging dependencies, build the frontend, and package the executable:

~~~powershell
python -m pip install -r backend/requirements.txt pyinstaller pillow pystray
Set-Location frontend
npm ci
npm run build
Set-Location ..
python -m PyInstaller --clean --noconfirm rookery.spec
~~~

The executable is created at <code>dist/Rookery.exe</code>. FFmpeg is not bundled.

## License

Phrolova is distributed under the [MIT License](LICENSE). FFmpeg is distributed separately; see the [FFmpeg legal information](https://ffmpeg.org/legal.html) for licensing terms.

Phrolova is an independent project and is not affiliated with or endorsed by CHZZK, Naver, YouTube, X, or Discord. Follow the applicable service terms and copyright law.
