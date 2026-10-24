const hosts = new Set(['pandalive.co.kr', 'www.pandalive.co.kr']);
const validId = (id: string): string | null => /^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$/.test(id) ? id.toLowerCase() : null;

export function parsePandaliveChannelInput(value: string): string | null {
    const text = value.trim();
    if (/[\x00-\x20\\]/.test(text)) return null;
    if (!text.includes('://')) return validId(text);
    try {
        const authority = text.match(/^https?:\/\/([^/?#]*)/i)?.[1];
        if (!authority || /[^\x21-\x7e]|[@%]/.test(authority)) return null;
        const url = new URL(text);
        if (!['http:', 'https:'].includes(url.protocol) || !hosts.has(url.hostname) || url.username || url.password || url.port) return null;
        const match = decodeURIComponent(url.pathname).match(/^\/play\/([A-Za-z0-9][A-Za-z0-9_-]{0,99})\/?$/);
        return match ? validId(match[1]) : null;
    } catch { return null; }
}
