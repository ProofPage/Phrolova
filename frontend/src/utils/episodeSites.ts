import type { DownloadSource } from '../api/client';

export const EPISODE_HOSTS: Record<string, DownloadSource> = {
    'anilife01.tv': 'anilife', 'anilife1.tv': 'anilife', 'linkani.tv': 'linkani', 'www.ohli24.net': 'ohli24', 'ohli24.net': 'ohli24',
    'tvwiki54.net': 'tvwiki',
};
export function parseEpisodeInput(value: string): { url: string; collection: boolean; source: DownloadSource } | null {
    try {
        const url = new URL(value.trim());
        const source = EPISODE_HOSTS[url.hostname];
        if (!source || url.protocol !== 'https:' || url.username || url.password || url.port || /[\x00-\x1f\x7f\\]/.test(decodeURIComponent(url.pathname))) return null;
        if (source === 'tvwiki') {
            const match = url.pathname.match(/^\/(movie|kor_movie|drama|ent|sisa|world|ott_ent|short_drama|ani_movie|animation|old_ent|old_drama)\/([1-9]\d*)(?:\/([1-9]\d*))?\/?$/);
            return match ? {url:`https://tvwiki54.net/${match[1]}/${match[2]}${match[3]?'/'+match[3]:''}`,collection:!match[3],source} : null;
        }
        if (source === 'anilife') {
            const match = url.pathname.match(/^\/content\/(\d+)(?:\/([A-Za-z0-9_-]+|\d+\.\d+))?\/?$/);
            return match ? {url:`https://anilife01.tv/content/${match[1]}${match[2]?'/'+match[2]:''}`,collection:!match[2],source} : null;
        }
        if (source === 'linkani') {
            const episode = url.pathname.match(/^\/watch\/(\d+)\/a(\d+)\/k(\d+)\/?$/);
            if (episode) return {url:`https://linkani.tv/watch/${episode[1]}/a${episode[2]}/k${episode[3]}/`,collection:false,source};
            const work = url.pathname.match(/^\/ani\/(\d+)\/?$/);
            return work ? {url:`https://linkani.tv/ani/${work[1]}/`,collection:true,source} : null;
        }
        if (!/^\/\d+\/[^/]+\.html$/.test(url.pathname)) {
            const id = url.pathname.match(/^\/(\d+)\/[^/]+$/)?.[1];
            if (!id || !(url.search || url.hash) || !/\.html(?:[?#].*)?$/.test(value.trim())) return null;
            url.pathname = `/${id}/index.html`;
        }
        url.hash=''; url.search='';
        return {url:url.href,collection:true,source};
    } catch { return null; }
}

export function isEpisodeSource(source: DownloadSource) {
    return source === 'anilife' || source === 'linkani' || source === 'ohli24' || source === 'tvwiki';
}
