# Episode-based video sources

The Anilife, Linkani and Ohli24 adapters are adapted from the user-supplied `Plugins.zip` package (Lua API1, version 0.2.7a1). Phrolova uses native Python adapters instead of installing a Lua runtime or executing uploaded scripts.

In **Videos**, select a source and paste a work or episode URL. Work links open an episode picker with search, pagination, unavailable-file status and a limit of 100 selected episodes. Selection adds separate tasks to the existing queue, preserving its quality controls, pause/cancel, persistence, remuxing and media inspection. Valid VTT subtitles are saved beside the video.

| Source | Work | Episode |
| --- | --- | --- |
| Anilife | `https://anilife01.tv/content/<work>` | `/content/<work>/<episode>`; `anilife1.tv` is also accepted |
| Linkani | `https://linkani.tv/ani/<work>/` | `/watch/<work>/a<source>/k<number>/` |
| Ohli24 | `https://www.ohli24.net/<id>/<title>.html` (`ohli24.net` also accepted) | Same URL shape; the page determines whether it is a work or episode |

Only listed episodes are returned. Linkani lists that omit earlier episodes carry an explicit incomplete-list notice; missing episodes are never guessed. Work/episode identity and Ohli24 parent breadcrumbs are checked again before extraction. Site JavaScript is parsed only as normal JSON data, never evaluated.

Requests use HTTPS, bounded responses and explicit site/player/CDN allowlists. Redirect destinations and every manifest reference are checked. Cookies from normal player issuance stay within one extraction/download session, including the transition from metadata extraction to actual media transfer; credentials from other platforms are not borrowed.

Anilife's current guest player first posts to `/api/playback/session`, then requests playback with the issued proof and its matching HttpOnly cookie. Phrolova follows this normal guest-session flow, renews an expired proof once, and sends proof headers only to the issuing API host. Numeric and fractional episode selectors are resolved against the site's catalog. Guest proofs and cookies are kept on the server.

Ohli24 supports the `michealcdn.com` and `cdndania.com` players, the bounded `ohli[1-7]ncloud[1-5]-nocdn.xyz` and `tue[1-7]bcloud-starcdn.xyz` CDN families, and the older `hol[1-7]ncloud2-nocdn.xyz` hosts. The same HTTPS and redirect checks apply to both players. A title containing an unescaped question mark can be resolved using its numeric content ID instead of rejecting the site's own link.

HLS validation accepts ordinary AES-128 with `KEYFORMAT="identity"` and version `1`. Unsupported/protected key formats, malformed or duplicate key attributes, advertising playlists and unfinished live playlists are rejected. The original Lua package's browser-session fallback is not automatically installed; HTTP access failures are reported in the interface.

Validation includes strict URL/redirect tests, all three source parsers, Unicode URLs, episode identity, guest proof/cookie renewal, API-header scope, VTT subtitles, normal AES-128 and encrypted local-media downloads through the actual yt-dlp queue and FFprobe inspection. Session-protected local HLS downloads test all three adapters. Browser tests cover 11 sources, API failures, selection limits, queue payloads, fractional episode selectors, host aliases and 320/390/768/1440px layouts.

Public catalog/playback retrieval was checked against multiple works and episodes. Complete 94-second Anilife and Linkani episodes downloaded through Phrolova's preparation/download flow as approximately 25.8 MB 1920×1080 H.264/AAC MP4 files and passed inspection; Anilife also saved its VTT subtitles. A five-second Ohli24 1080p H.264/AAC sample from the new cdndania player passed download and inspection. Earlier HTTP 403 responses from Anilife playback were resolved by the normal guest-session issuance described above.
