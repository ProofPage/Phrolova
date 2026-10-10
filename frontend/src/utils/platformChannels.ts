import type { Platform } from '../api/client';
import { parseChzzkChannelInput } from './chzzkChannel';

export const SOOP_CHANNEL_HOSTS = new Set(['play.sooplive.co.kr', 'play.sooplive.com', 'www.sooplive.com', 'station.sooplive.com', 'play.afreecatv.com', 'bj.afreecatv.com']);

/** Normalize user input, never send a URL with credentials to a platform API. */
export function parsePlatformChannelInput(platform: Platform, value: string): string | null {
    const text = value.trim();
    if (platform === 'chzzk') return parseChzzkChannelInput(text);
    if (platform !== 'soop' && platform !== 'cime') return text || null;
    const validId = (id: string) => (platform === 'soop' ? /^[A-Za-z0-9_]{1,100}$/ : /^[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}$/).test(id) ? platform === 'soop' ? id.toLowerCase() : id : null;
    if (!text.includes('://')) return validId(platform === 'cime' ? text.replace(/^@/, '') : text);
    try {
        const url = new URL(text);
        if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || url.port) return null;
        if (platform === 'cime') {
            if (url.hostname !== 'ci.me' && url.hostname !== 'www.ci.me') return null;
            const match = url.pathname.match(/^\/@([A-Za-z0-9_.-]+)(?:\/live)?\/?$/);
            return match ? validId(match[1]) : null;
        }
        if (!SOOP_CHANNEL_HOSTS.has(url.hostname)) return null;
        const match = url.pathname.match(url.hostname === 'www.sooplive.com' ? /^\/(?:station\/)?([A-Za-z0-9_]+)\/?$/ : /^\/([A-Za-z0-9_]+)(?:\/\d+)?\/?$/);
        return match ? validId(match[1]) : null;
    } catch { return null; }
}
