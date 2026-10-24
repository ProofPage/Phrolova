const hosts = new Set(['av19t.com', 'www.av19t.com']);

export function canonicalAV19VideoUrl(value: string): string | null {
    if (/[\x00-\x1f\x7f]/.test(value)) return null;
    const raw = value.trim();
    if (/[\s\\]/.test(raw)) return null;
    const match = raw.match(/^https?:\/\/([^/?#]+)(\/(?:korea|bj|nsub)\/[1-9][0-9]*\/?)(?:[?#].*)?$/i);
    if (!match || /[^\x21-\x7e]|[@%]/.test(match[1])) return null;
    try {
        const url = new URL(raw);
        if (!hosts.has(url.hostname) || url.port || url.username || url.password) return null;
        // Validate the raw path: URL parsing otherwise normalizes traversal segments.
        if (!/^\/(?:korea|bj|nsub)\/[1-9][0-9]*\/?$/.test(match[2])) return null;
        return `https://av19t.com${match[2].replace(/\/$/, '')}`;
    } catch { return null; }
}
