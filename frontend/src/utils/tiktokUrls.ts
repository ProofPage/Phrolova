const channelHosts = new Set(['tiktok.com', 'www.tiktok.com', 'm.tiktok.com']);
const shortHosts = new Set(['vm.tiktok.com', 'vt.tiktok.com']);
export const TIKTOK_HOSTS = new Set([...channelHosts, ...shortHosts]);
const username = (value: string) => /^[A-Za-z0-9_.]{1,24}$/.test(value) && !value.endsWith('.') && /[A-Za-z0-9_]/.test(value) ? value.toLowerCase() : null;

function tiktokUrl(value: string): URL | null {
    try {
        const url = new URL(value.trim());
        decodeURIComponent(url.pathname);
        return ['http:', 'https:'].includes(url.protocol) && TIKTOK_HOSTS.has(url.hostname)
            && !url.username && !url.password && !url.port ? url : null;
    } catch { return null; }
}

export function parseTikTokChannelInput(value: string): string | null {
    const text = value.trim();
    if (!text.includes('://')) return username(text.replace(/^@/, ''));
    const url = tiktokUrl(text);
    if (!url || !channelHosts.has(url.hostname)) return null;
    const match = decodeURIComponent(url.pathname).match(/^\/@([^/]+)(?:\/live)?\/?$/);
    return match ? username(match[1]) : null;
}

export function canonicalTikTokVideoUrl(value: string): string | null {
    const url = tiktokUrl(value);
    if (!url) return null;
    const path = decodeURIComponent(url.pathname);
    if (shortHosts.has(url.hostname)) {
        const match = path.match(/^\/([A-Za-z0-9]{1,64})\/?$/);
        return match ? `https://${url.hostname}/${match[1]}/` : null;
    }
    const short = path.match(/^\/t\/([A-Za-z0-9]{1,64})\/?$/);
    if (short) return `https://www.tiktok.com/t/${short[1]}/`;
    const video = path.match(/^\/@([^/]+)\/video\/(\d+)\/?$/);
    if (video && username(video[1])) return `https://www.tiktok.com/@${username(video[1])}/video/${video[2]}`;
    const embed = path.match(/^\/(?:embed\/(?:v2\/)?|share\/video\/)(\d+)\/?$/);
    const mobile = url.hostname === 'm.tiktok.com' ? path.match(/^\/v\/(\d+)\.html$/) : null;
    return embed || mobile ? `https://www.tiktok.com/@_/video/${(embed || mobile)![1]}` : null;
}
