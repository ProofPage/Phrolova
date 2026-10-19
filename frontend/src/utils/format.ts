import { getActiveLocale, formatNumber, formatDateTime, translate } from '../i18n';
/**
 * 공용 포맷 유틸리티.
 * Dashboard, VodDownload, Stats 등에서 공통으로 사용하는 포맷 함수.
 */

/**
 * 초를 시간 형식으로 변환한다.
 * - "clock" : HH:MM:SS (대시보드 녹화 경과시간)
 * - "korean": X시간 X분 (통계 표시)
 * - "eta"   : X시간 X분 X초 / X분 X초 / X초 (남은 시간)
 */
export function formatDuration(
    seconds: number,
    style: "clock" | "korean" | "eta" = "clock",
): string {
    if (seconds <= 0) {
        if (style === "eta") return translate("common.calculating");
        if (style === "korean") return new Intl.NumberFormat(getActiveLocale(), {style:"unit", unit:"minute", unitDisplay:"short"}).format(0);
        return "00:00:00";
    }

    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);

    if (style === "clock") return `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
    const unit = (value: number, name: string) => new Intl.NumberFormat(getActiveLocale(), { style: 'unit', unit: name, unitDisplay: 'short' }).format(value);
    if (h > 0) return `${unit(h, 'hour')} ${unit(m, 'minute')}`;
    if (style === 'eta' && m > 0) return `${unit(m, 'minute')} ${unit(s, 'second')}`;
    return style === 'eta' ? unit(s, 'second') : unit(m, 'minute');
}

/**
 * 바이트를 사람이 읽기 쉬운 단위로 변환한다.
 */
export function formatBytes(bytes: number): string {
    if (bytes <= 0) return "0 B";
    if (bytes < 1024) return `${formatNumber(bytes)} B`;
    if (bytes < 1024 * 1024) return `${formatNumber(bytes / 1024, {minimumFractionDigits:1, maximumFractionDigits:1})} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${formatNumber(bytes / (1024 * 1024), {minimumFractionDigits:1, maximumFractionDigits:1})} MB`;
    return `${formatNumber(bytes / (1024 * 1024 * 1024), {minimumFractionDigits:2, maximumFractionDigits:2})} GB`;
}

/**
 * 날짜 표시를 선택 언어에 맞추되 API의 ISO 문자열은 그대로 둔다.
 */
export function formatDate(iso: string | null, includeYear = false): string {
    if (!iso) return "-";
    const opts: Intl.DateTimeFormatOptions = {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
    };
    if (includeYear) opts.year = "numeric";
    return formatDateTime(iso, opts);
}

/**
 * ISO 날짜 문자열에서 시:분(:초)만 추출한다.
 */
export function formatTime(iso: string | null, includeSeconds = false): string {
    if (!iso) return "-";
    const opts: Intl.DateTimeFormatOptions = {
        hour: "2-digit",
        minute: "2-digit",
    };
    if (includeSeconds) opts.second = "2-digit";
    return formatDateTime(iso, opts);
}
