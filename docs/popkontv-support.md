# PopkonTV support

PopkonTV appears as **팝콘티비** in Korean and **PopkonTV** in the other interface languages. It supports live channel monitoring, Streamlink recording, HLS previews, VODs and clips.

## Links and quality

- Live: `https://www.popkontv.com/live/view?castId=bok0705&partnerCode=P-00117`
- Equivalent live identifier: `bok0705@P-00117`
- VOD: `https://www.popkontv.com/vod/23501`
- Clip: `https://www.popkontv.com/clip/22652`

The channel and partner together identify the broadcast. Bare IDs use `P-00001`; paste the full link when the broadcaster belongs to another partner. Extra share parameters are removed, while duplicate identity parameters and unrelated hosts are rejected.

Live qualities come from the actual HLS master playlist. A requested unavailable quality reports an error; it does not silently select another resolution. Original MP4 videos are offered as the source format because the detail API does not advertise their dimensions. FFprobe reports the real dimensions after download. Existing queue controls, output containers, media inspection and processing history remain in use.

## Authentication and access

Import the account's Netscape cookie file in **Settings → Authentication → PopkonTV**, or configure `POPKONTV_COOKIE_FILE`. Signing in to the Codex browser does not import cookies into the Phrolova server.

Public video requests start without cookies. If authentication is required, the existing cookie fallback retries with the explicitly configured file. The adapter decodes the website's serialized account cookies locally and sends the resulting authorization only to the same-origin PopkonTV API. Expired live and VOD sessions use the official refresh-token API; rotated credentials are persisted atomically, and concurrent refreshes share one request. New connections reload imported credentials and broadcast metadata. Account cookies remain scoped to `popkontv.com`; API bearer tokens and the public web client header are excluded from media requests.

**Record according to the server playback response** is enabled by default. Broadcast types are not rejected locally before requesting playback, but playback still requires a successful API grant independently of HTTP status. An HTTP 200 denial never grants playback. Account, age-verification and viewing-permission requirements remain enforced. Enter a password in the channel's recording settings for a password-protected live room. The password is kept only while Phrolova is running, excluded from settings responses and never written to the configuration file; enter it again after restarting. Errors explain authentication, missing media, maintenance, rate limits or incompatible responses without exposing passwords, account tokens or signed media URLs.

The adapter reads the current public client identifier and web version from the site's normal script assets without executing JavaScript. API requests use the HTTPS same-origin proxy. Live media is restricted to the observed `live-popkontv.hscdn.com` and `vod2.popkontv.hscdn.com` delivery hosts. In-dashboard HLS requests use opaque proxy URLs so signed delivery URLs are not returned to the browser.

## Validation on 2026-10-16

The supplied live channel played in the user's authenticated Codex browser at **1920×1080**, with playback time advancing. The native server without imported account cookies received a login-required response; this was reported as an authentication error. An authenticated native recording from this account was not tested because no cookie file was imported into the test server.

Both supplied video links were downloaded completely through Phrolova's native VOD engine, without cookies, into an isolated test database and output directory:

| Link | Saved media | Duration | Size | Inspection |
| --- | --- | --- | --- | --- |
| `/vod/23501` | MKV, H.264 1920×1080 + AAC | 134.583 s | 104,003,599 bytes | FFprobe and full FFmpeg decode passed |
| `/clip/22652` | MKV, H.264 1080×1920 + AAC | 10.658 s | 971,585 bytes | FFprobe and full FFmpeg decode passed |

Automated tests cover channel/partner identity, URL normalization, denied API responses, cookie decoding and domain scope, adult/locked-content gates, native Streamlink capture and finalization against a local HLS fixture, preview proxy headers and error reasons, API registration, cookie operations, VOD/clip preparation, and responsive layouts at 320, 390, 768 and 1440 pixels. Local fixtures validate the integration without claiming an authenticated production recording.
