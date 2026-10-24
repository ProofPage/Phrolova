export interface PreviewLevel { width: number; height: number; bitrate?: number }

/** Resolution metadata selects a rendition; the video element verifies decoded pixels. */
export function preferredPreviewLevel(levels: PreviewLevel[]): number {
    const known = levels.map((level, index) => ({ ...level, index })).filter(level => Number.isFinite(level.width) && Number.isFinite(level.height) && level.width > 0 && level.height > 0);
    const fullHd = known.filter(level => level.width === 1920 && level.height === 1080);
    const height1080 = known.filter(level => level.height === 1080);
    const candidates = fullHd.length ? fullHd : height1080.length ? height1080 : known;
    return candidates.sort((a, b) => b.height - a.height || b.width - a.width || (b.bitrate ?? 0) - (a.bitrate ?? 0))[0]?.index ?? -1;
}

function playlistAttributes(line: string): Record<string, string> {
    return Object.fromEntries([...line.slice(line.indexOf(':') + 1).matchAll(/([A-Z0-9-]+)=("[^"]*"|[^,]*)/g)]
        .map(match => [match[1], match[2].replace(/^"|"$/g, '')]));
}

/** Native HLS can receive the chosen variant without changing the resolver contract. */
export async function preferredNativePreviewUrl(url: string, signal: AbortSignal): Promise<string> {
    try {
        const response = await fetch(url, { signal });
        if (!response.ok) return url;
        const lines = (await response.text()).split(/\r?\n/).map(line => line.trim());
        const externalGroups = new Set(lines.filter(line => line.startsWith('#EXT-X-MEDIA:'))
            .map(playlistAttributes).filter(attributes => attributes.URI)
            .map(attributes => `${attributes.TYPE}:${attributes['GROUP-ID']}`));
        const variants: (PreviewLevel & { url: string; attributes: Record<string, string> })[] = [];
        for (let index = 0; index < lines.length; index++) {
            if (!lines[index].startsWith('#EXT-X-STREAM-INF:')) continue;
            const attributes = playlistAttributes(lines[index]);
            const size = attributes.RESOLUTION?.match(/^(\d+)x(\d+)$/);
            let next: string | undefined;
            for (let following = index + 1; following < lines.length; following++) {
                if (lines[following].startsWith('#EXT-X-STREAM-INF:')) break;
                if (lines[following] && !lines[following].startsWith('#')) { next = lines[following]; break; }
            }
            if (!size || !next) continue;
            const variant = new URL(next, response.url || new URL(url, location.href).href);
            if (!['http:', 'https:'].includes(variant.protocol)) continue;
            variants.push({ width: Number(size[1]), height: Number(size[2]), bitrate: Number(attributes.BANDWIDTH) || 0, url: variant.href, attributes });
        }
        const selected = variants[preferredPreviewLevel(variants)];
        // Native video needs the master to discover separate audio/subtitle tracks.
        if (selected && ['AUDIO', 'VIDEO', 'SUBTITLES'].some(type => externalGroups.has(`${type}:${selected.attributes[type]}`))) return url;
        return selected?.url ?? url;
    } catch {
        // A native video may play a cross-origin playlist that disallows fetch.
        return url;
    }
}
