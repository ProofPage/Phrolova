"""Numbered website hosts shared by routing, logging and cookie import."""
import re


NUMBERED_SITE_HOSTS = {
    'tvhot': re.compile(r'tvhot[0-9]+\.com'),
    'toonday': re.compile(r'toonday[0-9]+\.com'),
    'tvroom': re.compile(r'tvroom[0-9]+\.org'),
    'animaru': re.compile(r'animaru[0-9]+\.com'),
    'tvwiki': re.compile(r'tvwiki[0-9]+\.net'),
    'anilife': re.compile(r'anilife[0-9]+\.tv'),
    'zzapflix': re.compile(r'zzap[0-9]+\.com'),
}


def numbered_site_for_host(host: str) -> str | None:
    """Accept a complete ASCII DNS hostname, never a URL or a host prefix."""
    if not isinstance(host, str) or not host.isascii() or any(len(label) > 63 for label in host.split('.')):
        return None
    return next((site for site, rule in NUMBERED_SITE_HOSTS.items() if rule.fullmatch(host.lower())), None)
