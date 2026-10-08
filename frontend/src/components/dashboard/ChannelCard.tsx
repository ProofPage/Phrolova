import { ChannelActions } from "./ChannelActions";
import { DownloadHoldStatus } from "./DownloadHoldStatus";
import { LivePreview } from "./LivePreview";
import { useEffect, useId, useState, useSyncExternalStore } from "react";
import { ChevronDown, MessageSquare, Play, Settings2, Square, Tags, Users } from "lucide-react";
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

function subscribeDesktopLayout(onChange: () => void) {
    const query = window.matchMedia("(min-width: 1024px)");
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
}

export function useDesktopChannelLayout() {
    return useSyncExternalStore(subscribeDesktopLayout, () => window.matchMedia("(min-width: 1024px)").matches, () => false);
}

export function ChannelRecordingControls(props: ChannelItemProps & { compact?: boolean }) {
    const { channel, onStartRecord, onStopRecord, onToggleAutoRecord, onEditDownloadSettings, isActionLoading } = props;
    const { t } = useLanguage();
    const displayName = channel.channel_name || channel.channel_id;
    const recording = channel.recording?.is_recording === true;
    return <div className={clsx("channel-recording-controls", props.compact && "channel-card-recording-controls")}>
        <div className="channel-control-secondary">
            <span className={clsx("channel-control-status", recording ? "text-ok" : channel.is_live ? "text-live" : "text-ink-faint")}><i aria-hidden="true" />{t(recording ? "녹화 중" : channel.is_live ? "라이브" : "오프라인")}</span>
            <label className="channel-desktop-auto">{props.compact ? <span>{t("자동 녹화")}</span> : t("자동 녹화")}<Switch checked={channel.auto_record} onChange={() => onToggleAutoRecord(channel)} label={`${displayName} ${t("자동 녹화")}`} /></label>
        </div>
        <div className="channel-control-primary">
            <Button icon={Settings2} variant="ghost" className={props.compact ? "channel-card-settings-inline" : undefined} aria-label={t("녹화 설정")} title={t("녹화 설정")} onClick={() => onEditDownloadSettings(channel)}>{props.compact ? <span className="channel-card-control-label">{t("녹화 설정")}</span> : t("녹화 설정")}</Button>
            <div className="channel-record-slot">{recording ? <Button className="channel-record-action" variant="danger" icon={Square} aria-label={t("녹화 중지")} title={t("녹화 중지")} loading={isActionLoading} onClick={() => onStopRecord(channel)}>{props.compact ? <span className="channel-card-control-label">{t("녹화 중지")}</span> : t("녹화 중지")}</Button>
            : channel.is_live && <Button className="channel-record-action" variant="primary" icon={Play} aria-label={t("녹화 시작하기")} title={t("녹화 시작하기")} loading={isActionLoading} onClick={() => onStartRecord(channel)}>{props.compact ? <span className="channel-card-control-label">{t("녹화 시작하기")}</span> : t("녹화 시작하기")}</Button>}</div>
        </div>
    </div>;
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

export function RecordingStats({ channel, duration }: { channel: Channel; duration?: number }) {
    const { t } = useLanguage();
    const active = channel.recording?.is_recording === true;
    if (!active) return null;
    return (
        <div className="recording-stats grid min-w-0 grid-cols-2 gap-2 text-[10px]" aria-label={t("녹화 정보")}>
            {duration !== undefined && <span className="flex min-w-0 flex-col gap-0.5"><span className="text-ink-faint">{t("녹화 시간")}</span><strong className="font-mono font-medium tabular-nums text-ok">{formatDuration(duration)}</strong></span>}
            <span className="flex min-w-0 flex-col gap-0.5"><span className="text-ink-faint">{t("용량")}</span><strong className="whitespace-nowrap font-mono font-medium tabular-nums text-ink-muted">{formatBytes(channel.recording?.file_size_bytes || 0)}</strong></span>
            <span className="flex min-w-0 flex-col gap-0.5"><span className="text-ink-faint">{t("속도")}</span><strong className="whitespace-nowrap font-mono font-medium tabular-nums text-ink-muted">{(channel.recording?.download_speed || 0).toFixed(2)} MB/s</strong></span>
            <span className="flex min-w-0 flex-col gap-0.5"><span className="text-ink-faint">{t("비트레이트")}</span><strong className="whitespace-nowrap font-mono font-medium tabular-nums text-ink-muted">{((channel.recording?.bitrate || 0) / 1000).toFixed(2)} Mbps</strong></span>
        </div>
    );
}

export function ChannelCard(props: ChannelItemProps & { isFullWidth?: boolean }) {
    const { channel, globalTags, onAddTag, onRemoveTag, onCreateTag, isDragging, isDropTarget } = props;
    const { t } = useLanguage();
    const displayName = channel.channel_name || channel.channel_id;
    const platform = channel.platform || "chzzk";
    const duration = useRecordingDuration(channel);
    const [tagsOpen, setTagsOpen] = useState(false);
    const tagsId = useId();
    const tags = <div className="channel-card-tags">
        {channel.category && channel.is_live && <span className="self-start text-[11px] bg-surface-3 text-ink-muted px-2 py-0.5 rounded-full max-w-[150px] truncate border border-line-strong">{channel.category}</span>}
        <TagManager availableTags={globalTags} selectedTags={channel.tags || []} onAddTag={(tag) => onAddTag(channel, tag)} onRemoveTag={(tag) => onRemoveTag(channel, tag)} onCreateTag={onCreateTag} triggerLabel="태그 관리" />
    </div>;

    return <Card padded={false} className={clsx("channel-row-card channel-card-shell", isDragging && "opacity-45", (props.isSelected || props.isFullWidth) && "col-span-full", props.isSelected && "channel-card-expanded", isDropTarget && "ring-2 ring-[var(--primary)]")} data-channel-key={getChannelKey(channel)}>
        <div className="channel-card-header">
            <div className="channel-card-name">
                {channel.profile_image_url ? <img src={channel.profile_image_url} alt="" className="size-9 shrink-0 rounded-full object-cover" /> : <span className="channel-card-avatar size-9 shrink-0 place-items-center rounded-full border-2 border-line-strong bg-surface-3 text-ink-faint"><Users className="size-4" /></span>}
                <h3 className="channel-info min-w-0 text-sm font-semibold text-ink" title={displayName}>{displayName}</h3>
            </div>
            <div className="channel-card-subtitle">
                <span className="channel-card-platform-chip"><PlatformBadge platform={platform} /></span>
                {channel.is_live && channel.title && <p title={channel.title}>{channel.title}</p>}
                {channel.is_live && typeof channel.viewer_count === "number" && <span className="channel-card-viewers" aria-label={`${t("시청자")}: ${channel.viewer_count.toLocaleString()}`} title={`${t("시청자")}: ${channel.viewer_count.toLocaleString()}`}><Users className="size-3 shrink-0" aria-hidden="true" />{channel.viewer_count.toLocaleString()}</span>}
            </div>
            <ChannelActions {...props} card onManageTags={() => setTagsOpen(value => !value)} />
            <button type="button" className="channel-card-tag-toggle icon-button" onClick={() => setTagsOpen(value => !value)} aria-expanded={tagsOpen} aria-controls={tagsId} aria-label={channel.tags?.length ? `${t("태그")} ${channel.tags.length}${t("개")}, ${t("태그 관리")}` : t("태그 관리")} title={t("태그 관리")}><Tags className="size-4" />{!!channel.tags?.length && <span>{channel.tags.length}</span>}</button>
        </div>
        <ChannelRecordingControls {...props} compact />
        <div className="channel-card-secondary">
            <button type="button" className="ui-button btn-ghost" aria-expanded={!!props.isSelected} aria-label={`${t(props.isSelected ? "상세 접기" : "채널 상세 보기")}: ${displayName}`} onClick={props.onSelect}><ChevronDown className={clsx("size-4", props.isSelected && "rotate-180")} />{t(props.isSelected ? "상세 접기" : "상세 보기")}</button>
            <Button icon={Settings2} variant="ghost" aria-label={t("녹화 설정")} title={t("녹화 설정")} onClick={() => props.onEditDownloadSettings(channel)}>{t("녹화 설정")}</Button>
        </div>
        {(channel.recording?.is_recording || channel.chat_archiving?.is_running) && <div className="channel-card-stats">
            <RecordingStats channel={channel} duration={duration} />
            {channel.chat_archiving?.is_running && <p className="mt-2 flex items-center gap-1.5 text-xs text-info"><MessageSquare className="size-3 shrink-0" />{t("채팅 저장 중")} · {channel.chat_archiving.message_count.toLocaleString()}{t("개")}</p>}
        </div>}
        <div className="channel-card-content">{channel.last_error && <ChannelError message={channel.last_error} />}<DownloadHoldStatus channel={channel} /></div>
        <div id={tagsId} hidden={!tagsOpen}>{tagsOpen && <><div className="flex items-center justify-between gap-2"><span className="text-xs text-ink-muted">{t("태그 관리")}</span><button type="button" className="ui-button btn-ghost" onClick={() => setTagsOpen(false)}>{t("닫기")}</button></div>{tags}</>}</div>
        {props.isSelected && <LivePreview channelKey={getChannelKey(channel)} isLive={channel.is_live} name={displayName} poster={channel.thumbnail_url} />}
    </Card>;
}

export function ChannelError({ message }: { message: string }) {
    return <details role="status" className="min-w-0 rounded-[var(--radius-control)] border border-danger/20 bg-danger/5 px-3 py-2 text-xs text-danger">
        <summary className="cursor-pointer"><span className="line-clamp-2 [overflow-wrap:anywhere]">{message}</span></summary>
        <p className="mt-2 [overflow-wrap:anywhere]">{message}</p>
    </details>;
}
