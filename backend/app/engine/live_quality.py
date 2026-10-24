"""Quality metadata taken from HLS renditions, without assuming aspect ratio or FPS."""
from streamlink.stream.hls.m3u8 import parse_m3u8


def hls_quality_options(text: str, base_url: str) -> list[dict]:
    manifest = parse_m3u8(text, base_uri=base_url)
    options = {}
    for playlist in manifest.playlists:
        if playlist.is_iframe:
            continue
        info = playlist.stream_info
        size = info.resolution
        if not size or not size.height:
            continue
        fps = info.framerate or None
        value = f"{size.height}p" + (f"{fps:g}" if fps else "")
        candidate = {
            "value": value, "label": value, "width": size.width,
            "height": size.height, "fps": fps, "bitrate": info.bandwidth,
        }
        previous = options.get(value)
        if previous is None or (candidate["bitrate"] or 0) > (previous["bitrate"] or 0):
            options[value] = candidate
    return sorted(options.values(), key=lambda item: (
        item["height"], item["fps"] or 0, item["bitrate"] or 0), reverse=True)
