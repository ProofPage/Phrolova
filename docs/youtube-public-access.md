# YouTube public access

## Diagnosis (2026-10-14)

The submitted URLs `https://youtu.be/oDpUL5aHVK4` and `https://youtu.be/MFRcNvE-dGA` both returned YouTube's “Sign in to confirm you're not a bot” response with yt-dlp 2026.08.19, without account cookies. The same response also affected unrelated public content on the test server.

This is a guest-access challenge, distinct from private videos, membership entitlements or age verification. It does not establish that the submitted videos require account cookies. YouTube's response alone does not identify whether the trigger is the server IP, session, traffic rate or another network signal.

The official 2026.10.10.233141 development build includes the new `tv_samsung` client. It retrieved 36 formats for `MFRcNvE-dGA` once without account cookies in an isolated comparison. Subsequent metadata, five-second media-download and live-HLS attempts still received bot challenges. A complete real download or live capture was **not** validated on this network.

An isolated test with bgutil-ytdlp-pot-provider 2.0.2 successfully started its local HTTP provider and generated player PO tokens for both `mweb` and `tv_samsung`. The request for `MFRcNvE-dGA` still returned the same bot challenge with no formats. The helper was stopped after the test and is not a product dependency. This matches the upstream known-issues guidance: a PO-token provider cannot remove an existing IP-based login restriction. The October client fixes address separate playback failures and do not establish that this guest-access challenge is resolved.

## Application changes

- Set the yt-dlp dependency floor to the official October 2026 client update, keeping its default client selection instead of hardcoding retired clients or accepting incomplete formats.
- Apply Node/EJS settings to video metadata, downloads and channel imports. Pace extractor requests and add a randomized delay before media downloads.
- Run live detection, capture-URL resolution and previews with the same installed Python yt-dlp as video downloads. Source installations use a small worker; Windows packages invoke their own isolated worker entry point. Cancellation terminates and reaps the worker process.
- Retain the temporary anonymous session between metadata extraction and download processing. It stays in memory and does not read browser account cookies or require a cookie upload.
- Start previews without account cookies, so an outdated saved cookie path does not break otherwise public playback. Preserve explicit cookie fallback for account-restricted content.
- Classify guest bot checks and HTTP 429 separately, display actionable localized messages and avoid automatic download retry storms. Preserve permission errors for private, age-restricted and members-only content.

## Deployment

Source installations must install the updated `backend/requirements.txt`, or `backend/requirements-termux.txt` for native Termux, and restart. Windows needs a newly built package to receive the updated embedded extractor and worker. Updating an external `yt-dlp.exe` alone does not update the embedded Python package.

No browser profiles, exported account cookies, third-party download services, random proxies or certificate-validation bypasses are used by this patch.

If a public request still receives a bot challenge, verify the connection on the **machine running Phrolova**, including any configured VPN/proxy, and allow time before retrying. For the reported VPS deployment, the next diagnostic step without account cookies is to repeat the request through a different outbound connection, such as the user's own normal internet connection. This requires a network change; the application patch cannot clear a restriction imposed by YouTube on the existing connection.

## Validation

- Backend suite: 966 passed, 2 skipped, with 4 subtests passed.
- Frontend: all 842 translation keys across 8 locales, translation checks, TypeScript and production build passed.
- Windows: a fresh PyInstaller package ran its isolated YouTube worker and reported yt-dlp `2026.10.10.233141`. The worker module, Node and EJS assets were bundled; the worker did not initialize server storage.
- Regression coverage includes shared extraction/download runtime settings and anonymous sessions, public-first preview behavior with stale saved cookies, access-error classification and worker cancellation cleanup.
- Network validation remains unsuccessful for the submitted URLs. These checks validate the application changes, not successful public YouTube downloading from this VPS.

## References

- [Official client update](https://github.com/yt-dlp/yt-dlp/pull/17805)
- [Known issues: guest IP blocks and PO-token limitations](https://github.com/yt-dlp/yt-dlp/issues/3766)
- [YouTube extractor guidance](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#youtube)
- [JavaScript runtime and EJS setup](https://github.com/yt-dlp/yt-dlp/wiki/EJS)
- [PO Token Guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide)
- [Provider verification and limitations](https://github.com/Brainicism/bgutil-ytdlp-pot-provider#verification)
