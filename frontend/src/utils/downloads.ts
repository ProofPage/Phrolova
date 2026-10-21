import type { DownloadSource, VodTask } from '../api/client';
import { episodeSourceForHost, parseEpisodeInput } from './episodeSites';
import { canonicalVodUrl } from './vodUrls';
import { canonicalKickVideoUrl } from './kickUrls';
import { canonicalTwitchVideoUrl, TWITCH_HOSTS } from './twitchUrls';
import { canonicalTikTokVideoUrl, TIKTOK_HOSTS } from './tiktokUrls';
import { canonicalBilibiliVideoUrl, BILIBILI_HOSTS } from './bilibiliUrls';
import { canonicalPopkonTVVideoUrl } from './popkontvUrls';
import { canonicalYamiKoreaVideoUrl } from './yamikoreaUrls';
import { canonicalAV19VideoUrl } from './av19Urls';
import { canonicalMissAVVideoUrl } from './missavUrls';

export type { DownloadSource } from '../api/client';
export function detectDownloadPlatform(value: string): DownloadSource {
    if (canonicalMissAVVideoUrl(value)) return 'missav';
    if (canonicalAV19VideoUrl(value)) return 'av19';
    if (canonicalYamiKoreaVideoUrl(value)) return 'yamikorea';
    try {
        const host = new URL(value).hostname;
        const episodeSource = episodeSourceForHost(host);
        if (episodeSource) return episodeSource;
        if (host === 'chzzk.naver.com') return 'chzzk';
        if (['youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be', 'youtube-nocookie.com', 'www.youtube-nocookie.com'].includes(host)) return 'youtube';
        if (TIKTOK_HOSTS.has(host)) return 'tiktok';
        if (host === 'rplay.live' || host === 'www.rplay.live') return 'rplay';
        if (host === 'popkontv.com' || host === 'www.popkontv.com') return 'popkontv';
        if (host === 'hearheart.com' || host === 'www.hearheart.com') return 'hearheart';
        if (BILIBILI_HOSTS.has(host)) return 'bilibili';
        if (TWITCH_HOSTS.has(host)) return 'twitch';
        if (host === 'kick.com' || host === 'www.kick.com') return 'kick';
        if (host === 'ci.me' || host === 'www.ci.me') return 'cime';
    } catch { /* Input may be a supported platform ID. */ }
    return 'external';
}

export function normalizeDownloadInput(value: string, source: DownloadSource): { url: string; collection: boolean; source: DownloadSource } | null {
    if (source === 'missav') {
        const url = canonicalMissAVVideoUrl(value);
        return url ? { url, collection: false, source: 'missav' } : null;
    }
    if (source === 'av19') {
        const url = canonicalAV19VideoUrl(value);
        return url ? { url, collection: false, source: 'av19' } : null;
    }
    let text = value.trim();
    if (source === 'bilibili' && !text.includes('://')) {
        const url = canonicalBilibiliVideoUrl(text);
        return url ? { url, collection: false, source: 'bilibili' } : null;
    }
    if (source === 'youtube') {
        if (/^@[^\s/?#]+$/.test(text)) text = `https://www.youtube.com/${text}`;
        else if (/^[A-Za-z0-9_-]{11}$/.test(text)) text = `https://www.youtube.com/watch?v=${text}`;
    }
    try {
        const parsed = new URL(text);
        if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password || (parsed.port && parsed.port !== '80' && parsed.port !== '443')) return null;
        const host = parsed.hostname.toLowerCase();
        if (host === 'missav123.com' || host === 'www.missav123.com') {
            const url = canonicalMissAVVideoUrl(value);
            return url ? { url, collection: false, source: 'missav' } : null;
        }
        if (host === 'av19t.com' || host === 'www.av19t.com') {
            const url = canonicalAV19VideoUrl(value);
            return url ? { url, collection: false, source: 'av19' } : null;
        }
        if (host === 'ym-05.com' || host === 'www.ym-05.com' || source === 'yamikorea') {
            const url = canonicalYamiKoreaVideoUrl(text);
            return url ? { url, collection: false, source: 'yamikorea' } : null;
        }
        if (episodeSourceForHost(host)) return parseEpisodeInput(text);
        if (['x.com','twitter.com','pscp.tv'].includes(host) || host.endsWith('.pscp.tv')) return null;
        if (host === 'twitcasting.tv' || host.endsWith('.twitcasting.tv')) return null;
        const youtube = ['youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be', 'youtube-nocookie.com', 'www.youtube-nocookie.com'].includes(host);
        if (youtube) {
            const id = host === 'youtu.be' ? parsed.pathname.slice(1).replace(/\/$/, '') : parsed.pathname === '/watch'
                ? parsed.searchParams.get('v') : /^\/(shorts|embed|live)\//.test(parsed.pathname) ? parsed.pathname.split('/')[2] : null;
            if (id && /^[A-Za-z0-9_-]{11}$/.test(id)) return { url: `https://www.youtube.com/watch?v=${id}`, collection: false, source: 'youtube' };
            if (/^\/(?:@[^/]+(?:\/.*)?|channel\/[^/]+(?:\/.*)?|c\/[^/]+(?:\/.*)?|user\/[^/]+(?:\/.*)?)\/?$/.test(parsed.pathname)) {
                parsed.hash = ''; return { url: parsed.href, collection: true, source: 'youtube' };
            }
            return null;
        }
        if (host === 'rplay.live' || host === 'www.rplay.live') {
            const match = parsed.pathname.match(/^\/play\/([a-fA-F0-9]{24})\/?$/);
            return match ? {url:`https://rplay.live/play/${match[1].toLowerCase()}`,collection:false,source:'rplay'} : null;
        }
        if (host === 'popkontv.com' || host === 'www.popkontv.com') {
            const url = canonicalPopkonTVVideoUrl(text);
            return url ? {url,collection:false,source:'popkontv'} : null;
        }
        if (host === 'hearheart.com' || host === 'www.hearheart.com') {
            const match = parsed.pathname.match(/^\/playlist\/(\d+)(?:\/play\/(\d+))?\/?$/);
            if (!match) return null;
            const cleanUrl = match[2] ? `https://hearheart.com/playlist/${match[1]}/play/${match[2]}` : `https://hearheart.com/playlist/${match[1]}`;
            return { url: cleanUrl, collection: !match[2], source: 'hearheart' };
        }
        if (BILIBILI_HOSTS.has(host)) {
            const url = canonicalBilibiliVideoUrl(text);
            return url ? { url, collection: false, source: 'bilibili' } : null;
        }
        if (TIKTOK_HOSTS.has(host)) {
            const url = canonicalTikTokVideoUrl(text);
            return url ? { url, collection: false, source: 'tiktok' } : null;
        }
        if (TWITCH_HOSTS.has(host)) {
            const url = canonicalTwitchVideoUrl(text);
            return url ? { url, collection: false, source: 'twitch' } : null;
        }
        if (host === 'kick.com' || host === 'www.kick.com') {
            const url = canonicalKickVideoUrl(text);
            return url ? { url, collection: false, source: 'kick' } : null;
        }
        if (host === 'chzzk.naver.com') { const url = canonicalVodUrl(text); return url ? { url, collection: false, source: 'chzzk' } : null; }
        if (host === 'ci.me' || host === 'www.ci.me') {
            const match = parsed.pathname.match(/^\/(?:@([A-Za-z0-9_][A-Za-z0-9_.-]{0,99})\/vods\/(\d+)|clips\/(\d+))\/?$/);
            if (!match) return null;
            return { url: match[3] ? `https://ci.me/clips/${match[3]}` : `https://ci.me/@${match[1]}/vods/${match[2]}`, collection: false, source: 'cime' };
        }
        if (source !== 'external') return null;
        parsed.hash = '';
        return { url: parsed.href, collection: false, source: 'external' };
    } catch { return null; }
}

export function parseDownloadInputs(text: string, source: DownloadSource) {
    const entries = text.split(/\s+/).filter(Boolean);
    const unique = new Map<string, { url: string; collection: boolean; source: DownloadSource }>();
    const invalid: string[] = [], duplicates: string[] = [];
    for (const entry of entries) {
        const item = normalizeDownloadInput(entry, source);
        if (!item) invalid.push(entry);
        else if (unique.has(item.url)) duplicates.push(entry);
        else unique.set(item.url, item);
    }
    return { count: entries.length, items: [...unique.values()], invalid, duplicates };
}

export function downloadState(task: VodTask): 'queued' | 'downloading' | 'processing' | 'paused' | 'completed' | 'failed' | 'cancelled' {
    if (task.phase === 'cancelled') return 'cancelled';
    if (task.state === 'completed') return 'completed';
    if (task.state === 'error' || task.phase === 'metadata_error') return 'failed';
    if (task.state === 'paused') return 'paused';
    if (task.state === 'downloading' && ['merging', 'verifying', 'processing'].includes(task.phase ?? '')) return 'processing';
    if (task.state === 'downloading' || task.state === 'cancelling') return 'downloading';
    return 'queued';
}

export const downloadStateLabels = { queued: "settings.waiting", downloading: "download.downloading", processing: "common.processing", paused: "download.paused", completed: "download.completed", failed: "download.failed", cancelled: "download.cancelled" };

export function downloadErrorMessage(task: VodTask): string {
    if (task.phase === 'metadata_error') return "common.couldNotFetchVideoInformation";
    if (/connection|network|timed?\s*out|timeout|HTTP Error 5\d\d/i.test(task.error_message ?? '')) return "common.downloadConnectionInterruptedTryAgain";
    if (/HTTP Error (401|403)|sign.?in|login|cookies|members.only/i.test(task.error_message ?? '')) return "common.cannotAccessTheVideoCheckAuthenticationAndVisibility";
    return "common.theDownloadFailedTryAgainOrCheckTheVideoURLAndAuthenticationSettings";
}
