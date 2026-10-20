import type { DownloadSource } from '../api/client';

const FIXED_EPISODE_HOSTS = new Map<string, DownloadSource>([
    ['reanime.to', 'reanime'], ['www.reanime.to', 'reanime'],
    ['moeni.net', 'moeni'], ['www.moeni.net', 'moeni'],
    ['linkani.tv', 'linkani'], ['www.ohli24.net', 'ohli24'], ['ohli24.net', 'ohli24'],
    ['ani.ohli24.com', 'ohli24'], ['ohli24.com', 'ohli24'], ['www.ohli24.com', 'ohli24'],
    ['v2.ohli365.org', 'ohli365'], ['ohli365.org', 'ohli365'], ['www.ohli365.org', 'ohli365'],
]);
const NUMBERED_EPISODE_HOSTS: [DownloadSource, RegExp][] = [
    ['animaru', /^animaru[0-9]+\.com$/],
    ['tvwiki', /^tvwiki[0-9]+\.net$/], ['anilife', /^anilife[0-9]+\.tv$/],
];
export function episodeSourceForHost(host: string): DownloadSource | undefined {
    if (host.length > 253 || /[\s\x00-\x1f\x7f]/.test(host) || host.split('.').some(label => label.length > 63)) return undefined;
    host = host.toLowerCase();
    return FIXED_EPISODE_HOSTS.get(host) ?? NUMBERED_EPISODE_HOSTS.find(([, pattern]) => pattern.test(host))?.[0];
}
export function parseEpisodeInput(value: string): { url: string; collection: boolean; source: DownloadSource } | null {
    try {
        const text = value.trim();
        if (/[\s\x00-\x1f\x7f\\]/.test(text)) return null;
        const authority = text.match(/^https:\/\/([^/?#]*)/i)?.[1];
        if (!authority || /[^\x21-\x7e]|[%@]/.test(authority)) return null;
        const url = new URL(text);
        const source = episodeSourceForHost(url.hostname);
        if (!source || url.protocol !== 'https:' || url.username || url.password || url.port || /[\x00-\x1f\x7f\\]/.test(decodeURIComponent(url.pathname))) return null;
        if (source === 'ohli365') {
            const titles = url.searchParams.getAll('title'), episodes = url.searchParams.getAll('episode');
            const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
            if (url.pathname !== '/' || titles.length !== 1 || !uuid.test(titles[0]) || episodes.length > 1 ||
                (episodes.length === 1 && episodes[0] !== 'movie' && !uuid.test(episodes[0]))) return null;
            const query = new URLSearchParams({title:titles[0].toLowerCase()});
            if (episodes.length) query.set('episode', episodes[0].toLowerCase());
            return {url:`${url.origin}/?${query}`,collection:episodes.length === 0,source};
        }
        if (source === 'animaru') {
            const match = url.pathname.match(/^\/contents?\/([1-9]\d*)(?:\/((?:0|[1-9]\d*)(?:\.\d+)?))?\/?$/);
            if (!match) return null;
            const raw = match[2];
            if (raw !== undefined && (raw.length > 32 || !Number.isFinite(Number(raw)) || Number(raw) >= 1000000)) return null;
            const episode = raw?.includes('.') ? raw.replace(/0+$/, '').replace(/\.$/, '') : raw;
            return {url:`${url.origin}/content/${match[1]}${episode !== undefined ? '/'+episode : ''}`,collection:episode === undefined,source};
        }
        if (source === 'tvwiki') {
            const match = url.pathname.match(/^\/(movie|kor_movie|drama|ent|sisa|world|ott_ent|short_drama|ani_movie|animation|old_ent|old_drama)\/([1-9]\d*)(?:\/([1-9]\d*))?\/?$/);
            return match ? {url:`${url.origin}/${match[1]}/${match[2]}${match[3]?'/'+match[3]:''}`,collection:!match[3],source} : null;
        }
        if (source === 'anilife') {
            const match = url.pathname.match(/^\/content\/(\d+)(?:\/([A-Za-z0-9_-]+|\d+\.\d+))?\/?$/);
            return match ? {url:`${url.origin}/content/${match[1]}${match[2]?'/'+match[2]:''}`,collection:!match[2],source} : null;
        }
        if (source === 'moeni') {
            const match = url.pathname.match(/^\/([1-9]\d*)(?:\/([1-9]\d*(?:\.\d+)?))?\/?$/);
            return match ? {url:`${url.origin}/${match[1]}${match[2]?'/'+match[2]:''}`,collection:!match[2],source} : null;
        }
        if (source === 'reanime') {
            const animeMatch = url.pathname.match(/^\/anime\/([a-zA-Z0-9_-]+)\/?$/);
            if (animeMatch) return {url:`${url.origin}/watch/${animeMatch[1]}`,collection:true,source};
            const watchMatch = url.pathname.match(/^\/watch\/([a-zA-Z0-9_-]+)\/?$/);
            if (watchMatch) {
                const ep = url.searchParams.get('ep');
                return {url:`${url.origin}/watch/${watchMatch[1]}${ep ? '?ep='+ep : ''}`,collection:!ep,source};
            }
            return null;
        }
        if (source === 'linkani') {
            const episode = url.pathname.match(/^\/watch\/(\d+)\/a(\d+)\/k(\d+)\/?$/);
            if (episode) return {url:`https://linkani.tv/watch/${episode[1]}/a${episode[2]}/k${episode[3]}/`,collection:false,source};
            const work = url.pathname.match(/^\/ani\/(\d+)\/?$/);
            return work ? {url:`https://linkani.tv/ani/${work[1]}/`,collection:true,source} : null;
        }
        if (source === 'ohli24') {
            const newWork = url.pathname.match(/^\/c\/([^/?#]+)\/?$/);
            if (newWork) return {url:`${url.origin}/c/${encodeURIComponent(decodeURIComponent(newWork[1]))}`,collection:true,source};
            const newEp = url.pathname.match(/^\/e\/([^/?#]+)\/?$/);
            if (newEp) return {url:`${url.origin}/e/${encodeURIComponent(decodeURIComponent(newEp[1]))}`,collection:false,source};
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
    return source === 'anilife' || source === 'linkani' || source === 'ohli24' || source === 'ohli365' || source === 'tvwiki' || source === 'animaru' || source === 'moeni' || source === 'reanime';
}
