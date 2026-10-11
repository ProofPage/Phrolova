"""Keep yt-dlp and Streamlink's percent-encoding wrappers composable."""

def install_media_http_compat():
    # yt-dlp bypasses the wrapped object's __getattr__. Streamlink supplies
    # regex methods through __getattr__, so both imports break URL parsing.
    # Normal attribute lookup preserves both libraries' signed URL policy.
    from yt_dlp.networking import _requests
    wrapper = getattr(_requests, "Urllib3PercentREOverride", None)
    if wrapper is not None:
        wrapper.__getattr__ = lambda self, name: getattr(self.re, name)
