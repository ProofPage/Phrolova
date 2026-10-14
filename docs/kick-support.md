# Kick live recording and video downloads

Kick is available in both the Live platform selector and the Videos source selector.

- Live channel URL: `https://kick.com/channel-name`, or enter the channel slug directly.
- VOD URL: `https://kick.com/channel-name/videos/<uuid>`.
- Clip URL: `https://kick.com/channel-name/clips/clip_<id>`. Shared `?clip=` links are normalized to this form.

Channel monitoring reads Kick's public channel metadata. Live stream extraction and capture use **Streamlink**, including its Kick plugin and HLS reader. Live previews use the existing opaque HLS proxy. Videos and clips use the installed **yt-dlp** Kick extractors and the existing download queue, file inspection and persistence.

## Authentication and 1080p

Open **Settings → Authentication → Kick** and register a Netscape-format cookie file exported from a signed-in Kick browser session. The card supports replacement, local status/expiry checks and removal. Source installations may alternatively configure `KICK_COOKIE_FILE` with a local file path. Status checks inspect the file; they do not claim that the account is accepted by Kick.

Registered, unexpired Kick cookies are used for both live quality resolution and video metadata/downloads. This is intentional: public extraction can succeed with a reduced quality list even when higher qualities require sign-in. Refresh the live quality list or retry video metadata after registering or replacing cookies. Each request borrows the current file; no restart is needed.

Only qualities returned by the current stream are displayed. `best` selects the highest available quality. An explicitly requested 1080p or higher resolution that is unavailable fails clearly instead of silently saving a 720p file. Authentication cannot add a resolution that the broadcaster does not provide.

Cookie contents and API tokens are not returned in API responses or placed in browser state. Uploaded files are limited to 1 MB and filtered to Kick domains. Borrowed yt-dlp cookie files are removed after use. Streamlink's bearer authorization is applied only to HTTPS Kick API requests; cookies follow their own domain scope. Neither is copied into CDN recording headers.

## Errors

API access denial, missing/deleted content and request throttling have separate Kick error codes. A failed or malformed API response is not reported as an offline channel. Existing monitoring backoff handles temporary connection/rate failures; permanent access or unavailable-quality failures do not trigger recording retry storms.

## Validation on 2026-10-14

- Real public live capture through the app's Streamlink pipeline: about 12 seconds of MPEG-TS, H.264 video at 640×360 and AAC audio. FFprobe passed.
- Real public VOD through the app's download queue: complete 592-second sample, saved as MP4 (about 47.3 MB), with H.264 video and AAC audio. File inspection passed.
- Authenticated tests use isolated cookie/API fixtures to check API-only bearer headers, cookie scope, 1080p quality discovery and selection, cookie replacement/removal, and temporary-file cleanup. A real signed-in 1080p download was not tested because no Kick account cookies were supplied.
- Chromium checks cover cookie registration, public/authenticated quality lists, 1080p channel registration, VOD preparation and layouts at 360, 390, 768 and 1440 pixels.
- Full backend regression suite: **1,003 passed, 2 skipped**, with 4 subtests passed. The final cookie-scope and VOD UI checks also passed (51 tests).
- All 849 translation keys across eight languages, translation behavior checks, TypeScript and production frontend build passed.
- Windows PyInstaller build passed. The packaged archive contains the app's Kick engine, Streamlink Kick plugin, yt-dlp Kick extractor and the final cookie-cache isolation fix. The isolated extractor worker started successfully.

Upstream references: [Streamlink Kick plugin](https://github.com/streamlink/streamlink/blob/master/src/streamlink/plugins/kick.py), [yt-dlp Kick extractors](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/kick.py).
