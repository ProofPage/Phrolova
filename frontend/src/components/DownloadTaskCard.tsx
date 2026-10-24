import { getActiveLocale, formatNumber } from "../i18n";
import { localizedStatus } from '../utils/error';
import { translate } from "../i18n";
import { memo, useId, useRef, useState, type ReactNode } from 'react';
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
    const status = state === 'completed' ? downloadStateLabels.completed : state === 'failed' ? task.phase === 'metadata_error' ? "download.couldNotFetchVideoInformation" : downloadStateLabels.failed : state === 'cancelled' ? downloadStateLabels.cancelled : task.state === 'cancelling' ? "download.cancelling" : state === 'queued' && task.phase === 'metadata' ? "download.checkingVideoInformation" : state === 'processing' && task.phase === 'merging' ? "download.merging" : state === 'processing' && task.phase === 'verifying' ? "live.verifying" : downloadStateLabels[state];
    const percentage = known(task.progress) ? Math.min(100, task.progress).toFixed(1) : null;
    const duration = known(metadata?.duration) && metadata.duration > 0 ? metadata.duration : task.media_duration;
    const act = async (action: DownloadAction, value?: string) => {
        if (pendingRef.current) return;
        pendingRef.current = true; setPending(action);
        try { await onAction(task, action, value); } finally { pendingRef.current = false; setPending(null); }
    };
    const move = (direction: number) => { if (!pendingRef.current) onMove(task.task_id, direction); };
    const statistics: [string, ReactNode][] = state === 'completed' ? [
        ["live.fileSize", known(task.file_size) ? formatBytes(task.file_size) : task.downloaded_bytes > 0 ? formatBytes(task.downloaded_bytes) : '—'],
        ["download.videoDuration", known(duration) && duration > 0 ? formatDuration(duration) : '—'],
        ["download.completedAt", task.completed_at ? <time dateTime={task.completed_at} className="download-completed-at"><span>{new Date(task.completed_at).toLocaleDateString(getActiveLocale())}</span><span>{new Date(task.completed_at).toLocaleTimeString(getActiveLocale())}</span></time> : '—'],
    ] : [
        ["download.downloadedSize", known(task.downloaded_bytes) ? `${formatBytes(task.downloaded_bytes)}${task.total_bytes > 0 ? ` / ${formatBytes(task.total_bytes)}` : ' / —'}` : '—'],
        ["download.downloadSpeed", state === 'downloading' && known(task.download_speed) && task.download_speed > 0 ? `${formatNumber(task.download_speed, {minimumFractionDigits:2, maximumFractionDigits:2})} MB/s` : '—'],
        ["download.remaining", state === 'downloading' && known(task.eta_seconds) && task.eta_seconds > 0 ? formatDuration(task.eta_seconds) : '—'],
    ];
    return <Card padded={false} className={`download-row download-task download-task--${mode}`} data-task-id={task.task_id}
        onDragOver={event => { if (manualOrder && event.dataTransfer.types.includes('application/x-phrolova-task')) event.preventDefault(); }}
        onDrop={event => { const id = event.dataTransfer.getData('application/x-phrolova-task'); if (manualOrder && id) { event.preventDefault(); onDropTask(id, task.task_id); } }}>
        <div className="download-task-summary">
            <DownloadTaskHeader task={task} duration={duration} actions={
            <div className="download-task-management" role="group" aria-label={`${t("download.manageCard")}: ${task.title}`}>
                <button className="icon-button" onClick={() => setExpanded(value => !value)} aria-expanded={expanded} aria-controls={detailsId} aria-label={`${t(expanded ? translate("live.collapseDetails") : translate("live.details"))}: ${task.title}`} title={t(expanded ? translate("live.collapseDetails") : translate("live.details"))}><ChevronDown className={clsx('size-4', expanded && 'rotate-180')} /></button>
                <button className="icon-button download-drag-handle" draggable={manualOrder} disabled={!manualOrder} onDragStart={event => event.dataTransfer.setData('application/x-phrolova-task', task.task_id)} aria-label={`${t("live.reorder")}: ${task.title}`} title={t(manualOrder ? translate("download.dragOrUseArrowKeysToReorder") : translate("download.reorderingIsAvailableInManualSortMode"))} onKeyDown={event => { const direction = ['ArrowUp', 'ArrowLeft'].includes(event.key) ? -1 : ['ArrowDown', 'ArrowRight'].includes(event.key) ? 1 : 0; if (direction && manualOrder) { event.preventDefault(); if (direction < 0 ? canMoveUp : canMoveDown) move(direction); } }}><GripVertical className="size-4" /></button>
                <ActionMenu className="download-mobile-menu" label={`${t("download.taskMenu")}: ${task.title}`}>{close => <>
                    <button disabled={!canMoveUp} onClick={() => { move(-1); close(); }}><ArrowUp className="size-4" />{t("live.moveUp")}</button>
                    <button disabled={!canMoveDown} onClick={() => { move(1); close(); }}><ArrowDown className="size-4" />{t("live.moveDown")}</button>
                    {['completed', 'failed', 'cancelled'].includes(state) && <button disabled={!!pending || inspecting || retryActive} onClick={() => { close(); void act('retry'); }}><RotateCw className="size-4" />{t(retryActive ? translate("download.downloadingAgain") : translate("download.retryDownload"))}</button>}
                    {(task.state === 'idle' || task.state === 'completed' || task.state === 'error') && <button disabled={!!pending || inspecting} onClick={() => { close(); void act('remove'); }} title={t("download.videoFilesAreKept")}><Trash2 className="size-4" />{t("download.removeHistory")}</button>}
                    <button onClick={() => { setExpanded(true); close(); }}>{t("download.showErrorAndSaveLocationDetails")}</button>
                </>}</ActionMenu>
            </div>
            } />
            <div className="download-task-status" role="status" aria-live="polite">
                <div className="download-status-heading"><Badge tone={tone}>{t(status)}</Badge>
                    {!canQuality && task.quality && <span className="download-selected-quality">{task.quality === 'best' ? t("live.highestQuality") : task.quality === 'worst' ? t("download.lowestQuality") : task.quality}</span>}
                </div>
                {['downloading', 'processing', 'paused'].includes(state) && <div className="download-progress"><div role="progressbar" aria-label={t("download.downloadProgress")} aria-valuenow={percentage ? Number(percentage) : undefined} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${percentage ?? 0}%` }} /></div><span className="tabular-nums">{percentage ? `${formatNumber(Number(percentage), {minimumFractionDigits:1, maximumFractionDigits:1})}%` : '—'}</span></div>}
                {state === 'processing' && <span className="text-xs text-ink-muted">{t("download.processingTheDownloadedVideo")}</span>}
            </div>
            <div className={clsx('download-task-footer', canQuality && 'download-task-footer--ready')}>
            {!canQuality && <dl className="download-task-metrics">{statistics.map(([label, value]) => <div key={label}><dt>{t(label)}</dt><dd>{value}</dd></div>)}</dl>}
            {task.state === 'completed' && inspection !== 'passed' && <div className="download-file-verification"><span className={clsx('text-xs', attention ? 'text-warn' : 'text-ink-muted')}>{t(inspecting ? translate("download.checkingFileInformation") : attention ? translate("live.fileNeedsAttention") : translate("download.inspectionPending"))}</span>{attention && <p className="download-task-warning text-xs break-words" role="status">{attention ? localizedStatus(task.inspection_message, 'download.downloadCompletedButFileInformationCouldNotBeVerified') : localizedStatus(task.download_warning_message, state === 'failed' ? downloadErrorMessage(task) : 'download.downloadWarning')}</p>}</div>}
            {(state === 'failed' || task.download_warning_message) && <p className="download-task-warning text-xs break-words" role="status">{attention ? localizedStatus(task.inspection_message, 'download.downloadCompletedButFileInformationCouldNotBeVerified') : localizedStatus(task.download_warning_message, state === 'failed' ? downloadErrorMessage(task) : 'download.downloadWarning')}</p>}
            <div className="download-task-controls">
                {canQuality && <div className="download-task-quality"><div className="download-quality-segments" role="group" aria-label={t("download.downloadResolution")}>{metadata?.qualities?.map(option => <Button className={clsx('download-quality-option', task.quality === option.value && 'is-selected')} key={option.value} aria-pressed={task.quality === option.value} disabled={!!pending} onClick={() => void act('quality', option.value)}>{t(option.label)}</Button>)}</div></div>}
                <div className="download-actions">
                {prepared && task.phase === 'ready' && <Button icon={Play} variant="primary" disabled={!!pending} loading={pending === 'start'} onClick={() => void act('start')}>{t("download.startDownload")}</Button>}
                {task.phase === 'metadata_error' && <Button icon={RotateCw} disabled={!!pending} onClick={() => void act('metadata')}>{t("download.retryMetadata")}</Button>}
                {state === 'downloading' && task.state !== 'cancelling' && <Button icon={Pause} disabled={!!pending} loading={pending === 'pause'} onClick={() => void act('pause')}>{t("download.paused")}</Button>}
                {state === 'paused' && <Button icon={Play} disabled={!!pending} loading={pending === 'resume'} onClick={() => void act('resume')}>{t("download.resume")}</Button>}
                {['downloading', 'processing', 'paused'].includes(state) && <Button icon={Square} variant="danger" disabled={!!pending || task.state === 'cancelling'} loading={pending === 'cancel'} onClick={() => void act('cancel')}>{t("common.cancel")}</Button>}
                {state === 'failed' && task.phase !== 'metadata_error' && <Button icon={RotateCw} disabled={!!pending || retryActive} loading={pending === 'retry'} onClick={() => void act('retry')}>{t("live.tryAgain")}</Button>}
                {task.state === 'completed' && task.output_path && <>
                    <a className="ui-button btn-secondary" href={`${client.defaults.baseURL}/vod/${encodeURIComponent(task.task_id)}/file`} target="_blank" rel="noopener noreferrer"><FileVideo className="size-4" aria-hidden="true" />{t("live.openFile")}</a>
                    <Button icon={FolderOpen} disabled={!!pending} onClick={() => void act('folder')}>{t("live.openSavedFolder")}</Button>
                    {attention && <Button icon={RotateCw} disabled={!!pending || inspecting} loading={pending === 'inspect'} onClick={() => void act('inspect')}>{t("live.inspectAgain")}</Button>}
                </>}
                </div>
            </div>
            </div>
        </div>
        <div id={detailsId} hidden={!expanded} className="download-task-details">
            <dl><div><dt>{t("download.videoTitle")}</dt><dd>{task.title}</dd></div><div><dt>{t("download.videoURL")}</dt><dd><a href={task.url} target="_blank" rel="noreferrer">{task.url}</a></dd></div>
                {metadata?.id && <div><dt>{t(task.url.includes('/clips/') ? translate("download.clipID") : translate("download.videoID"))}</dt><dd>{metadata.id}</dd></div>}
                {task.output_path && <div><dt>{t("download.storageLocation")}</dt><dd>{task.output_path}</dd></div>}
                {task.started_at && <div><dt>{t("download.downloadStartedAt")}</dt><dd>{new Date(task.started_at).toLocaleString(getActiveLocale())}</dd></div>}
                {task.completed_at && <div><dt>{t("download.completedAtInDownloadTaskCard")}</dt><dd>{<time dateTime={task.completed_at} className="download-completed-at"><span>{new Date(task.completed_at).toLocaleDateString(getActiveLocale())}</span><span>{new Date(task.completed_at).toLocaleTimeString(getActiveLocale())}</span></time>}</dd></div>}
                {task.cdn_applied && <div><dt>CDN</dt><dd>{task.cdn === 'akamai' ? 'Akamai CDN' : 'Naver CDN'}</dd></div>}
            </dl>
            {metadata?.quality_fallback && <p className="text-xs text-warn">{t("download.defaultQualityIsUnavailableAnAvailableQualityWasSelected")}</p>}
            {(task.error_message || task.download_warning_message) && <details className="text-xs text-danger"><summary>{t("download.errorDetails")}</summary><p>{task.error_message || task.download_warning_message}</p></details>}
            {task.inspection_diagnostics && <details className="text-xs text-ink-muted"><summary>{t("download.fileInspectionDetails")}</summary><pre>{JSON.stringify({ tool: 'FFprobe', code: task.inspection_code, ...task.inspection_diagnostics }, null, 2)}</pre></details>}
            {task.state === 'completed' && task.output_path && !attention && <Button icon={RotateCw} disabled={!!pending || inspecting} onClick={() => void act('inspect')}>{t(inspecting ? translate("live.verifying") : translate("live.inspectAgain"))}</Button>}
        </div>
    </Card>;
});
