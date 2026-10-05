import { Info, PauseCircle } from "lucide-react";
import type { Channel } from "../../api/client";

export function DownloadHoldStatus({ channel }: { channel: Channel }) {
    if (!channel.is_live || channel.recording?.is_recording) return null;
    if (!channel.download_hold_reason && (!channel.auto_record || channel.auto_record_eligible !== false)) return null;
    const reason = channel.download_hold_reason || (channel.broadcast_tags == null && channel.is_watchalong == null
        ? "같이보기 정보 확인 대기" : "다운로드 조건과 일치하지 않는 방송");
    return (
        <div role="status" className={`rounded-[var(--radius-control)] border p-2.5 text-xs ${channel.auto_record ? "border-warn/25 bg-warn/10" : "border-line bg-surface-3"}`}>
            <p className={`flex items-center gap-1.5 font-medium ${channel.auto_record ? "text-warn" : "text-ink-muted"}`}>
                {channel.auto_record ? <PauseCircle className="w-3.5 h-3.5 shrink-0" /> : <Info className="w-3.5 h-3.5 shrink-0" />}
                {channel.auto_record ? "다운로드 보류" : "다운로드 조건 안내"}
            </p>
            <p className="mt-1 text-ink-muted leading-relaxed">{reason}</p>
        </div>
    );
}
