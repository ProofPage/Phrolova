import { memo, useEffect, useId, useRef, useState } from 'react';
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
    const [label, tone] = pendingAction === 'stop' || state === 'stopping' ? ['녹화 중지 중', 'neutral']
        : pendingAction === 'start' ? ['녹화 준비 중', 'neutral']
        : channel.recording?.is_recording ? ['녹화 중', 'ok']
        : state === 'error' || channel.last_error ? ['녹화 오류', 'danger']
        : state === 'completed' ? ['녹화 완료', 'ok']
        : channel.is_live ? ['녹화 대기', 'neutral'] : ['오프라인', 'neutral'];
    return <span className={`recording-status is-${tone}`} role="status" aria-live="polite"><i aria-hidden="true" />{t(label)}</span>;
}

function RecordingChannelHeader({ channel }: { channel: Channel }) {
    const { t } = useLanguage();
    const name = channel.channel_name || channel.channel_id;
    const tags = channel.tags || [];
    return <header className="recording-channel-identity">
        {channel.profile_image_url ? <img src={channel.profile_image_url} alt="" className="recording-avatar" />
            : <span className="recording-avatar recording-avatar-fallback" aria-hidden="true"><Users className="size-4" /></span>}
        <div className="recording-channel-copy">
            <div className="recording-channel-name"><h3 title={name}>{name}</h3><PlatformBadge platform={channel.platform || 'chzzk'} /></div>
            <p className="recording-broadcast-title" title={channel.title || undefined}>{channel.is_live && channel.title ? channel.title : t('현재 방송 중이 아닙니다.')}</p>
            {(channel.is_live || tags.length > 0) && <div className="recording-channel-meta">
                {channel.is_live && finite(channel.viewer_count) && <span className="recording-viewers" title={`${t('시청자')}: ${channel.viewer_count.toLocaleString()}`}><Users className="size-3" aria-hidden="true" /><span>{t('시청자')} {channel.viewer_count.toLocaleString()}</span></span>}
                {tags.slice(0, 2).map(tag => <span className="recording-tag" key={tag} title={tag}>{tag}</span>)}
                {tags.length > 2 && <span className="recording-tag-overflow" title={tags.slice(2).join(', ')}>+{tags.length - 2}</span>}
            </div>}
        </div>
    </header>;
}

function RecordingControls(props: ChannelItemProps) {
    const { channel, pendingAction, isActionLoading, isAutoRecordLoading, onToggleAutoRecord, onStartRecord, onStopRecord, onEditDownloadSettings } = props;
    const { t } = useLanguage();
    const name = channel.channel_name || channel.channel_id;
    const recording = channel.recording?.is_recording || channel.recording?.state === 'stopping';
    return <div className="recording-channel-controls">
        <div className="recording-control-state"><RecordingStatus channel={channel} pendingAction={pendingAction} />
            <div className="recording-auto-control" aria-busy={!!isAutoRecordLoading}>
                <span>{t('자동 녹화')}</span><Switch checked={channel.auto_record} disabled={isAutoRecordLoading || isActionLoading} onChange={() => onToggleAutoRecord(channel)} label={`${name} ${t('자동 녹화')}`} />
                {isAutoRecordLoading && <span className="recording-saving" role="status"><Loader2 className="size-3 animate-spin" aria-hidden="true" />{t('저장 중')}</span>}
            </div>
        </div>
        <div className="recording-primary-controls">
            <Button icon={Settings2} variant="ghost" disabled={isActionLoading} onClick={() => onEditDownloadSettings(channel)} title={t('녹화 설정')}>{t('녹화 설정')}</Button>
            {recording ? <Button variant="danger" icon={Square} disabled={isActionLoading || channel.recording?.state === 'stopping'} loading={pendingAction === 'stop'} onClick={() => onStopRecord(channel)}>{t(pendingAction === 'stop' || channel.recording?.state === 'stopping' ? '녹화 중지 중' : '녹화 중지')}</Button>
                : channel.is_live && <Button variant="primary" icon={Play} disabled={isActionLoading} loading={pendingAction === 'start'} onClick={() => onStartRecord(channel)}>{t(pendingAction === 'start' ? '녹화 준비 중' : '녹화 시작')}</Button>}
        </div>
    </div>;
}

type Measurements = { duration?: number; size?: number; speed?: number; bitrate?: number };

/** Only this child ticks. Server duration is authoritative, independent of time zones. */
const RecordingMetrics = memo(function RecordingMetrics({ recording }: { recording: Channel['recording'] }) {
    const { t } = useLanguage();
    const [, tick] = useState(0);
    const last = useRef<Measurements>({});
    const session = useRef<string | null | undefined>(undefined);
    const wasActive = useRef(false);
    const clock = useRef({ seconds: undefined as number | undefined, received: performance.now() });
    const active = recording?.is_recording === true;
    if (active && (!wasActive.current || session.current !== recording?.start_time)) {
        last.current = {}; clock.current.seconds = undefined;
    }
    wasActive.current = active; session.current = recording?.start_time;
    if (finite(recording?.duration_seconds) && recording.duration_seconds !== clock.current.seconds) {
        clock.current = { seconds: recording.duration_seconds, received: performance.now() };
    }
    if (finite(recording?.duration_seconds)) last.current.duration = active
        ? recording.duration_seconds + Math.max(0, (performance.now() - clock.current.received) / 1000) : recording.duration_seconds;
    if (finite(recording?.file_size_bytes)) last.current.size = recording.file_size_bytes;
    if (finite(recording?.download_speed)) last.current.speed = recording.download_speed;
    if (finite(recording?.bitrate)) last.current.bitrate = recording.bitrate;
    useEffect(() => {
        if (!active || !finite(recording?.duration_seconds)) return;
        const timer = setInterval(() => tick(value => value + 1), 1000);
        return () => clearInterval(timer);
    }, [active, recording?.duration_seconds]);
    const value = last.current;
    const metrics = [
        ['녹화 시간', finite(value.duration) ? formatDuration(Math.floor(value.duration)) : '—'],
        ['파일 크기', finite(value.size) ? formatBytes(value.size) : '—'],
        ['저장 속도', finite(value.speed) ? `${value.speed.toFixed(2)} MB/s` : '—'],
        ['비트레이트', finite(value.bitrate) ? `${(value.bitrate / 1000).toFixed(2)} Mbps` : '—'],
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
        <div className="recording-details-copy">
        <dl className="recording-details-fields">
            <div><dt>{t('채널')}</dt><dd>{name}</dd></div>
            {channel.title && <div><dt>{t('방송 제목')}</dt><dd>{channel.title}</dd></div>}
            {channel.category && <div><dt>{t('카테고리')}</dt><dd>{channel.category}</dd></div>}
            {url && <div><dt>{t('방송 URL')}</dt><dd><a href={url} target="_blank" rel="noopener noreferrer">{url}</a></dd></div>}
            {recording?.output_path && <div><dt>{t('녹화 파일')}</dt><dd>{recording.output_path}</dd></div>}
            {recording?.start_time && <div><dt>{t('녹화 시작 시각')}</dt><dd>{new Date(recording.start_time).toLocaleString()}</dd></div>}
            {channel.recording_quality && <div><dt>{t('녹화 화질')}</dt><dd>{channel.recording_quality === 'best' ? t('최고 화질') : channel.recording_quality}</dd></div>}
            {channel.recording_inspection && <div><dt>{t('파일 검사')}</dt><dd className={channel.recording_inspection.state === 'passed' ? 'text-ok' : 'text-warn'} role="status">{channel.recording_inspection.message}</dd></div>}
            {channel.download_condition && <div><dt>{t('녹화 조건')}</dt><dd>{t(({ all: '모든 방송 녹화', watchalong: '같이보기 방송만 녹화', exclude_watchalong: '같이보기 방송 제외' })[channel.download_condition])}</dd></div>}
            {!!channel.tags?.length && <div><dt>{t('태그')}</dt><dd>{channel.tags.join(', ')}</dd></div>}
        </dl>
        {channel.last_error && <details className="recording-error"><summary>{t('최근 녹화 오류')}</summary><p>{localizePlatformNames(channel.last_error)}</p></details>}
        </div>
        <LivePreview channelKey={getChannelKey(channel)} isLive={channel.is_live} name={name} poster={channel.thumbnail_url} />
    </div>;
}

export function RecordingChannelCard(props: ChannelItemProps & { mode: 'grid' | 'list' }) {
    const { channel } = props;
    const { t } = useLanguage();
    const detailsId = useId();
    return <Card padded={false} className={clsx('channel-row-card recording-channel', `recording-channel--${props.mode}`, props.isSelected && 'is-selected', props.isDragging && 'opacity-45', props.isDropTarget && 'ring-2 ring-[var(--primary)]')} data-channel-key={getChannelKey(channel)}>
        <div className="recording-channel-summary">
            <RecordingChannelHeader channel={channel} />
            <div className="recording-channel-management"><ChannelActions {...props} detailsId={detailsId} tagControl={<TagManager compact busy={props.isTagLoading} availableTags={props.globalTags} selectedTags={channel.tags || []} onAddTag={tag => props.onAddTag(channel, tag)} onRemoveTag={tag => props.onRemoveTag(channel, tag)} onCreateTag={props.onCreateTag} triggerLabel={t('태그 관리')} />} /></div>
            <RecordingControls {...props} />
            <RecordingMetrics recording={channel.recording} />
        </div>
        {channel.download_hold_reason && <div className="recording-channel-notices"><DownloadHoldStatus channel={channel} /></div>}
        {channel.postprocess && <div className="px-3 pb-3"><RecordingPostprocess job={channel.postprocess}/></div>}
        <div id={detailsId} className="recording-detail-disclosure" hidden={!props.isSelected}>{props.isSelected && <RecordingChannelDetails channel={channel} />}</div>
    </Card>;
}
