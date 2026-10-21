const hosts = new Set(['ym-05.com', 'www.ym-05.com']);

export function canonicalYamiKoreaVideoUrl(value: string): string | null {
    const raw = value.trim();
    if (/[\s\x00-\x1f\x7f\\]/.test(raw)) return null;
    const authority = raw.match(/^https?:\/\/([^/?#]*)/i)?.[1];
    if (!authority || /[^\x21-\x7e]|[@%]/.test(authority)) return null;
    try {
        const url = new URL(raw);
        if (!hosts.has(url.hostname) || url.port || url.username || url.password) return null;
        const match = url.pathname.match(/^\/videos\/([^/]+)\/?$/);
        if (!match) return null;
        const slug = decodeURIComponent(match[1]);
        if (!/^[^\s\x00-\x1f\x7f/?#%\\]+$/.test(slug) || slug === '.' || slug === '..') return null;
        return `https://ym-05.com/videos/${encodeURIComponent(slug)}/`;
    } catch { return null; }
}
