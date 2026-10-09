/** Browser drops are data, never markup to render or execute. */
export function canonicalVodUrl(value: string): string | null {
    try {
        const url = new URL(value.trim());
        if (!['https:', 'http:'].includes(url.protocol) || url.hostname !== 'chzzk.naver.com'
            || url.username || url.password || (url.port && url.port !== '80' && url.port !== '443')) return null;
        const match = url.pathname.match(/^\/video\/(\d+)\/?$/);
        return match ? `https://chzzk.naver.com/video/${match[1]}` : null;
    } catch { return null; }
}

export function parseVodUrls(text: string): { urls: string[]; invalid: string[] } {
    const entries = text.split(/\s+/).filter(value => value && !value.startsWith('#'));
    const urls = new Set<string>(); const invalid: string[] = [];
    for (const entry of entries) {
        const url = canonicalVodUrl(entry);
        if (url) urls.add(url); else invalid.push(entry);
    }
    return { urls: [...urls], invalid };
}

export function droppedVodText(data: Pick<DataTransfer, 'getData'>): string {
    const uri = data.getData('text/uri-list');
    if (uri) return uri.split(/\r?\n/).filter(line => !line.startsWith('#')).join('\n');
    const plain = data.getData('text/plain');
    if (plain) return plain;
    const html = data.getData('text/html');
    if (!html) return '';
    // DOMParser's inert document is never inserted into the live DOM.
    return [...new DOMParser().parseFromString(html, 'text/html').querySelectorAll('a[href]')]
        .map(link => link.getAttribute('href') ?? '').join('\n');
}
