# Episode-based video sources

The Anilife, Linkani and Ohli24 adapters are adapted from the user-supplied `Plugins.zip` package (Lua API1, version 0.2.7a1). Phrolova uses native Python adapters instead of installing a Lua runtime or executing uploaded scripts.

In **Videos**, select a source and paste a work or episode URL. Work links open an episode picker with search, pagination, unavailable-file status and a limit of 100 selected episodes. Selection adds separate tasks to the existing queue, preserving its quality controls, pause/cancel, persistence, remuxing and media inspection. Valid VTT subtitles are saved beside the video.

| Source | Work | Episode |
| --- | --- | --- |
| Anilife | `https://anilife01.tv/content/<work>` | `/content/<work>/<episode>`; `anilife1.tv` is also accepted |
| Linkani | `https://linkani.tv/ani/<work>/` | `/watch/<work>/a<source>/k<number>/` |
| Ohli24 | `https://www.ohli24.net/<id>/<title>.html` | Same URL shape; the page determines whether it is a work or episode |

Only listed episodes are returned. Linkani lists that omit earlier episodes carry an explicit incomplete-list notice; missing episodes are never guessed. Work/episode identity and Ohli24 parent breadcrumbs are checked again before extraction. Site JavaScript is parsed only as normal JSON data, never evaluated.

Requests use HTTPS, bounded responses and explicit site/player/CDN allowlists. Redirect destinations and every manifest reference are checked. Cookies from normal player issuance stay within one extraction/download session; credentials from other platforms are not borrowed. The Ohli24 allowlist includes the seven `ohli*ncloud3-nocdn.xyz` hosts observed in its current issued media playlist, in addition to the supplied package's older hosts.

HLS validation accepts ordinary AES-128 with `KEYFORMAT="identity"` and version `1`. Unsupported/protected key formats, malformed or duplicate key attributes, advertising playlists and unfinished live playlists are rejected. The original Lua package's browser-session fallback is not automatically installed; HTTP access failures are reported in the interface.

Validation includes strict URL/redirect tests, all three source parsers, Unicode URLs, episode identity, VTT subtitles, normal AES-128 and encrypted local-media downloads through the actual yt-dlp queue and FFprobe inspection. The backend suite passed 1,147 tests (2 skipped; 4 subtests passed); TypeScript, production build and 875 keys in eight locales passed. Browser tests cover 11 sources, API failures, selection limits, queue payloads and 320/390/768/1440px layouts.

Public Linkani/Ohli24 catalog and 1080p format retrieval were checked. An entire 112-second Linkani episode downloaded through Phrolova's preparation/download flow as a 31 MB 1920×1080 H.264/AAC MP4 and passed inspection. A four-second Ohli24 1080p H.264/AAC transfer sample also passed FFprobe. The tested server received HTTP 403 from Anilife, so its parser and download contract are covered by isolated fixtures.
