import type { Platform } from '../api/client';
import { parseChzzkChannelInput } from './chzzkChannel';
import { parseKickChannelInput } from './kickUrls';
import { parseTwitchChannelInput } from './twitchUrls';
import { parseTikTokChannelInput } from './tiktokUrls';
import { parseBilibiliChannelInput } from './bilibiliUrls';
import { parsePandaliveChannelInput } from './pandaliveUrls';
import { parsePopkonTVChannelInput } from './popkontvUrls';

/** Normalize user input, never send a URL with credentials to a platform API. */
export function parsePlatformChannelInput(platform: Platform, value: string): string | null {
    const text = value.trim();
    if (platform === 'rplay') {
        if (/^[a-fA-F0-9]{24}$/.test(text)) return text.toLowerCase();
        try {
            const url = new URL(text);
            if (!['https:', 'http:'].includes(url.protocol) || !['rplay.live','www.rplay.live'].includes(url.hostname) || url.username || url.password || url.port) return null;
            const match = url.pathname.match(/^\/(?:live|creatorhome)\/([a-fA-F0-9]{24})\/?$/);
            if (match) return match[1].toLowerCase();
            const handleMatch = url.pathname.match(/^\/c\/([^/?#]+)\/?$/);
            if (handleMatch) return text;
            return null;
        } catch { return null; }
    }
    if (platform === 'popkontv') return parsePopkonTVChannelInput(text);
    if (platform === 'pandalive') return parsePandaliveChannelInput(text);
    if (platform === 'twitcasting') {
        if (/^[A-Za-z0-9_.-]{1,60}$/.test(text)) return text.toLowerCase();
        try {
            const url = new URL(text.startsWith('http') ? text : `https://${text}`);
            if (!['twitcasting.tv', 'www.twitcasting.tv'].includes(url.hostname)) return null;
            const pathParts = url.pathname.split('/').filter(p => p && p !== 'live' && p !== 'show' && p !== 'broadcaster');
            if (pathParts.length > 0 && /^[A-Za-z0-9_.-]{1,60}$/.test(pathParts[0])) {
                return pathParts[0].toLowerCase();
            }
            return null;
        } catch { return null; }
    }
    if (platform === 'tiktok') return parseTikTokChannelInput(text);
    if (platform === 'bilibili') return parseBilibiliChannelInput(text);
    if (platform === 'twitch') return parseTwitchChannelInput(text);
    if (platform === 'kick') return parseKickChannelInput(text);
    if (platform === 'chzzk') return parseChzzkChannelInput(text);
    if (platform === 'youtube') {
        let val = text.trim();
        if (!val) return null;
        if (val.startsWith('@http')) val = val.slice(1);
        if (val.startsWith('@') && !val.startsWith('@http')) return val;
        if (/^UC[A-Za-z0-9_-]{22}$/.test(val)) return val;
        if (/^[A-Za-z0-9_-]{11}$/.test(val)) return val;
        try {
            const url = new URL(val.startsWith('http') ? val : `https://${val}`);
            if (!['youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'].includes(url.hostname)) return val;
            const handle = url.pathname.match(/^\/@([A-Za-z0-9_.-]+)(?:\/live)?\/?$/);
            if (handle) return `@${handle[1]}`;
            const channel = url.pathname.match(/^\/channel\/(UC[A-Za-z0-9_-]{22})(?:\/live)?\/?$/);
            if (channel) return channel[1];
            const liveVid = url.pathname.match(/^\/live\/([A-Za-z0-9_-]{11})\/?$/);
            if (liveVid) return liveVid[1];
            const shortsVid = url.pathname.match(/^\/shorts\/([A-Za-z0-9_-]{11})\/?$/);
            if (shortsVid) return shortsVid[1];
            const watchVid = url.searchParams.get('v');
            if (watchVid && /^[A-Za-z0-9_-]{11}$/.test(watchVid)) return watchVid;
            if (url.hostname === 'youtu.be') {
                const shortVid = url.pathname.slice(1).split('/')[0];
                if (/^[A-Za-z0-9_-]{11}$/.test(shortVid)) return shortVid;
            }
            return val;
        } catch { return val; }
    }
    if (platform !== 'cime') return text || null;
    const validId = (id: string) => /^[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}$/.test(id) ? id : null;
    if (!text.includes('://')) return validId(text.replace(/^@/, ''));
    try {
        const url = new URL(text);
        if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || url.port) return null;
        if (url.hostname !== 'ci.me' && url.hostname !== 'www.ci.me') return null;
        const match = url.pathname.match(/^\/@([A-Za-z0-9_.-]+)(?:\/live)?\/?$/);
        return match ? validId(match[1]) : null;
    } catch { return null; }
}
