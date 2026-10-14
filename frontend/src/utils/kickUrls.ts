const slugPattern = /^[A-Za-z0-9_][A-Za-z0-9_-]{0,99}$/;
const reserved = new Set(['api', 'auth', 'browse', 'categories', 'clips', 'following', 'login', 'privacy', 'search', 'settings', 'signup', 'subscriptions', 'terms', 'video', 'videos']);
const slug = (value: string) => slugPattern.test(value) && !reserved.has(value.toLowerCase()) ? value.toLowerCase() : null;

function kickUrl(value: string): URL | null {
    try {
        const url = new URL(value.trim());
        decodeURIComponent(url.pathname);
        return ['http:', 'https:'].includes(url.protocol) && ['kick.com', 'www.kick.com'].includes(url.hostname)
            && !url.username && !url.password && !url.port ? url : null;
    } catch { return null; }
}

export function parseKickChannelInput(value: string): string | null {
    const text = value.trim();
    if (!text.includes('://')) return slug(text);
    const url = kickUrl(text);
    if (!url || url.searchParams.has('clip')) return null;
    const match = decodeURIComponent(url.pathname).match(/^\/([^/]+)\/?$/);
    return match ? slug(match[1]) : null;
}

export function canonicalKickVideoUrl(value: string): string | null {
    const url = kickUrl(value);
    if (!url) return null;
    const path = decodeURIComponent(url.pathname);
    const vod = path.match(/^\/([^/]+)\/videos\/([0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})\/?$/i);
    if (vod && slug(vod[1])) return `https://kick.com/${slug(vod[1])}/videos/${vod[2].toLowerCase()}`;
    const clip = path.match(/^\/([^/]+)\/clips\/(clip_[A-Za-z0-9_-]+)\/?$/);
    if (clip && slug(clip[1])) return `https://kick.com/${slug(clip[1])}/clips/${clip[2]}`;
    const channel = path.match(/^\/([^/]+)\/?$/);
    const ids = url.searchParams.getAll('clip');
    return channel && slug(channel[1]) && ids.length === 1 && /^clip_[A-Za-z0-9_-]+$/.test(ids[0])
        ? `https://kick.com/${slug(channel[1])}/clips/${ids[0]}` : null;
}
