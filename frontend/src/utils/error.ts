/**
 * 공용 에러 핸들링 유틸리티.
 */
import { AxiosError } from "axios";

/**
 * catch 블록에서 사용자에게 보여줄 에러 메시지를 추출한다.
 */
export function getErrorMessage(e: unknown, fallback: string): string {
    if (e instanceof AxiosError) {
        return e.response?.data?.detail || fallback;
    }
    if (e instanceof Error) return e.message;
    return fallback;
}
