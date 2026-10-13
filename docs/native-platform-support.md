# Native platform support

This document describes the current compatibility patch. Older audit documents remain historical records.

## Implementation

| Area | Behavior |
| --- | --- |
| POSIX lifecycle | Main-thread Uvicorn; per-installation flock and atomic PID metadata; start/command identity checked before SIGTERM; manual stop waits without forced kill |
| macOS | BSD-compatible symlink resolution; Homebrew Python/Node discovery; Finder open/open -R with timeout and exit-status checks |
| Linux | Desktop xdg-open when a display exists; headless path fallback; executable permission checks |
| Native Termux | Native packages/build tools, no managed pip upgrade, plain Uvicorn profile, current dependency import checks |
| proot | PHROLOVA_ENVIRONMENT=termux-proot overrides inherited Termux markers; Linux dependencies; systemd only when running |
| Runtime | Node 22+ and npm validation; packaged/project/PREFIX executable paths; versioned Homebrew fallback |
| Data | Root .env with legacy fallback; configured paths/database preserved; incompatible venv moved to .venv-backups/ |
| Service | Quoted executable/working directory, escaped systemd specifiers, runtime PATH, parent-first shutdown, legacy-service rollback |
| Diagnostics | Portable ps queries; installation-specific server identity; read-only SQLite |

## Automated coverage

CI backend matrix:

- Linux x64 and ARM64, Python 3.12, standard requirements.
- Windows x64, Python 3.12, standard requirements.
- macOS Apple Silicon and Intel, Python 3.12, standard requirements.
- Linux ARM64, Python 3.14, Termux requirements profile.

Jobs install FFmpeg/FFprobe, check dependency consistency and run the full backend suite. POSIX jobs check shell syntax. Frontend CI checks eight locale resources, locale formatting, TypeScript and production builds.

Native-management regressions cover PID reuse, duplicate startup, graceful-stop timeout, startup-failure cleanup, BSD symlinks/custom paths, Homebrew tools, distribution-specific Node packages, non-executable runtimes, headless/file-manager failure behavior, repeated Termux installation, settings/database preservation and incompatible-venv backup. Real child-process locking/SIGTERM tests run on POSIX runners.

Existing tests cover recording source preservation, TS/MKV/MP4 finalization/validation, cancellation, queue/concurrency behavior, API compatibility and migrations. They use controlled media/network fixtures rather than arbitrary live broadcasts.

## Device validation scope

The local host is Windows. Linux/macOS execution is validated through GitHub-hosted CI. Linux ARM64/Python 3.14 validates the Termux dependency profile, not Android ABI compatibility. Actual Termux compilation and background recording under Android power management require device validation; no Android device was available for this task.

## Primary references

- [yt-dlp EJS runtime requirements](https://github.com/yt-dlp/yt-dlp/wiki/EJS)
- [Homebrew installation and prefixes](https://docs.brew.sh/Installation)
- [GitHub-hosted runner platforms](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
- [Termux installation](https://github.com/termux/termux-app#installation)

[README](../README.md) · [Linux](linux-guide.md) · [macOS](macos-guide.md) · [Termux](termux-guide.md)
