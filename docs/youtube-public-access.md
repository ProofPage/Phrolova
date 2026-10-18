# YouTube public access

## Diagnosis (2026-10-14)

The submitted URLs `https://youtu.be/oDpUL5aHVK4` and `https://youtu.be/MFRcNvE-dGA` both returned YouTube's “Sign in to confirm you're not a bot” response with yt-dlp 2026.08.19, without account cookies. The same response also affected unrelated public content on the test server.

This is a guest-access challenge, distinct from private videos, membership entitlements or age verification. It does not establish that the submitted videos require account cookies. YouTube's response alone does not identify whether the trigger is the server IP, session, traffic rate or another network signal.

The official 2026.10.10.233141 development build includes the new `tv_samsung` client. It retrieved 36 formats for `MFRcNvE-dGA` once without account cookies in an isolated comparison. Subsequent metadata, five-second media-download and live-HLS attempts still received bot challenges. A complete real download or live capture was **not** validated on this network.

The helper was stopped after the test.

## Application changes

- Set the yt-dlp dependency floor to the official October 2026 client update, keeping its default client selection instead of hardcoding retired clients or accepting incomplete formats.
- Apply Node/EJS settings to video metadata, downloads and channel imports. Pace extractor requests and add a randomized delay before media downloads.
- Run live detection, capture-URL resolution and previews with the same installed Python yt-dlp as video downloads. Source installations use a small worker; Windows packages invoke their own isolated worker entry point. Cancellation terminates and reaps the worker process.
- Retain the temporary anonymous session between metadata extraction and download processing. It stays in memory and does not read browser account cookies or require a cookie upload.
- Start previews without account cookies, so an outdated saved cookie path does not break otherwise public playback. Preserve explicit cookie fallback for account-restricted content.
- Classify guest bot checks and HTTP 429 separately, display actionable localized messages and avoid automatic download retry storms. Preserve permission errors for private, age-restricted and members-only content.

## Automatic runtime setup

Phrolova prepares Deno 2.9.7 and the matching bgutil server/plugin 2.0.2 in its persistent `data/youtube-tools` directory. Official downloads are checked against pinned SHA-256 hashes before installation. Startup waits for the preparation result before starting application services. The console and service log show setup stages and failures; failures are reported as warnings, allowing other platforms to remain available.

On later launches, Phrolova verifies the installed Deno executable, plugin archive and required server files, checks that Deno runs, and skips downloading and installing healthy components. It reuses a matching server or starts its own server bound only to `127.0.0.1:4416`. Only the process started by Phrolova is terminated and reaped on shutdown. Leave the provider URL blank for automatic setup; entering the default loopback URL also uses the managed local server. Clearing and saving a custom URL restores automatic mode. An explicitly configured external provider URL is retained.

The Python API and live worker use `youtubepot-bgutilhttp:base_url` and the same plugin/runtime paths. Channel imports share the setup. An installation failure is logged and is not marked successful; it is not repeatedly retried for every video in that process. Restart after correcting the reported cause. Initial installation requires internet access and may take several minutes. Windows, macOS and GNU/Linux x64/ARM64 assets are supported; native Android/Termux needs a compatible manually prepared runtime/provider.

Successful installation and `/ping` health are not proof of token generation or YouTube playback. A production Windows check generated a token through `/get_pot` after a second launch skipped installation. YouTube may still require valid cookies or reject the network connection.

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
