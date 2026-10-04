import { useEffect, useState } from "react";
import { AlertCircle, AlertTriangle, Eye, GripVertical, MessageSquare, Play, Square, Trash2, Users, Video } from "lucide-react";
import { clsx } from "clsx";
import { PLATFORM_LABELS, type Channel, type Platform } from "../../api/client";
import type { ReorderProps } from "../../hooks/useChannelReorder";
import { getChannelKey } from "../../utils/channel";
import { formatBytes, formatDuration } from "../../utils/format";
import { TagManager } from "../ui/TagManager";
import { Button, Card, Switch } from "../ui/primitives";

const PLATFORM_BADGE_STYLES: Record<Platform, string> = {
    chzzk: "bg-chzzk/10 text-chzzk border-chzzk/25",
    twitcasting: "bg-twitcasting/10 text-twitcasting border-twitcasting/25",
    x_spaces: "bg-xspaces/10 text-xspaces border-xspaces/25",
    youtube: "bg-youtube/10 text-youtube border-youtube/25",
};

export interface ChannelItemProps extends ReorderProps {
    channel: Channel;
    onStartRecord: (channel: Channel) => void;
    onStopRecord: (channel: Channel) => void;
    onRemove: (channel: Channel) => void;
    onToggleAutoRecord: (channel: Channel) => void;
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
        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-sm border ${PLATFORM_BADGE_STYLES[platform]}`}>
            {PLATFORM_LABELS[platform]}
        </span>
    );
}

export function RecordingStats({ channel }: { channel: Channel }) {
    if (!channel.recording?.is_recording) return null;
    return (
        <div className="grid grid-cols-3 gap-2 text-xs">
            <div className="bg-surface-3 border border-line rounded px-2 py-1">
                <div className="text-ink-faint">용량</div>
                <div className="text-ink-muted font-mono">{formatBytes(channel.recording.file_size_bytes || 0)}</div>
            </div>
            <div className="bg-surface-3 border border-line rounded px-2 py-1">
                <div className="text-ink-faint">속도</div>
                <div className="text-ink-muted font-mono">{(channel.recording.download_speed || 0).toFixed(2)} MB/s</div>
            </div>
            <div className="bg-surface-3 border border-line rounded px-2 py-1">
                <div className="text-ink-faint">비트레이트</div>
                <div className="text-ink-muted font-mono">{(channel.recording.bitrate || 0).toFixed(0)} kbps</div>
            </div>
        </div>
    );
}

export function ChannelCard(props: ChannelItemProps) {
    const { channel, onStartRecord, onStopRecord, onRemove, onToggleAutoRecord, isActionLoading, globalTags, onAddTag, onRemoveTag, onCreateTag, onReorderPointerDown, onReorderPointerMove, onReorderPointerUp, onReorderMouseMove, onReorderMouseUp, onReorderKeyDown, isDragging, isDropTarget } = props;
    const displayName = channel.channel_name || channel.channel_id;
    const platform = channel.platform || "chzzk";
    const duration = useRecordingDuration(channel);

    return (
        <Card
            padded={false}
            className={clsx(
                "overflow-hidden transition-all group flex flex-col",
                channel.recording?.is_recording && "animate-pulse-border",
                isDragging && "opacity-45 scale-[0.985]",
                isDropTarget && "ring-2 ring-[var(--primary)] ring-offset-2 ring-offset-surface-0",
            )}
            data-channel-key={getChannelKey(channel)}
        >
            <div className="relative bg-surface-0 overflow-hidden w-full aspect-video">
                {channel.is_live && channel.thumbnail_url ? (
                    <img src={channel.thumbnail_url} alt={`${displayName} 방송 썸네일`} className="w-full h-full object-cover" loading="lazy" />
                ) : (
                    <div className="w-full h-full flex flex-col items-center justify-center text-ink-faint bg-linear-to-br from-surface-2 to-surface-0">
                        <AlertCircle className="w-10 h-10 mb-2 opacity-40" />
                        <span className="text-xs font-semibold tracking-wider opacity-60">OFFLINE</span>
                    </div>
                )}

                {channel.is_live && (
                    <div className="absolute top-2 left-2 flex gap-1.5">
                        <span className="bg-live text-white text-[10px] font-bold px-2 py-0.5 rounded-sm shadow-lg animate-pulse">● LIVE</span>
                        {channel.recording?.is_recording && <span className="bg-ok text-surface-0 text-[10px] font-bold px-2 py-0.5 rounded-sm">REC</span>}
                    </div>
                )}

                {channel.is_live && !!channel.viewer_count && (
                    <div className="absolute bottom-2 right-2 bg-surface-0/80 backdrop-blur-sm text-ink text-[11px] font-medium px-2 py-0.5 rounded flex items-center gap-1">
                        <Eye className="w-3 h-3" /> {channel.viewer_count.toLocaleString()}
                    </div>
                )}
                {platform !== "chzzk" && <div className="absolute bottom-2 left-2"><PlatformBadge platform={platform} /></div>}

                <div className="absolute top-2 right-2 flex items-start gap-1.5 z-10">
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
                        className="p-1.5 bg-surface-0/75 hover:bg-surface-3 text-ink-faint hover:text-ink rounded-[var(--radius-control)] cursor-grab active:cursor-grabbing transition-colors touch-none select-none"
                        title="드래그하거나 방향키를 눌러 채널 순서 변경"
                        aria-label={`${displayName} 채널 순서 변경`}
                        aria-keyshortcuts="ArrowLeft ArrowRight ArrowUp ArrowDown"
                    >
                        <GripVertical className="w-3.5 h-3.5 pointer-events-none" />
                    </div>
                    {channel.last_error && (
                        <div className="relative group/error">
                            <div className="p-1.5 bg-danger text-white rounded-[var(--radius-control)] cursor-help"><AlertTriangle className="w-3.5 h-3.5" /></div>
                            <div className="absolute top-full right-0 mt-1 w-48 bg-surface-2 border border-danger/50 text-danger text-xs p-2.5 rounded-[var(--radius-control)] shadow-xl opacity-0 invisible group-hover/error:opacity-100 group-hover/error:visible transition-all z-20 pointer-events-none wrap-break-word">
                                {channel.last_error}
                            </div>
                        </div>
                    )}
                    <button onClick={() => onRemove(channel)} className="p-1.5 bg-surface-0/70 hover:bg-danger text-ink-faint hover:text-white rounded-[var(--radius-control)] transition-all opacity-0 group-hover:opacity-100" title="채널 제거">
                        <Trash2 className="w-3.5 h-3.5" />
                    </button>
                </div>
            </div>

            <div className="p-4 flex-1 flex flex-col">
                <div className="flex items-center gap-3 mb-2 min-w-0">
                    {channel.profile_image_url ? (
                        <img src={channel.profile_image_url} alt={displayName} className="w-9 h-9 rounded-full object-cover shrink-0 border-2 border-line-strong" />
                    ) : (
                        <div className="w-9 h-9 rounded-full bg-surface-3 flex items-center justify-center shrink-0 border-2 border-line-strong"><Users className="w-4 h-4 text-ink-faint" /></div>
                    )}
                    <div className="min-w-0 flex-1">
                        <h3 className="font-bold text-ink text-sm truncate" title={displayName}>{displayName}</h3>
                        {channel.title && channel.is_live ? <p className="text-xs text-ink-muted truncate" title={channel.title}>{channel.title}</p> : <p className="text-xs text-ink-faint font-mono truncate">{channel.channel_id}</p>}
                    </div>
                </div>

                <div className="flex flex-col gap-2 mb-3">
                    {channel.category && channel.is_live && <span className="self-start text-[11px] bg-surface-3 text-ink-muted px-2 py-0.5 rounded-full max-w-[150px] truncate border border-line-strong">{channel.category}</span>}
                    <TagManager availableTags={globalTags} selectedTags={channel.tags || []} onAddTag={(tag) => onAddTag(channel, tag)} onRemoveTag={(tag) => onRemoveTag(channel, tag)} onCreateTag={onCreateTag} />
                </div>

                <div className="flex flex-col gap-3 mb-3">
                    <div className="flex items-center justify-between text-xs"><span className="text-ink-faint">상태</span><span className={channel.is_live ? "text-live" : "text-ink-faint"}>{channel.is_live ? "LIVE" : "OFFLINE"}</span></div>
                    <div className="flex items-center justify-between text-xs"><span className="text-ink-faint">자동 녹화</span><Switch checked={channel.auto_record} onChange={() => onToggleAutoRecord(channel)} label={`${displayName} 자동 녹화`} /></div>
                </div>

                <div className="mt-auto space-y-2">
                    {channel.recording?.is_recording ? (
                        <>
                            <div className="flex items-center gap-2">
                                <div className="flex-1 bg-danger/10 border border-danger/20 rounded-[var(--radius-control)] p-2 flex items-center justify-center gap-2 text-xs text-live animate-pulse"><Video className="w-3 h-3" /> {formatDuration(duration)}</div>
                                <Button variant="danger" icon={Square} loading={isActionLoading} onClick={() => onStopRecord(channel)} className="p-2" title="녹화 중단" />
                            </div>
                            <RecordingStats channel={channel} />
                            {channel.chat_archiving?.is_running && <div className="flex items-center gap-2 bg-info/10 border border-info/20 rounded-[var(--radius-control)] p-2 text-xs text-info"><MessageSquare className="w-3 h-3" /> 채팅 수집 중 ({channel.chat_archiving.message_count.toLocaleString()}개)</div>}
                        </>
                    ) : channel.is_live ? (
                        <Button icon={Play} loading={isActionLoading} onClick={() => onStartRecord(channel)} className="w-full text-ok">{isActionLoading ? "처리 중..." : "수동 녹화 시작"}</Button>
                    ) : (
                        <div className="bg-surface-3 border border-line rounded-[var(--radius-control)] p-2 flex items-center gap-2 text-xs text-ink-faint"><AlertCircle className="w-3 h-3" /> 방송 대기 중...</div>
                    )}
                </div>
            </div>
        </Card>
    );
}
