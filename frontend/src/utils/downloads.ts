import type { DownloadSource, Platform, VodTask } from '../api/client';
import { canonicalVodUrl } from './vodUrls';

export type { DownloadSource } from '../api/client';
export function detectDownloadPlatform(value: string): Platform | 'external' {
    try {
        const host = new URL(value).hostname;
        if (host === 'chzzk.naver.com') return 'chzzk';
        if (['youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be', 'youtube-nocookie.com', 'www.youtube-nocookie.com'].includes(host)) return 'youtube';
        if (host === 'ci.me' || host === 'www.ci.me') return 'cime';
        if (['vod.sooplive.com', 'vod.sooplive.co.kr', 'vod.afreecatv.com'].includes(host)) return 'soop';

    } catch { /* Input may be a supported platform ID. */ }
    return 'external';
}

export function normalizeDownloadInput(value: string, source: DownloadSource): { url: string; collection: boolean; source: DownloadSource } | null {
    let text = value.trim();
    if (source === 'youtube') {
        if (/^@[^\s/?#]+$/.test(text)) text = `https://www.youtube.com/${text}`;
        else if (/^[A-Za-z0-9_-]{11}$/.test(text)) text = `https://www.youtube.com/watch?v=${text}`;
    }
    try {
        const parsed = new URL(text);
        if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password || (parsed.port && parsed.port !== '80' && parsed.port !== '443')) return null;
        const host = parsed.hostname.toLowerCase();
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
        if (host === 'chzzk.naver.com') { const url = canonicalVodUrl(text); return url ? { url, collection: false, source: 'chzzk' } : null; }
        if (host === 'ci.me' || host === 'www.ci.me') {
            const match = parsed.pathname.match(/^\/(?:@([A-Za-z0-9_][A-Za-z0-9_.-]{0,99})\/vods\/(\d+)|clips\/(\d+))\/?$/);
            if (!match) return null;
            return { url: match[3] ? `https://ci.me/clips/${match[3]}` : `https://ci.me/@${match[1]}/vods/${match[2]}`, collection: false, source: 'cime' };
        }
        if (['vod.sooplive.com', 'vod.sooplive.co.kr', 'vod.afreecatv.com'].includes(host)) {
            const match = parsed.pathname.match(/^\/player\/(\d+)(?:\/(catch|catchstory))?\/?$/);
            return match ? { url: `https://vod.sooplive.com/player/${match[1]}${match[2] ? '/' + match[2] : ''}`, collection: false, source: 'soop' } : null;
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

export const downloadStateLabels = { queued: '대기 중', downloading: '다운로드 중', processing: '처리 중', paused: '일시정지', completed: '다운로드 완료', failed: '다운로드 실패', cancelled: '취소됨' };

export function downloadErrorMessage(task: VodTask): string {
    if (task.phase === 'metadata_error') return '영상 정보를 가져오지 못했습니다.';
    if (/connection|network|timed?\s*out|timeout|HTTP Error 5\d\d/i.test(task.error_message ?? '')) return '다운로드 연결이 중단되었습니다. 다시 시도하세요.';
    if (/HTTP Error (401|403)|sign.?in|login|cookies|members.only/i.test(task.error_message ?? '')) return '영상에 접근하지 못했습니다. 인증 및 공개 상태를 확인하세요.';
    return '다운로드를 완료하지 못했습니다. 다시 시도하거나 영상 주소와 인증 설정을 확인하세요.';
}
