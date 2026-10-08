import { AlertTriangle, ChevronRight, Users, Video } from "lucide-react";
import { clsx } from "clsx";
import { getChannelKey } from "../../utils/channel";
import { formatBytes, formatDuration } from "../../utils/format";
import { TagManager } from "../ui/TagManager";
import { Card } from "../ui/primitives";
import { ChannelRecordingControls, ChannelError, PlatformBadge, type ChannelItemProps, useDesktopChannelLayout, useRecordingDuration } from "./ChannelCard";
import { ChannelActions } from "./ChannelActions";
import { LivePreview } from "./LivePreview";
import { DownloadHoldStatus } from "./DownloadHoldStatus";
import { useLanguage } from "../../contexts/LanguageContext";

export function ChannelRow(props: ChannelItemProps) {
    const { channel, globalTags, onAddTag, onRemoveTag, onCreateTag,
        isDragging, isDropTarget,
        isSelected, onSelect } = props;
    const { t } = useLanguage();
    const displayName = channel.channel_name || channel.channel_id;
    const duration = useRecordingDuration(channel);
    const recording = channel.recording?.is_recording === true;
    const desktop = useDesktopChannelLayout();
    const Summary = desktop ? "div" : "button";
    return <Card padded={false} className={clsx("channel-row-card channel-list-row overflow-hidden", isSelected && "is-selected", isDragging && "opacity-45", isDropTarget && "ring-2 ring-[var(--primary)]")} data-channel-key={getChannelKey(channel)}>
        <div className="channel-list-header">
            <Summary type={desktop ? undefined : "button"} onClick={desktop ? undefined : onSelect} className="channel-summary flex-1" aria-expanded={desktop ? undefined : isSelected} title={desktop ? undefined : t("채널 상세 보기")}>
                {channel.profile_image_url ? <img src={channel.profile_image_url} alt="" className="size-8 shrink-0 rounded-full object-cover" /> : <span className="grid size-8 shrink-0 place-items-center rounded-full bg-surface-3 text-ink-faint"><Users className="size-4" /></span>}
                <div className="channel-info min-w-0 flex-1">
                    <div className="channel-list-name flex min-w-0 items-center gap-2"><h3 className="min-w-0 truncate text-[13px] font-semibold text-ink" title={displayName}>{displayName}</h3><PlatformBadge platform={channel.platform || "chzzk"} />{channel.last_error && <AlertTriangle className="size-3.5 text-danger" />}</div>
                    {channel.is_live && channel.title && <p className="mt-0.5 truncate text-xs text-ink-faint" title={channel.title}>{channel.title}</p>}
                    {!desktop && isSelected && channel.category && <p className="mt-0.5 truncate text-xs text-ink-faint" title={channel.category}>{channel.category}</p>}
                    {desktop && <div className="channel-list-tags">{isSelected && channel.category && <span className="max-w-[150px] truncate text-xs text-ink-faint">{channel.category}</span>}<TagManager availableTags={globalTags} selectedTags={channel.tags || []} onAddTag={(tag) => onAddTag(channel, tag)} onRemoveTag={(tag) => onRemoveTag(channel, tag)} onCreateTag={onCreateTag} triggerLabel="태그 관리" /></div>}
                </div>
                <ChevronRight className={clsx("lg:hidden size-4 shrink-0 text-ink-faint transition-transform", isSelected && "rotate-90")} />
            </Summary>
            <ChannelActions {...props} showDetails={desktop} compactMenu onManageTags={() => { if (!isSelected) onSelect?.(); }} />
        </div>
        <div className="space-y-2 px-3 pb-3">
            <ChannelRecordingControls {...props} />
            {!desktop && isSelected && <TagManager availableTags={globalTags} selectedTags={channel.tags || []} onAddTag={(tag) => onAddTag(channel, tag)} onRemoveTag={(tag) => onRemoveTag(channel, tag)} onCreateTag={onCreateTag} />}
            <DownloadHoldStatus channel={channel} />
            {recording && <div className="channel-recording-metrics" aria-label={t("녹화 정보")}>
                <span className="inline-flex items-center gap-1.5 font-medium text-ok"><Video className="size-3.5" />{formatDuration(duration)}</span>
                <span title={t("용량")}>{formatBytes(channel.recording?.file_size_bytes || 0)}</span>
                <span title={t("속도")}>{(channel.recording?.download_speed || 0).toFixed(2)} MB/s</span>
                <span title={t("비트레이트")}>{((channel.recording?.bitrate || 0) / 1000).toFixed(2)} Mbps</span>
                {channel.chat_archiving?.is_running && <span>{t("채팅 저장 중")} · {channel.chat_archiving.message_count.toLocaleString()}{t("개")}</span>}
            </div>}
            {isSelected && channel.last_error && <ChannelError message={channel.last_error} />}
        </div>
        {isSelected && <LivePreview channelKey={getChannelKey(channel)} isLive={channel.is_live} name={displayName} />}
    </Card>;
}
