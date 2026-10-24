const videoHosts = new Set(['bilibili.com', 'www.bilibili.com', 'm.bilibili.com']);
const shortHosts = new Set(['b23.tv']);
const liveHost = new URL('https://live.bilibili.com').hostname;
export const BILIBILI_HOSTS = new Set([...videoHosts, ...shortHosts, liveHost]);
const positiveId = (value: string) => /^[1-9]\d{0,19}$/.test(value) ? value : null;

function bilibiliUrl(value: string): URL | null {
    try {
        const url = new URL(value.trim());
        decodeURIComponent(url.pathname);
        return ['http:', 'https:'].includes(url.protocol) && BILIBILI_HOSTS.has(url.hostname)
            && !url.username && !url.password && !url.port ? url : null;
    } catch { return null; }
}

export function parseBilibiliChannelInput(value: string): string | null {
    const text = value.trim();
    if (!text.includes('://')) return positiveId(text);
    const url = bilibiliUrl(text);
    if (!url || url.hostname !== liveHost) return null;
    const match = decodeURIComponent(url.pathname).match(/^\/(\d+)\/?$/);
    return match ? positiveId(match[1]) : null;
}

function videoId(value: string): string | null {
    if (/^BV[A-Za-z0-9]{10}$/.test(value)) return value;
    const av = value.match(/^av([1-9]\d{0,19})$/i);
    return av ? `av${av[1]}` : null;
}

export function canonicalBilibiliVideoUrl(value: string): string | null {
    const text = value.trim();
    if (!text.includes('://')) {
        const id = videoId(text);
        return id ? `https://www.bilibili.com/video/${id}/` : null;
    }
    const url = bilibiliUrl(text);
    if (!url) return null;
    const path = decodeURIComponent(url.pathname);
    if (shortHosts.has(url.hostname)) {
        const match = path.match(/^\/([A-Za-z0-9]{1,64})\/?$/);
        return match ? `https://b23.tv/${match[1]}` : null;
    }
    if (!videoHosts.has(url.hostname)) return null;
    const match = path.match(/^\/video\/([^/]+)\/?$/);
    const id = match ? videoId(match[1]) : null;
    if (!id) return null;
    // 회차 선택만 보존해야 공유 추적 변수가 같은 영상을 중복 등록하지 않는다.
    const parts = url.searchParams.getAll('p');
    if (parts.length > 1 || (parts.length && !/^[1-9]\d{0,5}$/.test(parts[0]))) return null;
    return `https://www.bilibili.com/video/${id}/${parts.length && parts[0] !== '1' ? `?p=${parts[0]}` : ''}`;
}
