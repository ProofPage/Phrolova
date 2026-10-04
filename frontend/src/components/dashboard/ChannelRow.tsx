import { AlertCircle, AlertTriangle, Eye, GripVertical, MessageSquare, Play, Square, Trash2, Users, Video } from "lucide-react";
import { clsx } from "clsx";
import { getChannelKey } from "../../utils/channel";
import { formatDuration } from "../../utils/format";
import { TagManager } from "../ui/TagManager";
import { Button, Card, Switch } from "../ui/primitives";
import { PlatformBadge, RecordingStats, type ChannelItemProps, useRecordingDuration } from "./ChannelCard";

export function ChannelRow(props: ChannelItemProps) {
    const { channel, onStartRecord, onStopRecord, onRemove, onToggleAutoRecord, isActionLoading, globalTags, onAddTag, onRemoveTag, onCreateTag, onReorderPointerDown, onReorderPointerMove, onReorderPointerUp, onReorderMouseMove, onReorderMouseUp, onReorderKeyDown, isDragging, isDropTarget } = props;
    const displayName = channel.channel_name || channel.channel_id;
    const platform = channel.platform || "chzzk";
    const duration = useRecordingDuration(channel);

    return (
        <Card
            padded={false}
            className={clsx(
                "overflow-hidden transition-all group flex min-h-[150px] min-w-[900px]",
                channel.recording?.is_recording && "animate-pulse-border",
                isDragging && "opacity-45",
                isDropTarget && "ring-2 ring-[var(--primary)] ring-offset-2 ring-offset-surface-0",
            )}
            data-channel-key={getChannelKey(channel)}
        >
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
                className="w-9 grid place-items-center text-ink-faint hover:text-ink hover:bg-surface-3 cursor-grab active:cursor-grabbing border-r border-line transition-colors shrink-0 touch-none select-none"
                title="드래그하거나 방향키를 눌러 채널 순서 변경"
                aria-label={`${displayName} 채널 순서 변경`}
                aria-keyshortcuts="ArrowLeft ArrowRight ArrowUp ArrowDown"
            >
                <GripVertical className="w-4 h-4 pointer-events-none" />
            </div>
            <div className="relative bg-surface-0 overflow-hidden w-48 xl:w-64 shrink-0">
                {channel.is_live && channel.thumbnail_url ? (
                    <img src={channel.thumbnail_url} alt={`${displayName} 방송 썸네일`} className="w-full h-full object-cover" loading="lazy" />
                ) : (
                    <div className="w-full h-full flex flex-col items-center justify-center text-ink-faint bg-linear-to-br from-surface-2 to-surface-0">
                        <AlertCircle className="w-8 h-8 mb-2 opacity-40" />
                        <span className="text-xs font-semibold tracking-wider opacity-60">OFFLINE</span>
                    </div>
                )}
                {channel.is_live && <span className="absolute top-2 left-2 bg-live text-white text-[10px] font-bold px-2 py-0.5 rounded-sm animate-pulse">● LIVE</span>}
                {channel.is_live && !!channel.viewer_count && <span className="absolute bottom-2 right-2 bg-surface-0/80 text-ink text-[11px] px-2 py-0.5 rounded flex items-center gap-1"><Eye className="w-3 h-3" /> {channel.viewer_count.toLocaleString()}</span>}
                {platform !== "chzzk" && <div className="absolute bottom-2 left-2"><PlatformBadge platform={platform} /></div>}
            </div>

            <div className="p-4 flex-1 flex items-center gap-4 min-w-0">
                <div className="flex items-center gap-3 min-w-0 flex-1">
                    {channel.profile_image_url ? (
                        <img src={channel.profile_image_url} alt={displayName} className="w-9 h-9 rounded-full object-cover shrink-0 border-2 border-line-strong" />
                    ) : (
                        <div className="w-9 h-9 rounded-full bg-surface-3 flex items-center justify-center shrink-0 border-2 border-line-strong"><Users className="w-4 h-4 text-ink-faint" /></div>
                    )}
                    <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                            <h3 className="font-bold text-ink text-sm truncate" title={displayName}>{displayName}</h3>
                            {channel.last_error && <span title={channel.last_error}><AlertTriangle className="w-4 h-4 text-danger shrink-0" /></span>}
                        </div>
                        {channel.title && channel.is_live ? <p className="text-xs text-ink-muted truncate" title={channel.title}>{channel.title}</p> : <p className="text-xs text-ink-faint font-mono truncate">{channel.channel_id}</p>}
                        {channel.category && channel.is_live && <p className="text-[11px] text-ink-faint truncate mt-1">{channel.category}</p>}
                    </div>
                </div>

                <div className="w-40 shrink-0">
                    <TagManager availableTags={globalTags} selectedTags={channel.tags || []} onAddTag={(tag) => onAddTag(channel, tag)} onRemoveTag={(tag) => onRemoveTag(channel, tag)} onCreateTag={onCreateTag} />
                </div>

                <div className="flex flex-col gap-3 px-4 border-l border-line shrink-0">
                    <span className={`text-xs font-medium ${channel.is_live ? "text-live" : "text-ink-faint"}`}>{channel.is_live ? "LIVE" : "OFFLINE"}</span>
                    <div className="flex items-center gap-2 text-xs text-ink-faint">
                        자동 녹화
                        <Switch checked={channel.auto_record} onChange={() => onToggleAutoRecord(channel)} label={`${displayName} 자동 녹화`} />
                    </div>
                </div>

                <div className="w-64 border-l border-line pl-4 shrink-0 space-y-2">
                    {channel.recording?.is_recording ? (
                        <>
                            <div className="flex items-center gap-2">
                                <div className="flex-1 bg-danger/10 border border-danger/20 rounded-[var(--radius-control)] p-2 flex items-center justify-center gap-2 text-xs text-live animate-pulse"><Video className="w-3 h-3" /> {formatDuration(duration)}</div>
                                <Button variant="danger" icon={Square} loading={isActionLoading} onClick={() => onStopRecord(channel)} className="p-2" title="녹화 중단" />
                            </div>
                            <RecordingStats channel={channel} />
                            {channel.chat_archiving?.is_running && <p className="flex items-center gap-1 text-xs text-info"><MessageSquare className="w-3 h-3" /> 채팅 {channel.chat_archiving.message_count.toLocaleString()}개</p>}
                        </>
                    ) : channel.is_live ? (
                        <Button icon={Play} loading={isActionLoading} onClick={() => onStartRecord(channel)} className="w-full text-ok">{isActionLoading ? "처리 중..." : "수동 녹화 시작"}</Button>
                    ) : (
                        <div className="bg-surface-3 border border-line rounded-[var(--radius-control)] p-2 flex items-center gap-2 text-xs text-ink-faint"><AlertCircle className="w-3 h-3" /> 방송 대기 중...</div>
                    )}
                </div>

                <button onClick={() => onRemove(channel)} className="p-2 text-ink-faint hover:text-danger transition-colors opacity-0 group-hover:opacity-100" title="채널 제거"><Trash2 className="w-4 h-4" /></button>
            </div>
        </Card>
    );
}
