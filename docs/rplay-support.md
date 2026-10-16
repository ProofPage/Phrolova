# RPLAY support

RPLAY appears as **알플레이** in Korean and **RPLAY** in other interface languages. Paste `https://rplay.live/play/<24-character video ID>` into **Videos → RPLAY**. Share parameters and fragments are removed. Live channels are also available in **Live → RPLAY**, using `https://rplay.live/live/<24-character creator ID>` or the creator ID itself.

## Playback and authentication

The adapter requests the website's `/content` API with `requestCanView=true` and uses only a successful `canView.canView === true` grant and its `canView.url`. It never reconstructs a restricted media URL from storage keys or substitutes a preview for the full video. The existing queue, quality selection, pause/cancel, output containers, FFprobe inspection and saved history are reused. HLS, DASH and MP4 delivery are supported; DRM-protected content is rejected.

Public grants do not require an account. Videos requiring a subscription, purchase or adult verification require a session for an account that already has permission. Signing in to the Codex browser does not authenticate the separate Phrolova server.

RPLAY sends an access token in the `Authorization` header, rather than relying on a Netscape cookie file. Import an explicit session JSON under **Settings → Authentication → RPLAY**, or set `RPLAY_SESSION_FILE` to its path. The file format is:

```json
{
  "accessToken": "YOUR_RPLAY_ACCESS_TOKEN",
  "requestorOid": "YOUR_24_CHARACTER_ACCOUNT_ID",
  "loginType": "rplay"
}
```

Use the values from your own authenticated RPLAY session: the `Authorization` header and `requestorOid` query parameter on the site's normal content request. Do not share the file. The import stores only these fields and `loginType`; refresh tokens and unrelated fields are discarded. The application does not extract browser storage, import browser credentials automatically, refresh tokens, subscribe, purchase content or complete identity verification. Replace the file when its access token expires. The status button checks the registered file and any JWT expiry; actual viewing permission is checked for each video by RPLAY.

For videos, account authorization is sent only to `https://api.rplay.live/content`, without following redirects. It is not copied to delivery requests, returned metadata, status responses or download history. Delivery URLs must use the observed RPLAY API/public CDN hosts. Signed URLs and authorization details are redacted in download errors.

## Validation

On 2026-10-16, the supplied video `/play/6a8edff1f1781bc93acb28cf` played at **1920×1080** in the authenticated Codex browser. Playback advanced from 2.11 to 61.43 seconds with `readyState=4` and no media error; the video was paused after testing. Its duration was 8,124 seconds. The native unauthenticated content request returned `canView: false`; the integration reports a login-required error. An authenticated native download of this video has not been verified because no session file was imported into the test server.

Automated tests exercise URL identity, invalid domains, denied grants, HTTP errors, redirects, DRM rejection, token validation and expiry, credential scope, session upload/removal, video-only capabilities, quality extraction and real 1080p and 720p HLS download/remux/FFprobe inspection/history restore using isolated local test media. UI tests cover platform selection, capability fallback, queue preparation and authentication controls at 320, 390, 768 and 1440 pixels.

## Live channels

Live monitoring uses the official `/live/play` viewer API and validates the creator identity. A live channel may be visible while its playback grant is denied; monitoring reports its live state, and recording/preview explains the authentication or viewing-permission error. The same imported RPLAY session is shared with video downloads.

For BytePlus broadcasts, playback also requires the website's `/live/bytedance/auth` grant. A separate `resolution=ud` check controls 1080p availability. Missing UHD permission removes resolutions above 720p rather than silently starting an unauthorized quality. The application never purchases tickets, subscribes, donates or changes verification settings to gain permission.

The adapter resolves the HLS address advertised by the API (`bytePlusPlaybackUrl` for BytePlus, `playUrl` for legacy AWS IVS) through Streamlink. Quality choices come from the HLS master playlist. Broadcasts without advertised HLS playback produce an explicit unsupported-source error. For the official `livestream.rplay.live` delivery host, the explicit session's viewer token is included in the media query used by RPLAY. The API Authorization header is never forwarded to delivery hosts. Streamlink capture, retries, source TS preservation, post-recording container conversion, media inspection and history reuse the existing live pipeline. Browser preview playlists use opaque local asset URLs.

On 2026-10-16, the supplied `/live/6a56030961df0d415aa5b5d5` page loaded a 1280×720 player in the authenticated Codex browser. The native guest API reported an active broadcast but `accessible: false`; attempting playback through the adapter correctly reported a session-required error. A production recording for this account has not been verified because no session file was imported into the test server. Local synthetic HLS tests verify actual 1080p Streamlink capture, MKV finalization, FFprobe inspection and full-resolution frame previews. UI tests cover live registration, offered qualities, access errors and 320–1440px layouts.
