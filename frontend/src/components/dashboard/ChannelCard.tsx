import { DownloadHoldStatus } from "./DownloadHoldStatus";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AlertCircle, AlertTriangle, Eye, GripVertical, Maximize2, MessageSquare, Play, Square, Trash2, Users, Video, X } from "lucide-react";
import { clsx } from "clsx";
import { PLATFORM_LABELS, type Channel, type Platform } from "../../api/client";
import type { ReorderProps } from "../../hooks/useChannelReorder";
import { getChannelKey } from "../../utils/channel";
import { formatBytes, formatDuration } from "../../utils/format";
import { TagManager } from "../ui/TagManager";
import { Button, Card, Switch } from "../ui/primitives";
import { useLanguage } from "../../contexts/LanguageContext";

const PLATFORM_BADGE_STYLES: Record<Platform, string> = {
    chzzk: "bg-chzzk/10 text-chzzk border-chzzk/25",
    twitcasting: "bg-twitcasting/10 text-twitcasting border-twitcasting/25",
    x_spaces: "bg-xspaces/10 text-xspaces border-xspaces/25",
    youtube: "bg-youtube/10 text-youtube border-youtube/25",
};

export interface ChannelItemProps extends ReorderProps {
    channel: Channel;
    isSelected?: boolean;
    onSelect?: () => void;
    onStartRecord: (channel: Channel) => void;
    onStopRecord: (channel: Channel) => void;
    onRemove: (channel: Channel) => void;
    onToggleAutoRecord: (channel: Channel) => void;
    onEditDownloadSettings: (channel: Channel) => void;
    isActionLoading: boolean;
    globalTags: string[];
    onAddTag: (channel: Channel, tag: string) => void;
    onRemoveTag: (channel: Channel, tag: string) => void;
    onCreateTag: (tag: string) => void;
}

export function useRecordingDuration(channel: Channel) {
    const [duration, setDuration] = useState(channel.recording?.duration_seconds ?? 0);

    useEffect(() => {
        const startTime = channel.recording?.start_time;
        if (!channel.recording?.is_recording || !startTime) {
            setDuration(channel.recording?.duration_seconds ?? 0);
            return;
        }
        // SSE 갱신 간격과 무관하게 실제 시작 시각을 기준으로 초 단위를 맞춘다.
        const startMs = new Date(startTime).getTime();
        const tick = () => setDuration(Math.floor((Date.now() - startMs) / 1000));
        tick();
        const timer = setInterval(tick, 1000);
        return () => clearInterval(timer);
    }, [channel.recording?.is_recording, channel.recording?.start_time]);

    return duration;
}

export function PlatformBadge({ platform }: { platform: Platform }) {
    return (
        <span className={`text-[11px] font-medium ${PLATFORM_BADGE_STYLES[platform].split(" ")[1]}`}>
            {PLATFORM_LABELS[platform]}
        </span>
    );
}

export function ChannelThumbnail({ channel, className }: { channel: Channel; className: string }) {
    const { t } = useLanguage();
    const displayName = channel.channel_name || channel.channel_id;
    const [failed, setFailed] = useState(false);
    const [loading, setLoading] = useState(Boolean(channel.thumbnail_url));
    const [expanded, setExpanded] = useState(false);
    const dialogRef = useRef<HTMLDialogElement>(null);
    const imageRef = useRef<HTMLImageElement>(null);
    const src = channel.is_live ? channel.thumbnail_url : null;

    useEffect(() => {
        setFailed(false);
        setLoading(Boolean(src) && !imageRef.current?.complete);
    }, [src]);
    useEffect(() => {
        const dialog = dialogRef.current;
        if (expanded && dialog && !dialog.open) dialog.showModal();
        return () => { if (dialog?.open) dialog.close(); };
    }, [expanded]);

    return (
        <>
        <div className={`channel-thumbnail relative min-w-0 overflow-hidden bg-surface-0 ${className}`}>
            {src && !failed ? (
                <img ref={imageRef} src={src} alt={`${displayName} 방송 미리보기`} onLoad={() => setLoading(false)} onError={() => { setFailed(true); setLoading(false); }} onClick={() => setExpanded(true)} className="size-full object-cover" loading="lazy" />
            ) : (
                <div className="flex size-full flex-col items-center justify-center gap-1.5 bg-surface-1 text-ink-faint">
                    {loading ? <span className="size-6 animate-spin rounded-full border-2 border-line-strong border-t-info" aria-hidden="true" /> : <AlertCircle className="size-7 opacity-50" />}
                    <span className="text-[11px] font-medium">{loading ? t("미리보기를 불러오는 중") : channel.is_live ? t("미리보기를 불러올 수 없습니다.") : t("오프라인")}</span>
                </div>
            )}
            {src && !failed && loading && <div className="pointer-events-none absolute inset-0 grid place-items-center bg-surface-0/45 text-xs text-ink-muted " role="status">{t("미리보기를 불러오는 중")}</div>}
            {channel.is_live && !!channel.viewer_count && (
                <span className="absolute bottom-2 right-2 inline-flex items-center gap-1 rounded-md bg-surface-0/85 px-2 py-1 text-[11px] font-medium text-ink ">
                    <Eye className="size-3" /> {channel.viewer_count.toLocaleString()}
                </span>
            )}
            {src && !failed && <button type="button" onClick={() => setExpanded(true)} className="preview-expand-button absolute right-2 top-2 grid size-10 place-items-center rounded-[var(--radius-control)] border border-white/15 bg-surface-0/75 text-white transition-colors hover:bg-surface-0/95" aria-label={`${displayName} ${t("미리보기 크게 보기")}`} title={t("크게 보기")}><Maximize2 className="size-4" /></button>}
        </div>
        {expanded && src && !failed && createPortal(
            <dialog
                ref={dialogRef}
                aria-label={`${displayName} ${t("방송 미리보기")}`}
                onCancel={(event) => { event.preventDefault(); setExpanded(false); }}
                onClose={() => setExpanded(false)}
                onClick={(event) => { if (event.target === event.currentTarget) setExpanded(false); }}
                className="preview-dialog m-auto w-[min(96vw,1200px)] max-h-[94dvh] overflow-y-auto rounded-[var(--radius-card)] border border-line-strong bg-surface-2 p-0 text-ink shadow-2xl backdrop:bg-surface-0/85 "
            >
                <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3 sm:px-5">
                    <div className="min-w-0"><h2 className="truncate text-sm font-semibold">{displayName} · {t("방송 미리보기")}</h2>{channel.title && <p className="mt-0.5 line-clamp-2 text-xs text-ink-faint">{channel.title}</p>}</div>
                    <button type="button" onClick={() => setExpanded(false)} className="icon-button grid shrink-0" aria-label={t("닫기")}><X className="size-4" /></button>
                </div>
                <div className="aspect-video w-full overflow-hidden bg-black"><img src={src} alt={`${displayName} 방송 미리보기`} className="size-full object-contain" /></div>
            </dialog>,
            document.body,
        )}
        </>
    );
}

export function RecordingStats({ channel }: { channel: Channel }) {
    if (!channel.recording?.is_recording) return null;
    return (
        <div className="grid min-w-0 grid-cols-3 gap-2 text-[10px]" aria-label="녹화 정보">
            <span className="flex min-w-0 flex-col gap-0.5"><span className="text-ink-faint">용량</span><strong className="whitespace-nowrap font-mono font-medium tabular-nums text-ink-muted">{formatBytes(channel.recording.file_size_bytes || 0)}</strong></span>
            <span className="flex min-w-0 flex-col gap-0.5"><span className="text-ink-faint">속도</span><strong className="whitespace-nowrap font-mono font-medium tabular-nums text-ink-muted">{(channel.recording.download_speed || 0).toFixed(2)} MB/s</strong></span>
            <span className="flex min-w-0 flex-col gap-0.5"><span className="text-ink-faint">비트레이트</span><strong className="whitespace-nowrap font-mono font-medium tabular-nums text-ink-muted">{((channel.recording.bitrate || 0) / 1000).toFixed(2)} Mbps</strong></span>
        </div>
    );
}

export function ChannelCard(props: ChannelItemProps) {
    const { channel, onStartRecord, onStopRecord, onRemove, onToggleAutoRecord, isActionLoading, globalTags, onAddTag, onRemoveTag, onCreateTag, onReorderPointerDown, onReorderPointerMove, onReorderPointerUp, onReorderMouseMove, onReorderMouseUp, onReorderKeyDown, isDragging, isDropTarget } = props;
    const { t } = useLanguage();
    const displayName = channel.channel_name || channel.channel_id;
    const platform = channel.platform || "chzzk";
    const duration = useRecordingDuration(channel);

    return (
        <Card
            padded={false}
            className={clsx(
                "channel-row-card overflow-hidden transition-colors group flex flex-col",
                isDragging && "opacity-45",
                props.isSelected && "col-span-full",
                isDropTarget && "ring-2 ring-[var(--primary)] ring-offset-2 ring-offset-surface-0",
            )}
            data-channel-key={getChannelKey(channel)}
        >
            <div className="p-3.5 sm:p-4 flex-1 flex flex-col">
                <div className="flex items-center gap-3 mb-2 min-w-0">
                    {channel.profile_image_url ? (
                        <img src={channel.profile_image_url} alt={displayName} className="w-9 h-9 rounded-full object-cover shrink-0 border-2 border-line-strong" />
                    ) : (
                        <div className="w-9 h-9 rounded-full bg-surface-3 flex items-center justify-center shrink-0 border-2 border-line-strong"><Users className="w-4 h-4 text-ink-faint" /></div>
                    )}
                    <div className="min-w-0 flex-1">
                        <div className="flex min-w-0 items-center gap-2"><h3 className="font-bold text-ink text-sm truncate" title={displayName}>{displayName}</h3>{platform !== "chzzk" && <PlatformBadge platform={platform} />}</div>
                        {channel.title && channel.is_live ? <p className="line-clamp-2 break-words text-xs leading-relaxed text-ink-muted" title={channel.title}>{channel.title}</p> : <p className="text-xs text-ink-faint font-mono break-all">{channel.channel_id}</p>}
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                        <div role="button" tabIndex={0} onPointerDown={onReorderPointerDown} onPointerMove={onReorderPointerMove} onPointerUp={onReorderPointerUp} onPointerCancel={onReorderPointerUp} onLostPointerCapture={onReorderPointerUp} onMouseMove={onReorderMouseMove} onMouseUp={onReorderMouseUp} onKeyDown={onReorderKeyDown} className="grid size-10 place-items-center rounded-[var(--radius-control)] border border-line bg-surface-2 text-ink-faint hover:bg-surface-3 hover:text-ink cursor-grab active:cursor-grabbing touch-none select-none" title={t("드래그하거나 방향키를 눌러 채널 순서 변경")} aria-label={`${displayName} ${t("채널 순서 변경")}`} aria-keyshortcuts="ArrowLeft ArrowRight ArrowUp ArrowDown"><GripVertical className="size-4 pointer-events-none" /></div>
                        <button type="button" onClick={() => onRemove(channel)} className="grid size-10 place-items-center rounded-[var(--radius-control)] border border-line bg-surface-2 text-ink-faint transition-colors hover:border-danger/40 hover:bg-danger/10 hover:text-danger" title={t("채널 제거")} aria-label={`${t("채널 제거")}: ${displayName}`}><Trash2 className="size-4" /></button>
                    </div>
                </div>
                {channel.last_error && <p role="status" className="mb-3 break-words rounded-[var(--radius-control)] border border-danger/20 bg-danger/5 px-3 py-2 text-xs text-danger">{channel.last_error}</p>}

                <div className="flex flex-col gap-2 mb-3">
                    {channel.category && channel.is_live && <span className="self-start text-[11px] bg-surface-3 text-ink-muted px-2 py-0.5 rounded-full max-w-[150px] truncate border border-line-strong">{channel.category}</span>}
                    <TagManager availableTags={globalTags} selectedTags={channel.tags || []} onAddTag={(tag) => onAddTag(channel, tag)} onRemoveTag={(tag) => onRemoveTag(channel, tag)} onCreateTag={onCreateTag} />
                </div>

                <div className="flex flex-col gap-3 mb-3">
                    <div className="flex items-center justify-between text-xs"><span className="text-ink-faint">상태</span><span className={channel.is_live ? "text-live" : "text-ink-faint"}>{channel.is_live ? t("방송 중") : t("오프라인")}</span></div>
                    <div className="flex items-center justify-between text-xs"><span className="text-ink-faint">자동 녹화</span><Switch checked={channel.auto_record} onChange={() => onToggleAutoRecord(channel)} label={`${displayName} 자동 녹화`} /></div>
                    <Button onClick={() => props.onEditDownloadSettings(channel)} className="w-full text-xs">{t("녹화 설정")}</Button>
                    <DownloadHoldStatus channel={channel} />
                </div>

                <div className="mt-auto space-y-2">
                    {channel.recording?.is_recording ? (
                        <>
                            <div className="flex items-center gap-2">
                                <div className="flex-1 bg-danger/8 border border-danger/20 rounded-[var(--radius-control)] p-2 flex items-center justify-center gap-2 text-xs text-live"><Video className="w-3 h-3" /> <span className="font-mono tabular-nums">{formatDuration(duration)}</span></div>
                                <Button variant="danger" icon={Square} loading={isActionLoading} onClick={() => onStopRecord(channel)} className="size-11 p-2" title={t("녹화 중지")} aria-label={t("녹화 중지")} />
                            </div>
                            <RecordingStats channel={channel} />
                            {channel.chat_archiving?.is_running && <div className="flex items-center gap-2 bg-info/10 border border-info/20 rounded-[var(--radius-control)] p-2 text-xs text-info"><MessageSquare className="w-3 h-3" /> 채팅 저장 중 · {channel.chat_archiving.message_count.toLocaleString()}개</div>}
                        </>
                    ) : channel.is_live ? (
                        <Button variant="primary" icon={Play} loading={isActionLoading} onClick={() => onStartRecord(channel)} className="w-full">{isActionLoading ? "녹화 시작 중..." : "수동 녹화 시작"}</Button>
                    ) : (
                        <div className="bg-surface-3 border border-line rounded-[var(--radius-control)] p-2 flex items-center gap-2 text-xs text-ink-faint"><AlertCircle className="w-3 h-3" /> 방송을 기다리고 있습니다.</div>
                    )}
                </div>
            </div>
            <Button variant="ghost" onClick={props.onSelect} aria-expanded={props.isSelected} className="mx-3 mb-3">{t("채널 상세 보기")}</Button>
            {props.isSelected && channel.is_live && <ChannelThumbnail channel={channel} className="mx-auto aspect-video w-full max-w-[1200px]" />}
        </Card>
    );
}
