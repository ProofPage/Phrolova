import { AlertCircle, AlertTriangle, GripVertical, Play, Square, Trash2, Users, Video } from "lucide-react";
import { clsx } from "clsx";
import { getChannelKey } from "../../utils/channel";
import { formatBytes, formatDuration } from "../../utils/format";
import { TagManager } from "../ui/TagManager";
import { Button, Card, Switch } from "../ui/primitives";
import { ChannelThumbnail, PlatformBadge, type ChannelItemProps, useRecordingDuration } from "./ChannelCard";
import { DownloadHoldStatus } from "./DownloadHoldStatus";
import { useLanguage } from "../../contexts/LanguageContext";

export function ChannelRow(props: ChannelItemProps) {
    const {
        channel, onStartRecord, onStopRecord, onRemove, onToggleAutoRecord,
        isActionLoading, globalTags, onAddTag, onRemoveTag, onCreateTag,
        onReorderPointerDown, onReorderPointerMove, onReorderPointerUp,
        onReorderMouseMove, onReorderMouseUp, onReorderKeyDown,
        isDragging, isDropTarget,
    } = props;
    const { t } = useLanguage();
    const displayName = channel.channel_name || channel.channel_id;
    const platform = channel.platform || "chzzk";
    const duration = useRecordingDuration(channel);
    const recording = channel.recording?.is_recording === true;

    return (
        <Card
            padded={false}
            className={clsx(
                "channel-row-card group relative flex min-w-0 flex-col overflow-hidden transition-colors",
                isDragging && "opacity-45",
                isDropTarget && "ring-2 ring-[var(--primary)] ring-offset-2 ring-offset-surface-0",
            )}
            data-channel-key={getChannelKey(channel)}
        >
            <div className="min-w-0 space-y-4 p-4 sm:p-5">
                <div className="flex min-w-0 flex-wrap items-start justify-between gap-x-4 gap-y-3">
                    <div className="flex min-w-0 flex-1 items-start gap-3">
                        {channel.profile_image_url ? (
                            <img src={channel.profile_image_url} alt="" className="size-11 shrink-0 rounded-full border border-line-strong object-cover" />
                        ) : (
                            <span className="grid size-11 shrink-0 place-items-center rounded-full border border-line-strong bg-surface-3 text-ink-faint"><Users className="size-4" /></span>
                        )}
                        <div className="min-w-0 flex-1">
                            <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                                <h3 className="max-w-full truncate text-sm font-semibold text-ink" title={displayName}>{displayName}</h3>
                                {platform !== "chzzk" && <PlatformBadge platform={platform} />}
                                {channel.last_error && <span className="shrink-0" title={channel.last_error} aria-label={t("녹화 오류")}><AlertTriangle className="size-4 text-danger" /></span>}
                            </div>
                            {channel.title && channel.is_live
                                ? <p className="mt-1 line-clamp-2 break-words text-[13px] leading-5 text-ink-muted" title={channel.title}>{channel.title}</p>
                                : <p className="mt-1 break-all font-mono text-[11px] text-ink-faint" title={channel.channel_id}>{channel.channel_id}</p>}
                            {channel.category && channel.is_live && <p className="mt-1 break-words text-[11px] text-ink-faint" title={channel.category}>{channel.category}</p>}
                        </div>
                    </div>

                    <div className="flex shrink-0 flex-wrap items-center gap-2">
                        <span className={clsx("inline-flex min-h-8 items-center gap-1.5 rounded-full border px-2.5 text-[11px] font-medium", channel.is_live ? "border-live/20 bg-live/8 text-live" : "border-line bg-surface-3 text-ink-faint")}>
                            <span className={clsx("size-1.5 rounded-full", channel.is_live ? "bg-live" : "bg-line-strong")} />{channel.is_live ? t("라이브") : t("오프라인")}
                        </span>
                        {recording && <span className="inline-flex min-h-8 items-center gap-1.5 rounded-full border border-ok/20 bg-ok/8 px-2.5 text-[11px] font-medium text-ok"><span className="size-1.5 rounded-full bg-ok" />{t("녹화 중")}</span>}
                    </div>
                </div>

                <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
                    <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-5 gap-y-2">
                        <div className="flex items-center gap-2 text-xs text-ink-muted"><span>{t("자동 녹화")}</span><Switch checked={channel.auto_record} onChange={() => onToggleAutoRecord(channel)} label={`${displayName} ${t("자동 녹화")}`} /></div>
                        <Button variant="secondary" onClick={() => props.onEditDownloadSettings(channel)} className="min-h-10 text-xs">{t("녹화 설정")}</Button>
                        <TagManager availableTags={globalTags} selectedTags={channel.tags || []} onAddTag={(tag) => onAddTag(channel, tag)} onRemoveTag={(tag) => onRemoveTag(channel, tag)} onCreateTag={onCreateTag} />
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                        <div
                            role="button"
                            tabIndex={0}
                            onPointerDown={onReorderPointerDown}
                            onPointerMove={onReorderPointerMove}
                            onPointerUp={onReorderPointerUp}
                            onPointerCancel={onReorderPointerUp}
                            onLostPointerCapture={onReorderPointerUp}
                            onMouseMove={onReorderMouseMove}
                            onMouseUp={onReorderMouseUp}
                            onKeyDown={onReorderKeyDown}
                            className="grid size-10 place-items-center rounded-[var(--radius-control)] border border-line bg-surface-2 text-ink-faint transition-colors hover:bg-surface-3 hover:text-ink cursor-grab active:cursor-grabbing touch-none select-none"
                            title={t("드래그하거나 방향키를 눌러 채널 순서 변경")}
                            aria-label={`${displayName} ${t("채널 순서 변경")}`}
                            aria-keyshortcuts="ArrowLeft ArrowRight ArrowUp ArrowDown"
                        ><GripVertical className="size-4 pointer-events-none" /></div>
                        <button type="button" onClick={() => onRemove(channel)} className="grid size-10 place-items-center rounded-[var(--radius-control)] border border-line bg-surface-2 text-ink-faint transition-colors hover:border-danger/40 hover:bg-danger/10 hover:text-danger" title={t("채널 제거")} aria-label={`${t("채널 제거")}: ${displayName}`}><Trash2 className="size-4" /></button>
                    </div>
                </div>

                <DownloadHoldStatus channel={channel} />

                {recording ? (
                    <div className="space-y-3 border-t border-line/80 pt-3">
                        <div className="grid min-w-0 grid-cols-2 gap-3 sm:grid-cols-4">
                            <div className="min-w-0"><p className="text-[10px] text-ink-faint">{t("녹화 시간")}</p><p className="mt-1 inline-flex items-center gap-1.5 whitespace-nowrap font-mono text-xs font-semibold tabular-nums text-ok"><Video className="size-3.5" />{formatDuration(duration)}</p></div>
                            <div className="min-w-0"><p className="text-[10px] text-ink-faint">{t("용량")}</p><p className="mt-1 whitespace-nowrap font-mono text-xs font-medium tabular-nums text-ink">{formatBytes(channel.recording?.file_size_bytes || 0)}</p></div>
                            <div className="min-w-0"><p className="text-[10px] text-ink-faint">{t("속도")}</p><p className="mt-1 whitespace-nowrap font-mono text-xs font-medium tabular-nums text-ink">{(channel.recording?.download_speed || 0).toFixed(2)} MB/s</p></div>
                            <div className="min-w-0"><p className="text-[10px] text-ink-faint">{t("비트레이트")}</p><p className="mt-1 whitespace-nowrap font-mono text-xs font-medium tabular-nums text-ink">{((channel.recording?.bitrate || 0) / 1000).toFixed(2)} Mbps</p></div>
                        </div>
                        {channel.chat_archiving?.is_running && <p className="flex items-center gap-1.5 text-[11px] text-info"><span>{t("채팅 저장 중")}</span> · {channel.chat_archiving.message_count.toLocaleString()}{t("개")}</p>}
                        <div className="flex justify-end"><Button variant="danger" icon={Square} loading={isActionLoading} onClick={() => onStopRecord(channel)} className="min-h-10 min-w-36" title={t("녹화 중지")}>{t("녹화 중지")}</Button></div>
                    </div>
                ) : channel.is_live ? (
                    <div className="flex justify-end border-t border-line/80 pt-3"><Button variant="primary" icon={Play} loading={isActionLoading} onClick={() => onStartRecord(channel)} className="min-h-10 min-w-40">{isActionLoading ? t("녹화 시작 중...") : t("수동 녹화 시작")}</Button></div>
                ) : (
                    <div className="flex min-h-10 items-center gap-2 border-t border-line/80 pt-3 text-xs text-ink-faint"><AlertCircle className="size-4 shrink-0" />{t("방송을 기다리고 있습니다.")}</div>
                )}
            </div>

            <ChannelThumbnail channel={channel} className="mx-auto aspect-video w-full max-w-[1200px]" />
        </Card>
    );
}
