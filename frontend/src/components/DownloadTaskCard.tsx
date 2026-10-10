import { memo, useId, useRef, useState } from 'react';
import { ArrowDown, ArrowUp, ChevronDown, FileVideo, FolderOpen, GripVertical, Pause, Play, RotateCw, Square, Trash2 } from 'lucide-react';
import { clsx } from 'clsx';
import { client, type VodTask } from '../api/client';
import { useLanguage } from '../contexts/LanguageContext';
import { downloadState, downloadStateLabels, downloadErrorMessage } from '../utils/downloads';
import { formatBytes, formatDuration } from '../utils/format';
import { Badge, Button, Card } from './ui/primitives';
import { ActionMenu } from './ui/ActionMenu';
import { DownloadTaskHeader } from './DownloadTaskHeader';

export type DownloadAction = 'start' | 'metadata' | 'pause' | 'resume' | 'cancel' | 'retry' | 'inspect' | 'folder' | 'remove' | 'quality';
interface Props {
    task: VodTask; mode: 'grid' | 'list'; retryActive: boolean;
    canMoveUp: boolean; canMoveDown: boolean; manualOrder: boolean;
    onMove: (id: string, direction: number) => void;
    onDropTask: (id: string, targetId: string) => void;
    onAction: (task: VodTask, action: DownloadAction, value?: string) => Promise<void>;
}
const known = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0;
export const DownloadTaskCard = memo(function DownloadTaskCard({ task, mode, retryActive, canMoveUp, canMoveDown, manualOrder, onMove, onDropTask, onAction }: Props) {
    const { t } = useLanguage();
    const [expanded, setExpanded] = useState(false);
    const [pending, setPending] = useState<DownloadAction | null>(null);
    const pendingRef = useRef(false);
    const detailsId = useId();
    const state = downloadState(task);
    const metadata = task.metadata;
    const prepared = task.prepared && task.state === 'idle';
    const canQuality = prepared && ['ready', 'queued'].includes(task.phase ?? '') && !task.started_at;
    const inspection = task.inspection_state ?? (task.warning_message ? 'attention' : 'pending');
    const attention = task.state === 'completed' && ['attention', 'failed'].includes(inspection);
    const inspecting = inspection === 'running';
    const tone = state === 'failed' ? 'danger' : state === 'completed' ? 'ok' : state === 'paused' ? 'warn' : ['downloading', 'processing'].includes(state) ? 'info' : 'neutral';
    const status = state === 'completed' ? downloadStateLabels.completed : state === 'failed' ? task.phase === 'metadata_error' ? '영상 정보 조회 실패' : downloadStateLabels.failed : state === 'cancelled' ? downloadStateLabels.cancelled : task.state === 'cancelling' ? '취소 중' : state === 'queued' && task.phase === 'metadata' ? '영상 정보 확인 중' : state === 'processing' && task.phase === 'merging' ? '병합 중' : state === 'processing' && task.phase === 'verifying' ? '파일 검사 중' : downloadStateLabels[state];
    const percentage = known(task.progress) ? Math.min(100, task.progress).toFixed(1) : null;
    const duration = known(metadata?.duration) && metadata.duration > 0 ? metadata.duration : task.media_duration;
    const act = async (action: DownloadAction, value?: string) => {
        if (pendingRef.current) return;
        pendingRef.current = true; setPending(action);
        try { await onAction(task, action, value); } finally { pendingRef.current = false; setPending(null); }
    };
    const move = (direction: number) => { if (!pendingRef.current) onMove(task.task_id, direction); };
    const statistics = state === 'completed' ? [
        ['파일 크기', known(task.file_size) ? formatBytes(task.file_size) : task.downloaded_bytes > 0 ? formatBytes(task.downloaded_bytes) : '—'],
        ['영상 길이', known(duration) && duration > 0 ? formatDuration(duration) : '—'],
        ['완료 시각', task.completed_at ? new Date(task.completed_at).toLocaleString() : '—'],
    ] : [
        ['다운로드 용량', known(task.downloaded_bytes) ? `${formatBytes(task.downloaded_bytes)}${task.total_bytes > 0 ? ` / ${formatBytes(task.total_bytes)}` : ' / —'}` : '—'],
        ['다운로드 속도', state === 'downloading' && known(task.download_speed) && task.download_speed > 0 ? `${task.download_speed.toFixed(2)} MB/s` : '—'],
        ['남은 시간', state === 'downloading' && known(task.eta_seconds) && task.eta_seconds > 0 ? formatDuration(task.eta_seconds) : '—'],
    ];
    return <Card padded={false} className={`download-row download-task download-task--${mode}`} data-task-id={task.task_id}
        onDragOver={event => { if (manualOrder && event.dataTransfer.types.includes('application/x-phrolova-task')) event.preventDefault(); }}
        onDrop={event => { const id = event.dataTransfer.getData('application/x-phrolova-task'); if (manualOrder && id) { event.preventDefault(); onDropTask(id, task.task_id); } }}>
        <div className="download-task-summary">
            <DownloadTaskHeader task={task} duration={duration} actions={
            <div className="download-task-management" role="group" aria-label={`${t('카드 관리')}: ${task.title}`}>
                <button className="icon-button" onClick={() => setExpanded(value => !value)} aria-expanded={expanded} aria-controls={detailsId} aria-label={`${t(expanded ? '상세 접기' : '상세 보기')}: ${task.title}`} title={t(expanded ? '상세 접기' : '상세 보기')}><ChevronDown className={clsx('size-4', expanded && 'rotate-180')} /></button>
                <button className="icon-button download-drag-handle" draggable={manualOrder} disabled={!manualOrder} onDragStart={event => event.dataTransfer.setData('application/x-phrolova-task', task.task_id)} aria-label={`${t('순서 변경')}: ${task.title}`} title={t(manualOrder ? '드래그하거나 방향키를 눌러 순서 변경' : '직접 정렬에서 순서를 변경할 수 있습니다.')} onKeyDown={event => { const direction = ['ArrowUp', 'ArrowLeft'].includes(event.key) ? -1 : ['ArrowDown', 'ArrowRight'].includes(event.key) ? 1 : 0; if (direction && manualOrder) { event.preventDefault(); if (direction < 0 ? canMoveUp : canMoveDown) move(direction); } }}><GripVertical className="size-4" /></button>
                <ActionMenu className="download-mobile-menu" label={`${t('작업 메뉴')}: ${task.title}`}>{close => <>
                    <button disabled={!canMoveUp} onClick={() => { move(-1); close(); }}><ArrowUp className="size-4" />{t('위로 이동')}</button>
                    <button disabled={!canMoveDown} onClick={() => { move(1); close(); }}><ArrowDown className="size-4" />{t('아래로 이동')}</button>
                    {['completed', 'failed', 'cancelled'].includes(state) && <button disabled={!!pending || inspecting || retryActive} onClick={() => { close(); void act('retry'); }}><RotateCw className="size-4" />{t(retryActive ? '다시 다운로드 중' : '다시 다운로드')}</button>}
                    {(task.state === 'idle' || task.state === 'completed' || task.state === 'error') && <button disabled={!!pending || inspecting} onClick={() => { close(); void act('remove'); }} title={t('영상 파일은 삭제하지 않습니다.')}><Trash2 className="size-4" />{t('목록에서 제거')}</button>}
                    <button onClick={() => { setExpanded(true); close(); }}>{t('오류 및 저장 위치 상세 보기')}</button>
                </>}</ActionMenu>
            </div>
            } />
            <div className="download-task-status" role="status" aria-live="polite">
                <div className="download-status-heading"><Badge tone={tone}>{t(status)}{state === 'downloading' && percentage && ` · ${percentage}%`}</Badge>
                    {!canQuality && task.quality && <span className="download-selected-quality"><span>{t('화질')}</span> {task.quality === 'best' ? t('최고 화질') : task.quality === 'worst' ? t('최저 화질') : task.quality}</span>}
                </div>
                {['downloading', 'processing', 'paused'].includes(state) && <div className="download-progress"><div role="progressbar" aria-label={t('다운로드 진행률')} aria-valuenow={percentage ? Number(percentage) : undefined} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${percentage ?? 0}%` }} /></div><span className="tabular-nums">{percentage ? `${percentage}%` : '—'}</span></div>}
                {state === 'processing' && <span className="text-xs text-ink-muted">{t('다운로드 후 처리를 진행하고 있습니다.')}</span>}
                {task.state === 'completed' && <span className={clsx('text-xs', attention ? 'text-warn' : inspection === 'passed' ? 'text-ok' : 'text-ink-muted')}>{t(inspecting ? '파일 정보를 확인하고 있습니다.' : attention ? '파일 확인 필요' : inspection === 'passed' ? '파일 검사 완료' : '검사 대기')}</span>}
            </div>
            <div className={clsx('download-task-footer', canQuality && 'download-task-footer--ready')}>
            {!canQuality && <dl className="download-task-metrics">{statistics.map(([label, value]) => <div key={label}><dt>{t(label)}</dt><dd>{value}</dd></div>)}</dl>}
            <div className="download-task-controls">
                {canQuality && <div className="download-task-quality"><div className="download-quality-segments" role="group" aria-label={t('다운로드 해상도')}>{metadata?.qualities?.map(option => <button className={clsx('download-quality-option', task.quality === option.value && 'is-selected')} key={option.value} aria-pressed={task.quality === option.value} disabled={!!pending} onClick={() => void act('quality', option.value)}>{option.label}</button>)}</div></div>}
                <div className="download-actions">
                {prepared && task.phase === 'ready' && <Button icon={Play} variant="primary" disabled={!!pending} loading={pending === 'start'} onClick={() => void act('start')}>{t('다운로드 시작')}</Button>}
                {task.phase === 'metadata_error' && <Button icon={RotateCw} disabled={!!pending} onClick={() => void act('metadata')}>{t('정보 다시 조회')}</Button>}
                {state === 'downloading' && task.state !== 'cancelling' && <Button icon={Pause} disabled={!!pending} loading={pending === 'pause'} onClick={() => void act('pause')}>{t('일시정지')}</Button>}
                {state === 'paused' && <Button icon={Play} disabled={!!pending} loading={pending === 'resume'} onClick={() => void act('resume')}>{t('재개')}</Button>}
                {['downloading', 'processing', 'paused'].includes(state) && <Button icon={Square} variant="danger" disabled={!!pending || task.state === 'cancelling'} loading={pending === 'cancel'} onClick={() => void act('cancel')}>{t('취소')}</Button>}
                {state === 'failed' && task.phase !== 'metadata_error' && <Button icon={RotateCw} disabled={!!pending || retryActive} loading={pending === 'retry'} onClick={() => void act('retry')}>{t('다시 시도')}</Button>}
                {task.state === 'completed' && task.output_path && <>
                    <a className="ui-button btn-secondary" href={`${client.defaults.baseURL}/vod/${encodeURIComponent(task.task_id)}/file`} target="_blank" rel="noopener noreferrer"><FileVideo className="size-4" aria-hidden="true" />{t('파일 열기')}</a>
                    <Button icon={FolderOpen} variant="ghost" disabled={!!pending} onClick={() => void act('folder')}>{t('저장 폴더 열기')}</Button>
                    {attention && <Button icon={RotateCw} disabled={!!pending || inspecting} loading={pending === 'inspect'} onClick={() => void act('inspect')}>{t('다시 검사')}</Button>}
                </>}
                </div>
            </div>
            </div>
            {(attention || state === 'failed' || task.download_warning_message) && <p className="download-task-warning text-xs break-words" role="status">{t(attention ? task.inspection_message || '다운로드는 완료되었지만 파일 정보를 확인하지 못했습니다.' : task.download_warning_message || downloadErrorMessage(task))}</p>}
        </div>
        <div id={detailsId} hidden={!expanded} className="download-task-details">
            <dl><div><dt>{t('영상 제목')}</dt><dd>{task.title}</dd></div><div><dt>{t('영상 URL')}</dt><dd><a href={task.url} target="_blank" rel="noreferrer">{task.url}</a></dd></div>
                {metadata?.id && <div><dt>{t(task.url.includes('/clips/') ? '클립 번호' : '영상 번호')}</dt><dd>{metadata.id}</dd></div>}
                {task.output_path && <div><dt>{t('저장 위치')}</dt><dd>{task.output_path}</dd></div>}
                {task.started_at && <div><dt>{t('다운로드 시작 시각')}</dt><dd>{new Date(task.started_at).toLocaleString()}</dd></div>}
                {task.completed_at && <div><dt>{t('다운로드 완료 시각')}</dt><dd>{new Date(task.completed_at).toLocaleString()}</dd></div>}
                {task.cdn_applied && <div><dt>CDN</dt><dd>{task.cdn === 'akamai' ? 'Akamai CDN' : t('기본 CDN')}</dd></div>}
            </dl>
            {metadata?.quality_fallback && <p className="text-xs text-warn">{t('기본 화질이 제공되지 않아 사용 가능한 화질을 선택했습니다.')}</p>}
            {task.error_message && <details className="text-xs text-danger"><summary>{t('오류 세부 정보')}</summary><p>{t(task.error_message)}</p></details>}
            {task.inspection_diagnostics && <details className="text-xs text-ink-muted"><summary>{t('파일 검사 상세 정보')}</summary><pre>{JSON.stringify({ tool: 'FFprobe', code: task.inspection_code, ...task.inspection_diagnostics }, null, 2)}</pre></details>}
            {task.state === 'completed' && task.output_path && !attention && <Button icon={RotateCw} disabled={!!pending || inspecting} onClick={() => void act('inspect')}>{t(inspecting ? '파일 검사 중' : '다시 검사')}</Button>}
        </div>
    </Card>;
});
