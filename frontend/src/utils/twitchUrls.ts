const channelHosts = new Set(['twitch.tv', 'www.twitch.tv', 'm.twitch.tv', 'go.twitch.tv']);
export const TWITCH_HOSTS = new Set([...channelHosts, 'clips.twitch.tv', 'player.twitch.tv']);
const reserved = new Set(['directory', 'downloads', 'settings', 'login', 'signup', 'videos', 'clip', 'clips', 'collections', 'subscriptions', 'search', 'inventory', 'wallet', 'turbo']);
const channel = (value: string) => /^[A-Za-z0-9_]{1,25}$/.test(value) && !reserved.has(value.toLowerCase()) ? value.toLowerCase() : null;
const clip = (value: string) => /^[A-Za-z0-9_-]{1,200}$/.test(value);

function twitchUrl(value: string): URL | null {
    try {
        const url = new URL(value.trim());
        decodeURIComponent(url.pathname);
        return ['http:', 'https:'].includes(url.protocol) && TWITCH_HOSTS.has(url.hostname)
            && !url.username && !url.password && !url.port ? url : null;
    } catch { return null; }
}

export function parseTwitchChannelInput(value: string): string | null {
    const text = value.trim();
    if (!text.includes('://')) return channel(text);
    const url = twitchUrl(text);
    if (!url || !channelHosts.has(url.hostname)) return null;
    const match = decodeURIComponent(url.pathname).match(/^\/([^/]+)\/?$/);
    return match ? channel(match[1]) : null;
}

export function canonicalTwitchVideoUrl(value: string): string | null {
    const url = twitchUrl(value);
    if (!url) return null;
    const path = decodeURIComponent(url.pathname);
    if (channelHosts.has(url.hostname)) {
        const vod = path.match(/^\/(?:videos\/|[^/]+\/v(?:ideo)?\/)(\d+)\/?$/);
        if (vod) return `https://www.twitch.tv/videos/${vod[1]}`;
        const match = path.match(/^\/(?:[A-Za-z0-9_]{1,25}\/)?clip\/([A-Za-z0-9_-]{1,200})\/?$/);
        return match ? `https://clips.twitch.tv/${match[1]}` : null;
    }
    if (url.hostname === 'clips.twitch.tv') {
        const ids = path.replace(/\/$/, '') === '/embed' ? url.searchParams.getAll('clip') : [path.replace(/^\/+|\/+$/g, '')];
        return ids.length === 1 && clip(ids[0]) ? `https://clips.twitch.tv/${ids[0]}` : null;
    }
    if (url.hostname === 'player.twitch.tv' && ['/', ''].includes(path)) {
        const ids = url.searchParams.getAll('video');
        return ids.length === 1 && /^v?\d+$/.test(ids[0]) ? `https://www.twitch.tv/videos/${ids[0].replace(/^v/, '')}` : null;
    }
    return null;
}
