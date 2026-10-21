/**
 * 공용 에러 핸들링 유틸리티.
 */
import axios, { AxiosError } from "axios";
import { localizePlatformNames } from './platformNames';
import { getActiveLocale, messageKey, translate } from '../i18n';

export function isAxiosLike(e: unknown): e is AxiosError {
    return axios.isAxiosError(e) || (e instanceof AxiosError) || (typeof e === 'object' && e !== null && ('isAxiosError' in e || 'response' in e));
}

export function isTimeoutError(e: unknown): boolean {
    if (!e || typeof e !== 'object') return false;
    if (isCanceledError(e)) return false;
    const err = e as { code?: string; name?: string; message?: string; response?: unknown };
    if (err.response) return false;
    if (err.code === 'ECONNABORTED' || err.code === 'ETIMEDOUT' || err.code === 'ERR_TIMEOUT') return true;
    if (err.name === 'TimeoutError') return true;
    if (typeof err.message === 'string' && /timeout/i.test(err.message)) return true;
    return false;
}

export function isNetworkError(e: unknown): boolean {
    if (!e || typeof e !== 'object') return false;
    if (isCanceledError(e)) return false;
    const err = e as { code?: string; name?: string; message?: string; response?: unknown; request?: unknown };
    if (err.response) return false;
    if (err.code === 'ERR_NETWORK' || err.code === 'ECONNREFUSED' || err.code === 'ENOTFOUND') return true;
    if (typeof err.message === 'string' && /failed to fetch|network\s*error/i.test(err.message)) return true;
    if (isAxiosLike(e) && Boolean(err.request)) return true;
    return false;
}

export function isCanceledError(e: unknown): boolean {
    if (!e || typeof e !== 'object') return false;
    const err = e as { code?: string; name?: string };
    return axios.isCancel(e) || err.code === 'ERR_CANCELED' || err.name === 'CanceledError' || err.name === 'AbortError';
}

export function isHtml(text: string): boolean {
    return /<!doctype|<html|<head|<body/i.test(text) || /<\/?[a-z][\s\S]*>/i.test(text);
}

export function sanitizeSecrets(text: string): string {
    const mask = getActiveLocale() === 'ko-KR' ? '[비공개]' : '[redacted]';
    let clean = text
        .replace(/<[^>]+>/g, '')
        // Preserve scheme (http:// or https://) on credentials removal
        .replace(/(https?:\/\/)[^\s:@/]+:[^\s:@/]+@/gi, '$1')
        // Mask JSON-serialized headers and sensitive key-values (incl. escaped values)
        .replace(/"((?:access[-_]?|refresh[-_]?)?token|password|passwd|auth[-_]?token|secret|session(?:id)?|api[-_]?key|authorization|cookie|x-csrf-token)"\s*:\s*("(?:\\.|[^"\\])*"|[^\s,}{]+)/gi,
            (match, key) => `"${key}": "${mask}"`)
        // Mask entire HTTP header lines through newline
        .replace(/\b(authorization|cookie|x-csrf-token)\s*:[^\r\n]*/gim, (match, header) => `${header}: ${mask}`)
        // Mask sensitive query parameters in URLs
        .replace(/([?&](?:(?:access[-_]?|refresh[-_]?)?token|auth|password|passwd|secret|api[-_]?key|session(?:id)?|sig|signature)=)[^&\s]+/gi, `$1${mask}`)
        // Mask plain token/access_token/refresh_token/password assignments
        .replace(/\b((?:access[-_]?|refresh[-_]?)?token|password|passwd|auth[-_]?token|secret|session(?:id)?|api[-_]?key)\s*[:=]\s*([^\s,;&}]+)/gi, `$1=${mask}`);

    if (clean.length > 500) {
        clean = clean.slice(0, 497) + '...';
    }
    return clean;
}

export function isStandardStatusText(text: string): boolean {
    return /^(?:(?:50[0-4]|40[0-4]|408|409|422|429)\s+)?(?:bad gateway|service unavailable|gateway time-?out|internal server error|unauthorized|forbidden|not found|conflict|too many requests|unprocessable entity|bad request)$/i.test(text.trim());
}

export function extractDetail(data: unknown): string | undefined {
    if (!data) return undefined;

    if (typeof data === 'string') {
        const trimmed = data.trim();
        if (!trimmed || isHtml(trimmed) || isStandardStatusText(trimmed)) return undefined;
        return trimmed;
    }

    if (typeof data !== 'object') return undefined;

    const obj = data as Record<string, unknown>;

    // 1. Structured FastAPI validation error list
    if (Array.isArray(obj.detail)) {
        const messages: string[] = [];
        for (const item of obj.detail) {
            if (typeof item === 'string') {
                const s = item.trim();
                if (s && !isHtml(s) && !isStandardStatusText(s) && !messages.includes(s)) messages.push(s);
            } else if (item && typeof item === 'object') {
                const err = item as Record<string, unknown>;
                const rawMsg = typeof err.msg === 'string' ? err.msg.trim()
                    : typeof err.message === 'string' ? err.message.trim()
                    : '';
                if (!rawMsg || isHtml(rawMsg) || isStandardStatusText(rawMsg)) continue;
                const loc = Array.isArray(err.loc)
                    ? err.loc.filter(x => x !== 'body' && x !== 'query' && x !== 'path' && x !== 'header').join('.')
                    : typeof err.loc === 'string' ? err.loc.trim() : '';
                const translated = messageKey(rawMsg) ? translate(rawMsg) : rawMsg;
                const entry = loc ? `${loc}: ${translated}` : translated;
                if (!messages.includes(entry)) messages.push(entry);
            }
        }
        if (messages.length > 0) return messages.join(', ');
    }

    // 2. String detail
    if (typeof obj.detail === 'string') {
        const trimmed = obj.detail.trim();
        if (trimmed && !isHtml(trimmed) && !isStandardStatusText(trimmed)) return trimmed;
        return undefined;
    }

    // 3. Object detail with msg / message / error
    if (obj.detail && typeof obj.detail === 'object') {
        const d = obj.detail as Record<string, unknown>;
        const msg = typeof d.msg === 'string' ? d.msg.trim()
            : typeof d.message === 'string' ? d.message.trim()
            : typeof d.error === 'string' ? d.error.trim()
            : '';
        if (msg && !isHtml(msg) && !isStandardStatusText(msg)) return msg;
    }

    // 4. Top-level message or error
    if (typeof obj.message === 'string') {
        const trimmed = obj.message.trim();
        if (trimmed && !isHtml(trimmed) && !isStandardStatusText(trimmed)) return trimmed;
    }
    if (typeof obj.error === 'string') {
        const trimmed = obj.error.trim();
        if (trimmed && !isHtml(trimmed) && !isStandardStatusText(trimmed)) return trimmed;
    }

    return undefined;
}

/**
 * catch 블록에서 사용자에게 보여줄 에러 메시지를 추출한다.
 */
export function getErrorMessage(e: unknown, fallback: string): string {
    // 1. Cancellation checked first
    if (isCanceledError(e)) {
        return translate(fallback);
    }

    // 2. HTTP response from server (uses server response/detail rather than transport timeout)
    if (isAxiosLike(e) && e.response) {
        const response = e.response;
        const status = response.status;
        const data = response.data;

        const rawDetail = extractDetail(data);
        const detail = rawDetail ? sanitizeSecrets(rawDetail) : undefined;

        if (detail) {
            const known = messageKey(detail);
            if (known) return translate(known);
            if (getActiveLocale() === 'ko-KR') return localizePlatformNames(detail);
            // Non-Korean: display if it does not contain untranslated Korean text
            if (!/[\uac00-\ud7a3]/.test(detail)) return localizePlatformNames(detail);
        }

        if (data && typeof data === 'object') {
            const key = (data as Record<string, unknown>).message_key;
            if (typeof key === 'string' && messageKey(key)) return translate(key);
        }

        // Status code mapping for non-JSON/HTML responses or status-specific errors
        if (status) {
            if (status === 504 || status === 408) return translate('errors.timeout');
            if (status === 401 || status === 403) return translate('errors.authentication');
            if (status === 429) return translate('errors.rateLimited');
            if (status === 422 && (!fallback || fallback === 'errors.request')) return translate('errors.invalidInput');
            if (status >= 500 && (typeof data === 'string' && isHtml(data) || !fallback || fallback === 'errors.request')) {
                return translate('errors.server');
            }
        }

        return translate(fallback);
    }

    // 3. Transport failures (no server response)
    if (isTimeoutError(e)) {
        return translate('errors.timeout');
    }
    if (isNetworkError(e)) {
        return translate('errors.network');
    }

    // 4. Standard JS Error
    if (e instanceof Error) {
        if (messageKey(e.message)) return translate(e.message);
        if (/failed to fetch|network\s*error/i.test(e.message)) return translate('errors.network');
    }

    return translate(fallback);
}

export function localizedStatus(message: string | null | undefined, key: string): string {
    if (!message) return translate(key);
    const sanitized = sanitizeSecrets(message);
    const known = messageKey(sanitized);
    if (known) return translate(known);
    if (getActiveLocale() === 'ko-KR') return localizePlatformNames(sanitized);
    if (!/[\uac00-\ud7a3]/.test(sanitized)) return localizePlatformNames(sanitized);
    return translate(key);
}
