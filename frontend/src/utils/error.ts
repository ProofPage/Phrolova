/**
 * 공용 에러 핸들링 유틸리티.
 */
import { AxiosError } from "axios";
import { localizePlatformNames } from './platformNames';
import { getActiveLocale, messageKey, translate } from '../i18n';

/**
 * catch 블록에서 사용자에게 보여줄 에러 메시지를 추출한다.
 */
export function getErrorMessage(e: unknown, fallback: string): string {
    if (e instanceof AxiosError) {
        const data = e.response?.data;
        const detail = typeof data?.detail === 'string' ? data.detail : data?.detail?.message;
        const known = detail && messageKey(detail);
        if (known) return translate(known);
        if (getActiveLocale() === 'ko-KR' && detail) return localizePlatformNames(detail);
        if (data?.message_key && messageKey(data.message_key)) return translate(data.message_key);
        return translate(e.response ? fallback : 'errors.network');
    }
    if (e instanceof Error && messageKey(e.message)) return translate(e.message);
    return translate(fallback);
}

export function localizedStatus(message: string | null | undefined, key: string): string {
    if (message && messageKey(message)) return translate(message);
    return getActiveLocale() === 'ko-KR' && message ? message : translate(key);
}
