import { AlertTriangle, ChevronDown, ChevronRight, GripVertical, Play, Square, Trash2, Users, Video } from "lucide-react";
import { clsx } from "clsx";
import { getChannelKey } from "../../utils/channel";
import { formatBytes, formatDuration } from "../../utils/format";
import { TagManager } from "../ui/TagManager";
import { Badge, Button, Card, Switch } from "../ui/primitives";
import { ChannelDesktopControls, PlatformBadge, type ChannelItemProps, useDesktopChannelLayout, useRecordingDuration } from "./ChannelCard";
import { LivePreview } from "./LivePreview";
import { DownloadHoldStatus } from "./DownloadHoldStatus";
import { useLanguage } from "../../contexts/LanguageContext";

export function ChannelRow(props: ChannelItemProps) {
    const { channel, onStartRecord, onStopRecord, onRemove, onToggleAutoRecord, isActionLoading, globalTags, onAddTag, onRemoveTag, onCreateTag,
        onReorderPointerDown, onReorderPointerMove, onReorderPointerUp, onReorderMouseMove, onReorderMouseUp, onReorderKeyDown, isDragging, isDropTarget,
        isSelected, onSelect } = props;
    const { t } = useLanguage();
    const displayName = channel.channel_name || channel.channel_id;
    const duration = useRecordingDuration(channel);
    const recording = channel.recording?.is_recording === true;
    const desktop = useDesktopChannelLayout();
    const Summary = desktop ? "div" : "button";
    return <Card padded={false} className={clsx("channel-row-card channel-list-row overflow-hidden", isSelected && "is-selected", isDragging && "opacity-45", isDropTarget && "ring-2 ring-[var(--primary)]")} data-channel-key={getChannelKey(channel)}>
        <div className="channel-list-header flex min-w-0 items-start gap-1 pr-2">
            <Summary type={desktop ? undefined : "button"} onClick={desktop ? undefined : onSelect} className="channel-summary flex-1" aria-expanded={desktop ? undefined : isSelected} title={desktop ? undefined : t("채널 상세 보기")}>
                {channel.profile_image_url ? <img src={channel.profile_image_url} alt="" className="size-8 shrink-0 rounded-full object-cover" /> : <span className="grid size-8 shrink-0 place-items-center rounded-full bg-surface-3 text-ink-faint"><Users className="size-4" /></span>}
                <div className="channel-info min-w-0 flex-1">
                    <div className="channel-list-name flex flex-wrap items-center gap-x-2 gap-y-1"><h3 className={clsx("min-w-0 max-w-full text-[13px] font-semibold text-ink", isSelected ? "line-clamp-2 break-words" : "truncate")}>{displayName}</h3><PlatformBadge platform={channel.platform || "chzzk"} />{channel.last_error && <AlertTriangle className="size-3.5 text-danger" />}</div>
                    <p className="mt-0.5 line-clamp-2 break-words text-xs text-ink-faint" title={channel.title || channel.channel_id}>{channel.is_live && channel.title ? channel.title : channel.channel_id}</p>
                    {!desktop && isSelected && channel.category && <p className="mt-0.5 text-xs text-ink-faint">{channel.category}</p>}
                    {desktop && <div className="channel-list-tags">{isSelected && channel.category && <span className="max-w-[150px] truncate text-xs text-ink-faint">{channel.category}</span>}<TagManager availableTags={globalTags} selectedTags={channel.tags || []} onAddTag={(tag) => onAddTag(channel, tag)} onRemoveTag={(tag) => onRemoveTag(channel, tag)} onCreateTag={onCreateTag} triggerLabel="태그 관리" /></div>}
                </div>
                <ChevronRight className={clsx("lg:hidden size-4 shrink-0 text-ink-faint transition-transform", isSelected && "rotate-90")} />
            </Summary>
            <div className="channel-header-actions flex shrink-0 items-center gap-1 pt-2">
                {desktop && <Button variant="ghost" onClick={onSelect} aria-expanded={isSelected} className="channel-list-details">{t(isSelected ? "상세 접기" : "상세 보기")}<ChevronDown className={clsx("size-4", isSelected && "rotate-180")} /></Button>}
                <div role="button" tabIndex={0} onPointerDown={onReorderPointerDown} onPointerMove={onReorderPointerMove} onPointerUp={onReorderPointerUp} onPointerCancel={onReorderPointerUp} onLostPointerCapture={onReorderPointerUp} onMouseMove={onReorderMouseMove} onMouseUp={onReorderMouseUp} onKeyDown={onReorderKeyDown} className="icon-button cursor-grab touch-none select-none active:cursor-grabbing" title={t("드래그하거나 방향키를 눌러 채널 순서 변경")} aria-label={`${displayName} ${t("채널 순서 변경")}`} aria-keyshortcuts="ArrowLeft ArrowRight ArrowUp ArrowDown"><GripVertical className="size-4 pointer-events-none" /></div>
                <button type="button" onClick={() => onRemove(channel)} className="icon-button hover:text-danger" title={t("채널 제거")} aria-label={`${t("채널 제거")}: ${displayName}`}><Trash2 className="size-4" /></button>
            </div>
        </div>
        <div className="space-y-2 px-3 pb-3">
            {desktop ? <ChannelDesktopControls {...props} /> : <div className="channel-list-controls flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
                <Badge tone={channel.is_live ? "danger" : "neutral"}>{t(channel.is_live ? "라이브" : "오프라인")}</Badge>
                {recording && <Badge tone="ok">{t("녹화 중")}</Badge>}
                <label className="channel-desktop-auto flex items-center gap-2 text-xs text-ink-faint">{t("자동 녹화")}<Switch checked={channel.auto_record} onChange={() => onToggleAutoRecord(channel)} label={`${displayName} ${t("자동 녹화")}`} /></label>
                <Button variant="ghost" onClick={() => props.onEditDownloadSettings(channel)}>{t("녹화 설정")}</Button>
                {isSelected && <TagManager availableTags={globalTags} selectedTags={channel.tags || []} onAddTag={(tag) => onAddTag(channel, tag)} onRemoveTag={(tag) => onRemoveTag(channel, tag)} onCreateTag={onCreateTag} />}
                <div className="channel-record-action ml-auto">{recording ? <Button variant="danger" icon={Square} loading={isActionLoading} onClick={() => onStopRecord(channel)}>{t("녹화 중지")}</Button> : channel.is_live ? <Button variant="primary" icon={Play} loading={isActionLoading} onClick={() => onStartRecord(channel)}>{t("녹화 시작")}</Button> : null}</div>
            </div>}
            <DownloadHoldStatus channel={channel} />
            {recording && <div className="channel-recording-metrics" aria-label={t("녹화 정보")}>
                <span className="inline-flex items-center gap-1.5 font-medium text-ok"><Video className="size-3.5" />{formatDuration(duration)}</span>
                <span title={t("용량")}>{formatBytes(channel.recording?.file_size_bytes || 0)}</span>
                <span title={t("속도")}>{(channel.recording?.download_speed || 0).toFixed(2)} MB/s</span>
                <span title={t("비트레이트")}>{((channel.recording?.bitrate || 0) / 1000).toFixed(2)} Mbps</span>
                {channel.chat_archiving?.is_running && <span>{t("채팅 저장 중")} · {channel.chat_archiving.message_count.toLocaleString()}{t("개")}</span>}
            </div>}
            {isSelected && channel.last_error && <p role="status" className="break-words text-xs text-danger">{channel.last_error}</p>}
        </div>
        {isSelected && <LivePreview channelKey={getChannelKey(channel)} isLive={channel.is_live} name={displayName} />}
    </Card>;
}
