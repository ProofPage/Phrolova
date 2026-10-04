/**
 * 공용 포맷 유틸리티.
 * Dashboard, VodDownload, Stats, ChatLogs 등에서 공통으로 사용하는 포맷 함수.
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
        if (style === "eta") return "계산 중...";
        if (style === "korean") return "0분";
        return "00:00:00";
    }

    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);

    switch (style) {
        case "clock":
            return `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
        case "korean":
            if (h > 0) return `${h}시간 ${m}분`;
            return `${m}분`;
        case "eta":
            if (h > 0) return `${h}시간 ${m}분`;
            if (m > 0) return `${m}분 ${s}초`;
            return `${s}초`;
    }
}

/**
 * 바이트를 사람이 읽기 쉬운 단위로 변환한다.
 */
export function formatBytes(bytes: number): string {
    if (bytes <= 0) return "0 B";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

/**
 * ISO 날짜 문자열을 한국어 형식으로 변환한다.
 * - includeYear: true이면 YYYY. MM. DD. HH:MM, false이면 MM. DD. HH:MM
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
    return new Date(iso).toLocaleString("ko-KR", opts);
}

/**
 * ISO 날짜 문자열에서 시:분:초만 추출한다.
 */
export function formatTime(iso: string): string {
    return new Date(iso).toLocaleTimeString("ko-KR", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
    });
}
