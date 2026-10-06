import { Info, PauseCircle } from "lucide-react";
import type { Channel } from "../../api/client";
import { useLanguage } from "../../contexts/LanguageContext";

export function DownloadHoldStatus({ channel }: { channel: Channel }) {
    const { t } = useLanguage();
    if (!channel.is_live || channel.recording?.is_recording) return null;
    if (!channel.download_hold_reason && (!channel.auto_record || channel.auto_record_eligible !== false)) return null;
    const rawReason = channel.download_hold_reason;
    const reason = !rawReason || rawReason === "같이보기 정보 확인 대기"
        ? t("같이보기 정보를 확인하고 있습니다.")
        : rawReason === "같이보기 방송을 제외하도록 설정되어 있습니다."
            ? t("같이보기 방송은 자동 녹화하지 않도록 설정되어 있습니다.")
            : rawReason === "일반 라이브 방송입니다. 같이보기 방송만 다운로드하도록 설정되어 있습니다."
                ? t("같이보기 방송만 녹화하도록 설정되어 있어 이 방송은 저장하지 않습니다.")
                : rawReason === "방송의 같이보기 태그가 지정한 태그와 일치하지 않습니다."
                    ? t("방송의 같이보기 태그가 설정한 태그와 일치하지 않습니다.")
                    : rawReason === "같이보기 태그 조건과 일치하지 않는 방송입니다."
                        ? t("방송 태그가 설정한 녹화 조건과 일치하지 않습니다.")
                        : t(rawReason);
    return (
        <div role="status" className={`rounded-[var(--radius-control)] border p-2.5 text-xs ${channel.auto_record ? "border-warn/25 bg-warn/10" : "border-line bg-surface-3"}`}>
            <p className={`flex items-center gap-1.5 font-medium ${channel.auto_record ? "text-warn" : "text-ink-muted"}`}>
                {channel.auto_record ? <PauseCircle className="w-3.5 h-3.5 shrink-0" /> : <Info className="w-3.5 h-3.5 shrink-0" />}
                {channel.auto_record ? t("자동 녹화 보류") : t("자동 녹화 꺼짐")}
            </p>
            <p className="mt-1 text-ink-muted leading-relaxed">{reason}</p>
        </div>
    );
}
