import { getActiveLocale, formatNumber } from "../../i18n";
import { translate } from "../../i18n";
import { memo, useRef, useState, type CSSProperties } from 'react';
import { Loader2, Play, Settings2, Square, TrendingUp, Users } from 'lucide-react';
import { RecordingPostprocess } from './RecordingPostprocess';
import { clsx } from 'clsx';
import { type Channel } from '../../api/client';
import type { ReorderProps } from '../../hooks/useChannelReorder';
import { getChannelKey } from '../../utils/channel';
import { localizedStatus } from '../../utils/error';
import { localizePlatformNames } from '../../utils/platformNames';
import { formatBytes, formatDuration } from '../../utils/format';
import { useLanguage } from '../../contexts/LanguageContext';
import { Button, Card, Switch } from '../ui/primitives';
import { TagManager } from '../ui/TagManager';
import { PlatformBadge } from '../ui/PlatformBadge';
import { ChannelActions } from './ChannelActions';
import { LivePreview } from './LivePreview';
import { DownloadHoldStatus } from './DownloadHoldStatus';
import './recording-channel.css';

export interface ChannelItemProps extends ReorderProps {
    channel: Channel;
    isSelected?: boolean;
    onSelect?: () => void;
    detailsId?: string;
    layoutStyle?: CSSProperties;
    onStartRecord: (channel: Channel) => void;
    onStopRecord: (channel: Channel) => void;
    onRemove: (channel: Channel) => void;
    onToggleAutoRecord: (channel: Channel) => void;
    onEditDownloadSettings: (channel: Channel) => void;
    isActionLoading: boolean;
    pendingAction?: 'start' | 'stop' | 'remove';
    isAutoRecordLoading?: boolean;
    isTagLoading?: boolean;
    globalTags: string[];
    onAddTag: (channel: Channel, tag: string) => void;
    onRemoveTag: (channel: Channel, tag: string) => void;
    onCreateTag: (tag: string) => void;
}

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0;

function RecordingStatus({ channel, pendingAction }: Pick<ChannelItemProps, 'channel' | 'pendingAction'>) {
    const { t } = useLanguage();
    const state = channel.recording?.state;
    const error = channel.last_error && !channel.last_error.startsWith('감시 오류:') ? channel.last_error : null;
    const [label, tone] = channel.skip_pending ? ["live.skippingRecording", 'neutral']
        : pendingAction === 'stop' || state === 'stopping' ? ["live.stoppingRecording", 'neutral']
        : pendingAction === 'start' ? ["live.preparingRecording", 'neutral']
        : state === 'connecting' ? ["live.connectingToStream", 'info']
        : state === 'reconnecting' ? ["live.reconnecting", 'warn']
        : channel.recording?.is_recording ? ["live.recording", 'ok']
        : state === 'error' || error ? [channel.recording?.has_data === false || !channel.recording?.file_size_bytes ? "live.recordingCouldNotStart" : "live.recordingError", 'danger']
        : channel.download_hold_reason ? ["live.skippedRecording", 'neutral']
        : state === 'completed' ? ["live.recordingCompleted", 'ok']
        : ["live.waitingToRecord", 'neutral'];
    return <span className={`recording-status is-${tone}`} role="status" aria-live="polite"><i aria-hidden="true" />{t(label)}</span>;
}

function RecordingChannelHeader({ channel, pendingAction }: Pick<ChannelItemProps, 'channel' | 'pendingAction'>) {
    const { t } = useLanguage();
    const name = channel.channel_name || channel.channel_id;
    const tags = channel.tags || [];
    // 외부 CDN이 이미지를 거부해도 깨진 그림을 남기지 않고 주소가 갱신되면 다시 시도한다.
    const [failedAvatar, setFailedAvatar] = useState<string | null>(null);
    const avatarUrl = channel.profile_image_url;
    // Bilibili의 online 값은 동시 시청자 수가 아니라 플랫폼 인기도다.
    const popularity = channel.viewer_count_type === 'popularity' || (!channel.viewer_count_type && channel.platform === 'bilibili');
    const countLabel = popularity ? 'live.popularity' : 'live.viewers';
    const CountIcon = popularity ? TrendingUp : Users;
    return <header className="recording-channel-identity">
        {avatarUrl && failedAvatar !== avatarUrl ? <img key={avatarUrl} src={avatarUrl} alt="" className="recording-avatar" referrerPolicy="no-referrer" onError={() => setFailedAvatar(avatarUrl)} onLoad={() => setFailedAvatar(null)} />
            : <span className="recording-avatar recording-avatar-fallback" aria-hidden="true"><Users className="size-4" /></span>}
        <div className="recording-channel-copy">
            <div className="recording-channel-name"><h3 title={name}>{name}</h3><PlatformBadge platform={channel.platform || 'chzzk'} /></div>
            <p className="recording-broadcast-title" title={channel.title || undefined}>{channel.is_live && channel.title ? channel.title : t(channel.broadcast_status === 'checking' ? translate("live.checkingLiveStatus") : channel.broadcast_status === 'error' ? translate("live.couldNotCheckLiveStatus") : translate("live.thisChannelIsCurrentlyOffline"))}</p>
            {(channel.is_live || tags.length > 0) && <div className="recording-channel-meta">
                {/* RPLAY's viewer API does not provide a concurrent viewer count. */}
                {channel.is_live && channel.platform !== 'rplay' && finite(channel.viewer_count) && <span className="recording-viewers" title={`${t(countLabel)}: ${channel.viewer_count.toLocaleString(getActiveLocale())}`}><CountIcon className="size-3" aria-hidden="true" /><span>{t(countLabel)} {channel.viewer_count.toLocaleString(getActiveLocale())}</span></span>}
                {tags.slice(0, 2).map(tag => <span className="recording-tag" key={tag} title={tag}>{tag}</span>)}
                {tags.length > 2 && <span className="recording-tag-overflow" title={tags.slice(2).join(', ')}>+{tags.length - 2}</span>}
            </div>}
            <div className="recording-channel-statuses" aria-label={t("live.liveAndRecordingStatus")}>
                <span className={clsx('recording-status', channel.is_live && 'is-info')} role="status"><i aria-hidden="true" />{t(channel.broadcast_status === 'checking' ? translate("live.checkingStatus") : channel.broadcast_status === 'error' ? translate("live.statusCheckFailed") : channel.is_live ? translate("live.title") : translate("live.offline"))}</span>
                {(channel.is_live || channel.recording?.state || (channel.last_error && !channel.last_error.startsWith('감시 오류:')) || pendingAction) && <RecordingStatus channel={channel} pendingAction={pendingAction} />}
            {channel.monitor_status && <span className="recording-status">{t(channel.monitor_status === 'paused' ? translate("live.monitoringPaused") : channel.monitor_status === 'retry_wait' ? translate("live.waitingToRetryMonitoring") : translate("live.monitoring"))}</span>}
            </div>
            {channel.download_hold_reason && <DownloadHoldStatus channel={channel} />}
            {channel.recording?.warning_message && <p className="recording-status-message text-warn" role="status">{localizedStatus(channel.recording.warning_message,"errors.recording")}</p>}
            {channel.monitor_error && <p className="recording-status-message text-danger" role="status">{t("live.monitoringErrorInRecordingChannelCard")}: {localizedStatus(channel.monitor_error,"errors.network")}</p>}
            {channel.last_error && !channel.last_error.startsWith('감시 오류:') && <p className="recording-status-message text-danger" role="status">{localizedStatus(channel.last_error,"errors.recording")}{channel.retry_at && <span className="text-ink-muted"> {translate("live.waitingToReconnect")}</span>}</p>}
        </div>
    </header>;
}

function RecordingControls(props: ChannelItemProps) {
    const { channel, pendingAction, isActionLoading, isAutoRecordLoading, onToggleAutoRecord, onStartRecord, onStopRecord, onEditDownloadSettings } = props;
    const { t } = useLanguage();
    const name = channel.channel_name || channel.channel_id;
    const recording = channel.recording?.is_recording || ['connecting', 'reconnecting', 'stopping'].includes(channel.recording?.state || '');
    const failed = channel.recording?.state === 'error' || Boolean(channel.last_error && !channel.last_error.startsWith('감시 오류:'));
    const retryStop = channel.recording?.state === 'stopping' && pendingAction !== 'stop' && !channel.skip_pending;
    return <div className="recording-channel-controls">
            <div className="recording-auto-control" aria-busy={!!isAutoRecordLoading}>
                <span>{t("live.autoRecord")}</span><Switch checked={channel.auto_record} disabled={isAutoRecordLoading || isActionLoading} onChange={() => onToggleAutoRecord(channel)} label={`${name} ${t("live.autoRecord")}`} />
                {isAutoRecordLoading && <span className="recording-saving" role="status"><Loader2 className="size-3 animate-spin" aria-hidden="true" />{t("live.saving")}</span>}
            </div>
        <div className="recording-primary-controls">
            <Button icon={Settings2} variant="ghost" disabled={isActionLoading} onClick={() => onEditDownloadSettings(channel)} title={t("live.recordingSettings")}>{t("live.recordingSettings")}</Button>
            {recording ? <Button variant="danger" icon={Square} disabled={isActionLoading || channel.skip_pending} loading={pendingAction === 'stop'} onClick={() => onStopRecord(channel)}>{t(retryStop ? "live.tryAgain" : pendingAction === 'stop' || channel.recording?.state === 'stopping' ? "live.stoppingRecording" : "live.stopRecording")}</Button>
                : (channel.is_live || failed) && <Button variant="primary" icon={Play} disabled={isActionLoading} loading={pendingAction === 'start'} onClick={() => onStartRecord(channel)}>{t(pendingAction === 'start' ? "live.preparingRecording" : failed ? "live.tryAgain" : "live.startRecording")}</Button>}
        </div>
    </div>;
}

type Measurements = { duration?: number; size?: number; speed?: number; bitrate?: number };

/** The server's media clock advances only while data is actually received. */
const RecordingMetrics = memo(function RecordingMetrics({ recording }: { recording: Channel['recording'] }) {
    const { t } = useLanguage();
    const last = useRef<Measurements>({});
    const session = useRef<string | null | undefined>(undefined);
    const key = recording?.session_id || recording?.start_time;
    if (recording && key !== session.current) { last.current = {}; session.current = key; }
    const hasData = recording?.has_data ?? (finite(recording?.file_size_bytes) ? recording.file_size_bytes > 0 : (last.current.size || 0) > 0);
    const active = recording?.is_recording === true && hasData;
    if (hasData && finite(recording?.duration_seconds)) last.current.duration = recording.duration_seconds;
    if (finite(recording?.file_size_bytes)) last.current.size = recording.file_size_bytes;
    if (hasData && finite(recording?.download_speed)) last.current.speed = recording.download_speed;
    if (hasData && finite(recording?.bitrate)) last.current.bitrate = recording.bitrate;
    const value = last.current;
    const metrics = [
        ["live.recordingTime", hasData && finite(value.duration) ? formatDuration(Math.floor(value.duration)) : '—'],
        ["live.fileSize", finite(value.size) ? formatBytes(value.size) : '—'],
        ["live.writeSpeed", hasData && finite(value.speed) ? `${formatNumber(value.speed, {minimumFractionDigits:2, maximumFractionDigits:2})} MB/s` : '—'],
        ["live.bitrate", hasData && finite(value.bitrate) && value.bitrate > 0 ? `${formatNumber(value.bitrate / 1000, {minimumFractionDigits:2, maximumFractionDigits:2})} Mbps` : '—'],
    ];
    return <dl className={clsx('recording-metrics', !active && 'is-inactive')} aria-label={t("live.recordingDetails")}>
        {metrics.map(([label, text]) => <div key={label}><dt>{t(label)}</dt><dd className={label === "live.recordingTime" && active ? 'text-ok' : undefined}>{text}</dd></div>)}
    </dl>;
});

function RecordingChannelDetails({ channel }: { channel: Channel }) {
    const { t } = useLanguage();
    const name = channel.channel_name || channel.channel_id;
    const recording = channel.recording;
    const url = channel.channel_url || ((channel.platform || 'chzzk') === 'chzzk' ? `https://chzzk.naver.com/live/${encodeURIComponent(channel.channel_id)}` : null);
    return <div className="recording-channel-details">
        <LivePreview channelKey={getChannelKey(channel)} isLive={channel.is_live} broadcastState={channel.broadcast_status} name={name} poster={channel.thumbnail_url} />
        <div className="recording-details-copy">
        <dl className="recording-details-fields">
            <div><dt>{t("live.channels")}</dt><dd>{name}</dd></div>
            {channel.title && <div><dt>{t("live.streamTitle")}</dt><dd>{channel.title}</dd></div>}
            {channel.category && <div><dt>{t("live.category")}</dt><dd>{channel.category}</dd></div>}
            {url && <div><dt>{t("live.streamURL")}</dt><dd><a href={url} target="_blank" rel="noopener noreferrer">{url}</a></dd></div>}
            {recording?.output_path && <div><dt>{t("live.recordingFile")}</dt><dd>{recording.output_path}</dd></div>}
            {recording?.start_time && <div><dt>{t("live.recordingStartedAt")}</dt><dd>{new Date(recording.start_time).toLocaleString(getActiveLocale())}</dd></div>}
            {recording?.continuity_source?.selected && <div><dt>{t("live.receivingSource")}</dt><dd>{t(recording.continuity_source.selected.cdn === 'akamai' ? 'Akamai CDN' : recording.continuity_source.selected.cdn === 'korean' ? 'Naver CDN' : translate("live.defaultCDN"))} · {recording.continuity_source.selected.mode === 'llhls' ? 'LL-HLS' : 'HLS'}</dd></div>}
            {recording?.continuity_source?.standby && <div><dt>{t("live.standbyCDN")}</dt><dd>Akamai CDN · {t(({ ready: translate("live.ready"), absent: translate("live.notProvided"), unavailable: translate("live.connectionCheckFailed") })[recording.continuity_source.standby.state])}</dd></div>}
            {(channel.recording_quality || recording?.recording_resolution?.height) && <div><dt>{t("live.recordingQuality")}</dt><dd>{recording?.recording_resolution?.width && recording?.recording_resolution?.height ? `${recording.recording_resolution.width}×${recording.recording_resolution.height}${recording.recording_resolution.fps ? ` · ${recording.recording_resolution.fps}fps` : ''}` : channel.recording_quality === 'best' ? t("live.highestQuality") : channel.recording_quality}</dd></div>}
            {channel.recording_inspection && <div><dt>{t("live.fileInspection")}</dt><dd className={channel.recording_inspection.state === 'passed' ? 'text-ok' : 'text-warn'} role="status">{localizedStatus(channel.recording_inspection.message, channel.recording_inspection.state === "passed" ? "download.fileInspectionComplete" : "errors.inspection")}</dd></div>}
            {channel.download_condition && <div><dt>{t("live.recordingCondition")}</dt><dd>{t(({ all: translate("live.recordAllLiveStreams"), watchalong: translate("live.recordWatchAlongStreamsOnlyInRecordingChannelCard"), exclude_watchalong: translate("live.excludeWatchAlongStreams") })[channel.download_condition])}</dd></div>}
            {!!channel.tags?.length && <div className="recording-tags-field"><dt>{t("live.tags")}</dt><dd>{channel.tags.join(', ')}</dd></div>}
        </dl>
        {!!channel.recent_errors?.length && <details className="recording-error"><summary>{t("live.recentErrorHistory")}</summary>{channel.recent_errors.slice().reverse().map((error,index)=><div key={`${error.timestamp}-${index}`} className="mt-2"><p className="text-ink-muted">{new Date(error.timestamp).toLocaleString(getActiveLocale())} · {error.kind === 'monitor' ? t("live.monitoringInRecordingChannelCard") : t("live.recordings")}</p><p>{localizedStatus(error.message,"errors.recording")}</p>{error.detail && <pre className="whitespace-pre-wrap break-words">{error.detail}</pre>}</div>)}</details>}
        {channel.last_error && <details className="recording-error"><summary>{t("live.recentRecordingErrors")}</summary><p>{localizedStatus(channel.last_error,"errors.recording")}</p>{channel.error_detail && <pre className="whitespace-pre-wrap break-words text-xs">{localizePlatformNames(channel.error_detail)}</pre>}</details>}
        </div>
    </div>;
}

export function RecordingChannelCard(props: ChannelItemProps & { mode: 'grid' | 'list' }) {
    const { channel } = props;
    const { t } = useLanguage();
    const detailsId = props.detailsId || `channel-details-${encodeURIComponent(getChannelKey(channel))}`;
    return <Card padded={false} className={clsx('channel-row-card recording-channel', `recording-channel--${props.mode}`, props.isSelected && 'is-selected', props.isDragging && 'opacity-45', props.isDropTarget && 'ring-2 ring-[var(--primary)]')} data-channel-key={getChannelKey(channel)} style={props.layoutStyle}>
        <div className="recording-channel-summary">
            <RecordingChannelHeader channel={channel} pendingAction={props.pendingAction} />
            <div className="recording-channel-management"><ChannelActions {...props} detailsId={detailsId} tagControl={<TagManager compact busy={props.isTagLoading} availableTags={props.globalTags} selectedTags={channel.tags || []} onAddTag={tag => props.onAddTag(channel, tag)} onRemoveTag={tag => props.onRemoveTag(channel, tag)} onCreateTag={props.onCreateTag} triggerLabel={t("live.manageTags")} />} /></div>
            <RecordingControls {...props} />
            <RecordingMetrics recording={channel.recording} />
        </div>
        <div className="recording-channel-extra" hidden={!channel.postprocess}>
            {channel.postprocess && <div className="recording-channel-postprocess"><RecordingPostprocess job={channel.postprocess}/></div>}
        </div>
    </Card>;
}

export function RecordingChannelPanel({ channel, id, selected, onClose, layoutStyle }: { channel: Channel; id: string; selected: boolean; onClose: () => void; layoutStyle: CSSProperties }) {
    const { t } = useLanguage();
    return <section id={id} className="recording-detail-panel" hidden={!selected} style={layoutStyle} aria-label={`${channel.channel_name || channel.channel_id} ${t("live.streamDetails")}`}>
        {selected && <>
            <div className="recording-detail-panel-heading"><strong>{channel.channel_name || channel.channel_id}</strong><PlatformBadge platform={channel.platform || 'chzzk'} /><Button onClick={onClose}>{t("live.collapseDetails")}</Button></div>
            <RecordingChannelDetails channel={channel} />
        </>}
    </section>;
}
