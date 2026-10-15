# Episode-based video sources

The Anilife, Linkani and Ohli24 adapters are adapted from the user-supplied `Plugins.zip` package (Lua API1, version 0.2.7a1). Phrolova uses native Python adapters instead of installing a Lua runtime or executing uploaded scripts.

In **Videos**, select a source and paste a work or episode URL. Work links open an episode picker with search, pagination, unavailable-file status and a limit of 100 selected episodes. Selection adds separate tasks to the existing queue, preserving its quality controls, pause/cancel, persistence, remuxing and media inspection. Valid VTT subtitles are saved beside the video.

| Source | Work | Episode |
| --- | --- | --- |
| Anilife | `https://anilife01.tv/content/<work>` | `/content/<work>/<episode>`; `anilife1.tv` is also accepted |
| Linkani | `https://linkani.tv/ani/<work>/` | `/watch/<work>/a<source>/k<number>/` |
| Ohli24 | `https://www.ohli24.net/<id>/<title>.html` (`ohli24.net` also accepted) | Same URL shape; the page determines whether it is a work or episode |
| TVWiki (티비위키) | `https://tvwiki54.net/<category>/<work>` | `/<category>/<work>/<episode>`; categories include drama, ent, movie and animation |

Only listed episodes are returned. Linkani lists that omit earlier episodes carry an explicit incomplete-list notice; missing episodes are never guessed. Work/episode identity and Ohli24 parent breadcrumbs are checked again before extraction. Site JavaScript is parsed only as normal JSON data, never evaluated.

Requests use HTTPS, bounded responses and explicit site/player/CDN allowlists. Redirect destinations and every manifest reference are checked. Cookies from normal player issuance stay within one extraction/download session, including the transition from metadata extraction to actual media transfer; credentials from other platforms are not borrowed.

TVWiki is a separate Videos source. Its catalog uses the site's actual episode links, with duplicate thumbnail links removed. The adapter follows the current guest session and player configuration requests, parses configuration data without executing site JavaScript, and validates the issued HLS playlist and its resources. It prefers the player's advertised native/casting HLS rendition and registers its ordinary guest session on that rendition's issuing host. Standard 16-byte AES-128 keys use the existing native downloader and local remux/inspection pipeline; browser-specific key decoders are not executed. A denied site/player response is reported as an access error.

If an advertised TVWiki CDN fragment fails, the downloader retries that exact playlist resource on the issuing media server, preserving its path and query. This retry applies only to validated playlist resources and media hosts, strips explicit cross-host credentials, and keeps the existing cookie jar's domain rules. A failed CDN host is avoided for subsequent fragments of the same task; unavailable fragments are never silently skipped.

The October 16, 2026 TVWiki check retrieved a 14-episode public catalog and downloaded a complete 1,375.354-second episode through the actual VOD engine, including origin recovery for blocked CDN fragments. The final 631,200,903-byte MKV contains 1920×1080 H.264 video and AAC audio, passed media inspection, and completed a full FFmpeg decode with no errors. Tests also cover native guest-session issuance, key validation, origin/resource boundaries, encrypted local HLS downloads, all 13 source choices, episode-to-queue requests, and 320/390/768/1440-pixel layouts.

Some connections reset before the site's HTTPS handshake finishes. In that case the site client retries the same allowed host once, splitting the TLS ClientHello across standard TLS records. The original certificate/hostname verification, cookies and proxy settings remain in use. HTTP errors, certificate failures and resets while reading an HTTP response do not trigger this retry; a session-creation POST is never repeated after it has been sent.

Anilife's current guest player first posts to `/api/playback/session`, then requests playback with the issued proof and its matching HttpOnly cookie. Phrolova follows this normal guest-session flow, renews an expired proof once, and sends proof headers only to the issuing API host. Numeric and fractional episode selectors are resolved against the site's catalog. Guest proofs and cookies are kept on the server.

Ohli24 supports the `michealcdn.com` and `cdndania.com` players, the bounded `ohli[1-7]ncloud[1-5]-nocdn.xyz` and `tue[1-7]bcloud-starcdn.xyz` CDN families, and the older `hol[1-7]ncloud2-nocdn.xyz` hosts. The same HTTPS and redirect checks apply to both players. A title containing an unescaped question mark can be resolved using its numeric content ID instead of rejecting the site's own link.

HLS validation accepts ordinary AES-128 with `KEYFORMAT="identity"` and version `1`. Unsupported/protected key formats, malformed or duplicate key attributes, advertising playlists and unfinished live playlists are rejected. The original Lua package's browser-session fallback is not automatically installed; HTTP access failures are reported in the interface.

Validation includes strict URL/redirect tests, all three source parsers, Unicode URLs, episode identity, guest proof/cookie renewal, API-header scope, VTT subtitles, normal AES-128 and encrypted local-media downloads through the actual yt-dlp queue and FFprobe inspection. Session-protected local HLS downloads test all three adapters. Browser tests cover 11 sources, API failures, selection limits, queue payloads, fractional episode selectors, host aliases and 320/390/768/1440px layouts.

TLS recovery tests include real local HTTPS with a trusted certificate, rejection of an untrusted certificate and a mismatched hostname, connection reuse, cookie persistence, proxy-pool preservation and a reset followed by exactly one real session-creation POST. Record splitting preserves every handshake byte and leaves unrelated hosts and application-data records unchanged.

Public catalog/playback retrieval was checked against multiple works and episodes. Complete 94-second Anilife and Linkani episodes downloaded through Phrolova's preparation/download flow as approximately 25.8 MB 1920×1080 H.264/AAC MP4 files and passed inspection; Anilife also saved its VTT subtitles. A five-second Ohli24 1080p H.264/AAC sample from the new cdndania player passed download and inspection. Earlier HTTP 403 responses from Anilife playback were resolved by the normal guest-session issuance described above.

The October 15, 2026 retest recovered catalog/playback access to all three sites after TLS connection resets. An Anilife episode using the TVWiki provider downloaded all 685 HLS fragments into a 699,204,092-byte 1920×1080 H.264/AAC MP4, lasting 1,370.368 seconds. FFprobe and five-second decode checks at the beginning, middle and end passed. New complete 94-second Anilife/Linkani downloads and a 10-second Ohli24 native-HLS sample also passed media inspection. Downloading uses native HLS before local remuxing, including CDN segments whose URL extension is not a media extension.
