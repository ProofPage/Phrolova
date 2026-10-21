const hosts = new Set(['missav123.com', 'www.missav123.com']);

export function canonicalMissAVVideoUrl(value: string): string | null {
    if (/[\x00-\x1f\x7f]/.test(value)) return null;
    const raw = value.trim();
    if (/[\s\\]/.test(raw)) return null;
    // Inspect the raw authority and path before URL can normalize ports or traversal.
    const match = raw.match(/^https?:\/\/([^/?#]+)\/ko\/([A-Za-z0-9_-]+)\/?(?:[?#].*)?$/i);
    if (!match || !hosts.has(match[1].toLowerCase())) return null;
    try {
        const url = new URL(raw);
        if (!/^\/ko\//.test(url.pathname)) return null;
        return `https://missav123.com/ko/${match[2]}`;
    } catch { return null; }
}
