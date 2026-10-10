const CHANNEL_ID = /^[0-9a-f]{32}$/i;

/** Accept only 치지직 channel pages; VOD/clip and unrelated URLs are not channels. */
export function parseChzzkChannelInput(input: string): string | null {
    const value = input.trim();
    if (CHANNEL_ID.test(value)) return value.toLowerCase();
    try {
        const url = new URL(value);
        if (!['https:', 'http:'].includes(url.protocol) || url.hostname !== 'chzzk.naver.com'
            || url.username || url.password || url.port) return null;
        const match = /^\/(?:live\/)?([0-9a-f]{32})\/?$/i.exec(url.pathname);
        return match ? match[1].toLowerCase() : null;
    } catch {
        return null;
    }
}

export const CHZZK_CHANNEL_INPUT_ERROR = '올바른 치지직 채널 ID 또는 채널 링크를 입력하세요.';
