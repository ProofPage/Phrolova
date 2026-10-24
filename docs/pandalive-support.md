# PandaTV live support

Select **PandaTV** in Live (**팬더티비** in Korean) and enter a channel ID or `https://www.pandalive.co.kr/play/<channel>`. The existing download settings dialog controls automatic recording, available HLS quality and output container. The platform is live-only; the 16 existing video sources are unchanged.

The adapter uses the website's public `/v1/member/bj` and `/v1/live/play` requests. Channel IDs and returned media identities must match. It distinguishes ended broadcasts, missing channels, identity verification, password protection, access denial, rate limits and transient network errors. An authentication response is not saved as an offline broadcast or retried as a network failure.

Streamlink parses the advertised HLS playlist and captures the selected rendition. The existing recording finalizer closes the source before remuxing to MKV or MP4 and inspecting the result. Player headers are preserved. HLS addresses are limited to the platform and its observed AWS IVS delivery domain; unsupported qualities are reported instead of silently recording another quality.

The browser player uses the application's same-origin preview proxy. Playlist, key and fragment URIs, including AWS IVS `EXT-X-PREFETCH` references, are rewritten to opaque application URLs. Upstream signed URLs and cookie values are not passed to the interface. Cross-origin private addresses and unrelated media servers are rejected.

For broadcasts that require account access, upload a Netscape cookie file under **Settings → Authentication → PandaTV**, or set `PANDALIVE_COOKIE_FILE` for a source installation. Complete any required identity verification on the official website first. The importer retains only cookies scoped to `pandalive.co.kr`; they are not copied to AWS IVS or other platforms. Browser sign-in does not automatically import credentials into the server. File registration validates its format and scope, not the account's entitlement to every broadcast.

## Verification

On October 16, 2026, `pretty1216` returned five advertised qualities: 1080p, 720p, 480p, 360p and 160p. The actual Streamlink recording pipeline captured 26.005 seconds and the existing finalizer produced a 23,159,532-byte MKV with 1920×1080 30fps H.264 video and AAC audio. Inspection and full FFmpeg decoding passed without a cookie file.

The supplied `100zzi` channel returned HTTP 400 with an identity-verification requirement to the unauthenticated server. In the user's already signed-in Codex browser, the same channel decoded 1920×1080 video with ready state 4, playback active and no player error. This browser result is separate from cookie-authenticated recording through Phrolova.

The actual Phrolova engine and preview API also served `pretty1216` through opaque same-origin URLs to a Chromium player. It decoded 1920×1080 video with ready state 4, advanced from 22.09 to 26.28 seconds with no player error, and had no horizontal overflow at a 390-pixel viewport. A separate injected CDN 503 response produced a sanitized API error without exposing the fixture token.

Regression coverage includes API identity checks, authentication errors, cookie isolation, URL parsing, HLS quality selection, real local capture/finalization and low-latency preview URI boundaries. Browser integration checks nine live platforms, unchanged video sources, registration, cookies, dynamic quality, 19 frontend/backend URL cases and 320/390/768/1440-pixel layouts.
