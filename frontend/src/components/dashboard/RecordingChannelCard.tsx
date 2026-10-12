import { memo, useRef, type CSSProperties } from 'react';
import { Loader2, Play, Settings2, Square, Users } from 'lucide-react';
import { RecordingPostprocess } from './RecordingPostprocess';
import { clsx } from 'clsx';
import { type Channel } from '../../api/client';
import type { ReorderProps } from '../../hooks/useChannelReorder';
import { getChannelKey } from '../../utils/channel';
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
    const [label, tone] = pendingAction === 'stop' || state === 'stopping' ? ['녹화 중지 중', 'neutral']
        : pendingAction === 'start' ? ['녹화 준비 중', 'neutral']
        : state === 'connecting' ? ['스트림 연결 중', 'info']
        : state === 'reconnecting' ? ['재연결 중', 'warn']
        : channel.recording?.is_recording ? ['녹화 중', 'ok']
        : state === 'error' || error ? [channel.recording?.has_data === false || !channel.recording?.file_size_bytes ? '녹화 시작 실패' : '녹화 오류', 'danger']
        : state === 'completed' ? ['녹화 완료', 'ok']
        : ['녹화 대기', 'neutral'];
    return <span className={`recording-status is-${tone}`} role="status" aria-live="polite"><i aria-hidden="true" />{t(label)}</span>;
}

function RecordingChannelHeader({ channel, pendingAction }: Pick<ChannelItemProps, 'channel' | 'pendingAction'>) {
    const { t } = useLanguage();
    const name = channel.channel_name || channel.channel_id;
    const tags = channel.tags || [];
    return <header className="recording-channel-identity">
        {channel.profile_image_url ? <img src={channel.profile_image_url} alt="" className="recording-avatar" />
            : <span className="recording-avatar recording-avatar-fallback" aria-hidden="true"><Users className="size-4" /></span>}
        <div className="recording-channel-copy">
            <div className="recording-channel-name"><h3 title={name}>{name}</h3><PlatformBadge platform={channel.platform || 'chzzk'} /></div>
            <p className="recording-broadcast-title" title={channel.title || undefined}>{channel.is_live && channel.title ? channel.title : t(channel.broadcast_status === 'checking' ? '방송 상태를 확인하는 중입니다.' : channel.broadcast_status === 'error' ? '방송 상태 확인에 실패했습니다.' : '현재 방송 중이 아닙니다.')}</p>
            {(channel.is_live || tags.length > 0) && <div className="recording-channel-meta">
                {channel.is_live && finite(channel.viewer_count) && <span className="recording-viewers" title={`${t('시청자')}: ${channel.viewer_count.toLocaleString()}`}><Users className="size-3" aria-hidden="true" /><span>{t('시청자')} {channel.viewer_count.toLocaleString()}</span></span>}
                {tags.slice(0, 2).map(tag => <span className="recording-tag" key={tag} title={tag}>{tag}</span>)}
                {tags.length > 2 && <span className="recording-tag-overflow" title={tags.slice(2).join(', ')}>+{tags.length - 2}</span>}
            </div>}
            <div className="recording-channel-statuses" aria-label={t('방송 및 녹화 상태')}>
                <span className={clsx('recording-status', channel.is_live && 'is-info')} role="status"><i aria-hidden="true" />{t(channel.broadcast_status === 'checking' ? '상태 확인 중' : channel.broadcast_status === 'error' ? '상태 확인 실패' : channel.is_live ? '라이브' : '오프라인')}</span>
                {(channel.is_live || channel.recording?.state || (channel.last_error && !channel.last_error.startsWith('감시 오류:')) || pendingAction) && <RecordingStatus channel={channel} pendingAction={pendingAction} />}
            {channel.monitor_status && <span className="recording-status">{t(channel.monitor_status === 'paused' ? '감시 일시 중지' : channel.monitor_status === 'retry_wait' ? '감시 재시도 대기' : '감시 중')}</span>}
            </div>
            {channel.download_hold_reason && <DownloadHoldStatus channel={channel} />}
            {channel.recording?.warning_message && <p className="recording-status-message text-warn" role="status">{channel.recording.warning_message}</p>}
            {channel.monitor_error && <p className="recording-status-message text-danger" role="status">{t('감시 오류')}: {localizePlatformNames(channel.monitor_error)}</p>}
            {channel.last_error && !channel.last_error.startsWith('감시 오류:') && <p className="recording-status-message text-danger" role="status">{localizePlatformNames(channel.last_error)}{channel.retry_at && <span className="text-ink-muted"> · 재연결 대기</span>}</p>}
        </div>
    </header>;
}

function RecordingControls(props: ChannelItemProps) {
    const { channel, pendingAction, isActionLoading, isAutoRecordLoading, onToggleAutoRecord, onStartRecord, onStopRecord, onEditDownloadSettings } = props;
    const { t } = useLanguage();
    const name = channel.channel_name || channel.channel_id;
    const recording = channel.recording?.is_recording || ['connecting', 'reconnecting', 'stopping'].includes(channel.recording?.state || '');
    return <div className="recording-channel-controls">
            <div className="recording-auto-control" aria-busy={!!isAutoRecordLoading}>
                <span>{t('자동 녹화')}</span><Switch checked={channel.auto_record} disabled={isAutoRecordLoading || isActionLoading} onChange={() => onToggleAutoRecord(channel)} label={`${name} ${t('자동 녹화')}`} />
                {isAutoRecordLoading && <span className="recording-saving" role="status"><Loader2 className="size-3 animate-spin" aria-hidden="true" />{t('저장 중')}</span>}
            </div>
        <div className="recording-primary-controls">
            <Button icon={Settings2} variant="ghost" disabled={isActionLoading} onClick={() => onEditDownloadSettings(channel)} title={t('녹화 설정')}>{t('녹화 설정')}</Button>
            {recording ? <Button variant="danger" icon={Square} disabled={isActionLoading || channel.recording?.state === 'stopping'} loading={pendingAction === 'stop'} onClick={() => onStopRecord(channel)}>{t(pendingAction === 'stop' || channel.recording?.state === 'stopping' ? '녹화 중지 중' : '녹화 중지')}</Button>
                : channel.is_live && <Button variant="primary" icon={Play} disabled={isActionLoading} loading={pendingAction === 'start'} onClick={() => onStartRecord(channel)}>{t(pendingAction === 'start' ? '녹화 준비 중' : '녹화 시작')}</Button>}
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
        ['녹화 시간', hasData && finite(value.duration) ? formatDuration(Math.floor(value.duration)) : '—'],
        ['파일 크기', finite(value.size) ? formatBytes(value.size) : '—'],
        ['저장 속도', hasData && finite(value.speed) ? `${value.speed.toFixed(2)} MB/s` : '—'],
        ['비트레이트', hasData && finite(value.bitrate) ? `${(value.bitrate / 1000).toFixed(2)} Mbps` : '—'],
    ];
    return <dl className={clsx('recording-metrics', !active && 'is-inactive')} aria-label={t('녹화 정보')}>
        {metrics.map(([label, text]) => <div key={label}><dt>{t(label)}</dt><dd className={label === '녹화 시간' && active ? 'text-ok' : undefined}>{text}</dd></div>)}
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
            <div><dt>{t('채널')}</dt><dd>{name}</dd></div>
            {channel.title && <div><dt>{t('방송 제목')}</dt><dd>{channel.title}</dd></div>}
            {channel.category && <div><dt>{t('카테고리')}</dt><dd>{channel.category}</dd></div>}
            {url && <div><dt>{t('방송 URL')}</dt><dd><a href={url} target="_blank" rel="noopener noreferrer">{url}</a></dd></div>}
            {recording?.output_path && <div><dt>{t('녹화 파일')}</dt><dd>{recording.output_path}</dd></div>}
            {recording?.start_time && <div><dt>{t('녹화 시작 시각')}</dt><dd>{new Date(recording.start_time).toLocaleString()}</dd></div>}
            {recording?.continuity_source?.selected && <div><dt>{t('수신 경로')}</dt><dd>{t(recording.continuity_source.selected.cdn === 'akamai' ? 'Akamai CDN' : recording.continuity_source.selected.cdn === 'korean' ? 'Naver CDN' : '기본 CDN')} · {recording.continuity_source.selected.mode === 'llhls' ? 'LL-HLS' : 'HLS'}</dd></div>}
            {recording?.continuity_source?.standby && <div><dt>{t('예비 CDN')}</dt><dd>Akamai CDN · {t(({ ready: '준비 완료', absent: '제공되지 않음', unavailable: '연결 확인 실패' })[recording.continuity_source.standby.state])}</dd></div>}
            {channel.recording_quality && <div><dt>{t('녹화 화질')}</dt><dd>{channel.recording_quality === 'best' ? t('최고 화질') : channel.recording_quality}</dd></div>}
            {channel.recording_inspection && <div><dt>{t('파일 검사')}</dt><dd className={channel.recording_inspection.state === 'passed' ? 'text-ok' : 'text-warn'} role="status">{channel.recording_inspection.message}</dd></div>}
            {channel.download_condition && <div><dt>{t('녹화 조건')}</dt><dd>{t(({ all: '모든 방송 녹화', watchalong: '같이보기 방송만 녹화', exclude_watchalong: '같이보기 방송 제외' })[channel.download_condition])}</dd></div>}
            {!!channel.tags?.length && <div><dt>{t('태그')}</dt><dd>{channel.tags.join(', ')}</dd></div>}
        </dl>
        {!!channel.recent_errors?.length && <details className="recording-error"><summary>{t('최근 오류 이력')}</summary>{channel.recent_errors.slice().reverse().map((error,index)=><div key={`${error.timestamp}-${index}`} className="mt-2"><p className="text-ink-muted">{new Date(error.timestamp).toLocaleString()} · {error.kind === 'monitor' ? t('감시') : t('녹화')}</p><p>{error.message}</p>{error.detail && <pre className="whitespace-pre-wrap break-words">{error.detail}</pre>}</div>)}</details>}
        {channel.last_error && <details className="recording-error"><summary>{t('최근 녹화 오류')}</summary><p>{localizePlatformNames(channel.last_error)}</p>{channel.error_detail && <pre className="whitespace-pre-wrap break-words text-xs">{localizePlatformNames(channel.error_detail)}</pre>}</details>}
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
            <div className="recording-channel-management"><ChannelActions {...props} detailsId={detailsId} tagControl={<TagManager compact busy={props.isTagLoading} availableTags={props.globalTags} selectedTags={channel.tags || []} onAddTag={tag => props.onAddTag(channel, tag)} onRemoveTag={tag => props.onRemoveTag(channel, tag)} onCreateTag={props.onCreateTag} triggerLabel={t('태그 관리')} />} /></div>
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
    return <section id={id} className="recording-detail-panel" hidden={!selected} style={layoutStyle} aria-label={`${channel.channel_name || channel.channel_id} ${t('방송 상세')}`}>
        {selected && <>
            <div className="recording-detail-panel-heading"><strong>{channel.channel_name || channel.channel_id}</strong><PlatformBadge platform={channel.platform || 'chzzk'} /><Button onClick={onClose}>{t('상세 접기')}</Button></div>
            <RecordingChannelDetails channel={channel} />
        </>}
    </section>;
}
