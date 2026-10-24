const hosts = new Set(['www.popkontv.com', 'popkontv.com']);

function popkonUrl(value: string): URL | null {
    const raw = value.trim();
    if (/[\x00-\x20\\]/.test(raw)) return null;
    const authority = raw.match(/^https?:\/\/([^/?#]*)/i)?.[1];
    if (!authority || /[^\x21-\x7e]|[@%]/.test(authority)) return null;
    try {
        const url = new URL(raw);
        return ['http:', 'https:'].includes(url.protocol)
            && hosts.has(url.hostname) && !url.port && !url.username && !url.password
            ? url : null;
    } catch { return null; }
}

export function parsePopkonTVChannelInput(value: string): string | null {
    let raw = value.trim();
    if (raw.includes('://')) {
        const url = popkonUrl(raw);
        if (!url || !/^\/live\/view\/?$/.test(url.pathname)) return null;
        const ids = url.searchParams.getAll('castId');
        const partners = url.searchParams.getAll('partnerCode');
        if (ids.length !== 1 || partners.length > 1) return null;
        raw = ids[0] + '@' + (partners.length ? partners[0] : 'P-00001');
    } else if (!raw.includes('@')) raw += '@P-00001';
    const match = raw.match(/^([A-Za-z0-9][A-Za-z0-9_-]{0,99})@(P-[0-9]{5})$/i);
    return match ? match[1].toLowerCase() + '@' + match[2].toUpperCase() : null;
}

export function canonicalPopkonTVVideoUrl(value: string): string | null {
    const url = popkonUrl(value);
    if (!url) return null;
    try {
        const match = decodeURIComponent(url.pathname).match(/^\/(vod|clip)\/([0-9]{1,20})\/?$/);
        if (!match || /^0+$/.test(match[2])) return null;
        return 'https://www.popkontv.com/' + match[1] + '/' + match[2].replace(/^0+/, '');
    } catch { return null; }
}
