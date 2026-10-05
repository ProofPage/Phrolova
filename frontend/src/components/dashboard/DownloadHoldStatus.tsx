import { PauseCircle } from "lucide-react";
import type { Channel } from "../../api/client";

export function DownloadHoldStatus({ channel }: { channel: Channel }) {
    if (!channel.is_live || !channel.auto_record || channel.recording?.is_recording || channel.auto_record_eligible !== false) return null;
    const reason = channel.download_hold_reason || (channel.broadcast_tags == null && channel.is_watchalong == null
        ? "같이보기 정보 확인 대기" : "다운로드 조건과 일치하지 않는 방송");
    return (
        <div role="status" className="rounded-[var(--radius-control)] border border-warn/25 bg-warn/10 p-2.5 text-xs">
            <p className="flex items-center gap-1.5 font-medium text-warn"><PauseCircle className="w-3.5 h-3.5 shrink-0" />다운로드 보류</p>
            <p className="mt-1 text-ink-muted leading-relaxed">{reason}</p>
        </div>
    );
}
