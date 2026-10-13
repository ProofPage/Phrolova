import { translate } from "../i18n";
import { useCallback, useEffect, useRef, useState } from 'react';
import { Download, FileVideo, LayoutGrid, List, Play, RotateCw, Trash2, Loader2, AlertCircle, CheckCircle, CircleHelp } from 'lucide-react';
import { api, type VodTask } from '../api/client';
import { useVod } from '../contexts/VodContext';
import { useLanguage } from '../contexts/LanguageContext';
import { useConfirm } from '../components/ui/ConfirmModal';
import { useToast } from '../components/ui/Toast';
import { Button, EmptyState, LoadingState, PageHeader, Select } from '../components/ui/primitives';
import { DownloadInput } from '../components/DownloadInput';
import { DownloadTaskCard, type DownloadAction } from '../components/DownloadTaskCard';
import { downloadState } from '../utils/downloads';
import { getErrorMessage } from '../utils/error';
import { clsx } from 'clsx';
import '../components/downloads.css';

export default function VodDownload() {
    const { t } = useLanguage();
    const { loading: tasksLoading, loadError, tasks, imports, refreshTasks, cancelTask, pauseTask, resumeTask, retryTask, clearCompleted, openFileLocation } = useVod();
    const toast = useToast(); const confirm = useConfirm();
    const [taskFilter, setTaskFilter] = useState('all');
    const [visibleCount, setVisibleCount] = useState(50);
    const [mode, setMode] = useState<'grid' | 'list'>(() => localStorage.getItem('downloadViewMode') === 'grid' ? 'grid' : 'list');
    const [sort, setSort] = useState('manual');
    const reorderBusyRef = useRef(false);
    const [reordering, setReordering] = useState(false);
    const [clearing, setClearing] = useState(false);
    const clearingRef = useRef(false);
    const [batchBusy, setBatchBusy] = useState(false);
    const batchRef = useRef(false);
    const [importActionId, setImportActionId] = useState<string | null>(null);
    const clearableTaskCount = tasks.filter(task => task.state === 'completed').length;
    const counts = { queued: 0, downloading: 0, processing: 0, paused: 0, completed: 0, failed: 0, cancelled: 0 };
    tasks.forEach(task => counts[downloadState(task)]++);
    const ready = tasks.filter(task => task.prepared && task.state === 'idle' && task.phase === 'ready');
    const orderedTasks = sort === 'manual' ? tasks : [...tasks].sort((a,b) => {
        const delta = (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0); return sort === 'newest' ? delta : -delta;
    });
    const filteredTasks = orderedTasks.filter(task => taskFilter === 'all' || (taskFilter === 'downloading' ? ['downloading', 'processing'].includes(downloadState(task)) : downloadState(task) === taskFilter));
    const visibleTasks = filteredTasks.slice(0, visibleCount);
    useEffect(() => { localStorage.setItem('downloadViewMode', mode); }, [mode]);
    const handleCancel = async (taskId: string, title: string) => {
        const ok = await confirm({
            title: t("download.cancelThisDownload"),
            message: t("download.cancelTheDownloadTitle", {title}),
            confirmText: t("download.cancelDownload"),
            variant: "danger",
        });
        if (!ok) return;
        try {
            await cancelTask(taskId);
            toast.success(t("download.downloadCancellationRequested"));
        } catch (err: unknown) {
            toast.error(getErrorMessage(err, t("download.couldNotCancelTheDownload")));
        }
    };

    const handleRetry = async (taskId: string, title: string) => {
        const ok = await confirm({
            title: t("download.retryThisDownload"),
            message: t("download.downloadTitleAgain", {title}),
            confirmText: t("download.retryDownload"),
        });
        if (!ok) return;
        try {
            await retryTask(taskId);
            toast.success(t("download.downloadRestarted"));
        } catch (err: unknown) {
            toast.error(getErrorMessage(err, t("download.couldNotRestartTheDownload")));
        }
    };

    const handleTaskAction = async (action: () => Promise<void>, success: string, fallback: string) => {
        try {
            await action();
            toast.success(t(success));
        } catch (err: unknown) {
            toast.error(getErrorMessage(err, t(fallback)));
        }
    };

    const handleClearCompleted = async () => {
        if (clearingRef.current) return; clearingRef.current = true; setClearing(true);
        const ok = await confirm({
            title: t("download.clearTheDownloadList"),
            message: t("download.clearCompletedHistoryOnlySavedVideoFilesAreKept"),
            confirmText: t("download.clearList"),
            variant: "danger",
        });
        if (!ok) { clearingRef.current = false; setClearing(false); return; }

        try {
            const result = await clearCompleted(true);
            toast.success("download.removedCountItemsFromTheDownloadList", {count: result.deleted_count});
        } catch (err: unknown) {
            toast.error(getErrorMessage(err, t("download.couldNotClearTheDownloadList")));
        } finally { clearingRef.current = false; setClearing(false); }
    };

    const reorderTask = async (taskId: string, dropIndex: number, visibleOnly = false) => {
        if (reorderBusyRef.current) return;
        const sourceIndex = tasks.findIndex(task => task.task_id === taskId);
        if (sourceIndex < 0 || dropIndex < 0 || dropIndex >= tasks.length || sourceIndex === dropIndex) return;
        reorderBusyRef.current = true;
        setReordering(true);
        const next = [...tasks];
        if (visibleOnly) {
            // 필터로 숨긴 항목의 위치는 유지하고 보이는 이웃끼리만 교환한다.
            [next[sourceIndex], next[dropIndex]] = [next[dropIndex], next[sourceIndex]];
        } else {
            const [task] = next.splice(sourceIndex, 1);
            next.splice(dropIndex, 0, task);
        }
        try {
            await api.reorderVodTasks(next.map(item => item.task_id));
            await refreshTasks();
        } catch {
            toast.error(t("download.couldNotChangeTheTaskOrder"));
        } finally {
            reorderBusyRef.current = false;
            setReordering(false);
        }
    };

    const dispatch = async (task: VodTask, action: DownloadAction, value?: string) => {
        if (action === 'cancel') return handleCancel(task.task_id, task.title);
        if (action === 'retry') return handleRetry(task.task_id, task.title);
        if (action === 'folder') return openFileLocation(task.task_id);
        if (action === 'remove' && !await confirm({ title: t("download.removeFromTheList"), message: t("download.onlyDownloadHistoryIsRemovedSavedVideoFilesAreKept"), confirmText: t("download.removeHistory"), variant: 'danger' })) return;
        await handleTaskAction(async () => {
            switch (action) {
                case 'start': await api.startPreparedVod(task.task_id); break;
                case 'metadata': await api.retryVodMetadata(task.task_id); break;
                case 'quality': if (value) await api.updateVodQuality(task.task_id, value); break;
                case 'inspect': await api.inspectVodFile(task.task_id); break;
                case 'remove': await api.removeVodTask(task.task_id); break;
                case 'pause': await pauseTask(task.task_id); break;
                case 'resume': await resumeTask(task.task_id); break;
            }
            await refreshTasks();
        }, "download.requestApplied", "download.theRequestFailed");
    };
    const dispatchRef = useRef(dispatch); dispatchRef.current = dispatch;
    const moveRef = useRef((id: string, direction: number) => { const index = visibleTasks.findIndex(task => task.task_id === id); const target = visibleTasks[index + direction]; if (target && sort === 'manual') void reorderTask(id, tasks.indexOf(target), true); });
    moveRef.current = (id, direction) => { const index = visibleTasks.findIndex(task => task.task_id === id); const target = visibleTasks[index + direction]; if (target && sort === 'manual') void reorderTask(id, tasks.indexOf(target), true); };
    const dropRef = useRef((id: string, targetId: string) => { const index = tasks.findIndex(task => task.task_id === targetId); if (sort === 'manual') void reorderTask(id, index, taskFilter !== 'all'); });
    dropRef.current = (id, targetId) => { const index = tasks.findIndex(task => task.task_id === targetId); if (sort === 'manual') void reorderTask(id, index, taskFilter !== 'all'); };
    const onAction = useCallback((task: VodTask, action: DownloadAction, value?: string) => dispatchRef.current(task, action, value), []);
    const onMove = useCallback((id: string, direction: number) => moveRef.current(id, direction), []);
    const onDropTask = useCallback((id: string, targetId: string) => dropRef.current(id, targetId), []);
    const startAll = async () => {
        if (batchRef.current) return; batchRef.current = true; setBatchBusy(true);
        try { const result = await api.startPreparedVods(ready.map(task => task.task_id)); const errors = result.results.filter(item => item.error); if (errors.length) toast.error(errors.map(item => item.error).join('\n')); await refreshTasks(); }
        catch (error) { toast.error(getErrorMessage(error, t("download.theRequestFailed"))); }
        finally { batchRef.current = false; setBatchBusy(false); }
    };
    return <div className="product-page downloads-page space-y-4">
        <PageHeader icon={Download} title={t("download.title")} variant="plain" meta={<div className="download-overview" aria-label={t("download.allTasks")}>
            {[[t("download.active"), counts.downloading + counts.processing], [t("settings.waiting"), counts.queued], [t("live.completed"), counts.completed], [t("live.failed"), counts.failed]].map(([label, count]) => <span key={label}>{label} <strong className="tabular-nums">{count}</strong></span>)}
        </div>} actions={<DownloadInput tasks={tasks} />} actionsPlacement="below" />
        {loadError && <div role="status" className="download-load-error"><span>{t("download.unableToLoadDownloadsTryAgainShortly")}</span><Button icon={RotateCw} onClick={() => void refreshTasks()}>{t("live.tryAgain")}</Button></div>}
            {imports.map((job) => {
                const running = job.state === "queued" || job.state === "collecting";
                const label = job.state === "queued" ? translate("download.waitingToLoadChannelVideos")
                    : job.state === "collecting" ? translate("download.loadingChannelVideos")
                    : job.state === "completed" ? translate("download.channelVideoListLoaded")
                    : job.state === "cancelled" ? translate("download.stoppedLoadingChannelVideos") : translate("download.couldNotLoadChannelVideos");
                return (
                    <div key={job.id} role="status" className="download-import rounded-[var(--radius-card)] border border-line bg-surface-2 p-4 flex flex-wrap sm:flex-nowrap items-start gap-3 [overflow-wrap:anywhere]">
                        {running ? <Loader2 className="w-5 h-5 animate-spin text-[var(--primary)] shrink-0 mt-0.5" />
                            : job.state === "error" ? <AlertCircle className="w-5 h-5 text-danger shrink-0 mt-0.5" />
                            : <CheckCircle className="w-5 h-5 text-[var(--primary)] shrink-0 mt-0.5" />}
                        <div className="min-w-0 flex-1 space-y-1">
                            <p className="text-sm font-semibold text-ink">{t(label)}</p>
                            <p className="text-xs text-ink-muted break-all">{job.url}</p>
                            <p className="text-xs text-ink-muted">{t("download.videosAdded")}: {job.added_count} · {t("download.videosAlreadyInTheQueue")}: {job.skipped_count}</p>
                            {running && <p className="text-xs text-ink-muted">{t("download.downloadsStartAsVideosAreFoundStoppingTheLookupKeepsVideosAlreadyAdded")}</p>}
                            {job.error && <details className="text-xs text-danger">
                                <summary className="cursor-pointer">{t("download.errorDetails")}</summary>
                                <p className="mt-1 break-words">{job.error}</p>
                            </details>}
                        </div>
                        <Button className="max-sm:w-full" loading={importActionId === job.id} disabled={importActionId !== null} onClick={async () => {
                            if (importActionId !== null) return;
                            setImportActionId(job.id);
                            try { await api.cancelVodImport(job.id); await refreshTasks(); }
                            catch (err) { toast.error(getErrorMessage(err, t("download.theRequestFailed"))); }
                            finally { setImportActionId(null); }
                        }}>{t(running ? translate("download.stopLoading") : translate("common.close"))}</Button>
                    </div>
                );
            })}

        <section className="download-list-section space-y-3" aria-label={t("download.downloadQueue")}>
            <div className="download-list-toolbar"><div className="download-list-heading"><h2 className="text-sm font-semibold">{t("download.downloadQueue")}</h2><details className="download-help"><summary aria-label={t("download.downloadHelp")}><CircleHelp className="size-3.5" aria-hidden="true" />{t("download.downloadHelp")}</summary><div><p>{t("download.concurrentDownloadsFollowServerSettings")}</p><p>{t("download.someVideosMayRequireSignInCookies")}</p></div></details></div><div className="download-list-options">
                <Button icon={Play} variant="primary" disabled={batchBusy || !ready.length} loading={batchBusy} onClick={() => void startAll()}>{t("download.startAllDownloads")} ({ready.length})</Button>
                <div className="download-list-display-controls"><Select aria-label={t("download.taskSortOrder")} value={sort} onChange={event => setSort(event.target.value)} options={[{ value: 'manual', label: t("download.manualOrder") }, { value: 'newest', label: t("download.newestAddedFirst") }, { value: 'oldest', label: t("download.oldestFirst") }]} />
                <div className="dashboard-view-toggle" role="group" aria-label={t("download.downloadView")}><button className="icon-button" aria-label={t("live.gridView")} title={t("live.gridView")} aria-pressed={mode === 'grid'} onClick={() => setMode('grid')}><LayoutGrid className="size-4" /></button><button className="icon-button" aria-label={t("live.listView")} title={t("live.listView")} aria-pressed={mode === 'list'} onClick={() => setMode('list')}><List className="size-4" /></button></div>
                </div>{tasks.length > 0 && <Button icon={Trash2} variant="ghost" disabled={clearing || !clearableTaskCount} title={t("download.clearCompletedHistoryOnlySavedVideoFilesAreKept")} onClick={() => void handleClearCompleted()}>{t("download.clearCompletedHistory")}</Button>}
            </div></div>

            <div className="download-filter-scroll" role="group" aria-label={t("download.downloadStatusFilters")}><div>
                {[['all', translate("live.all"), tasks.length], ['downloading', translate("download.downloading"), counts.downloading + counts.processing], ['queued', translate("settings.waiting"), counts.queued], ['paused', translate("download.paused"), counts.paused], ['completed', translate("live.completed"), counts.completed], ['failed', translate("live.failed"), counts.failed], ...(counts.cancelled ? [['cancelled', translate("download.cancelled"), counts.cancelled]] : [])].map(([value, label, count]) => <button key={value} className={clsx('dashboard-filter', taskFilter === value && 'is-selected')} aria-pressed={taskFilter === value} onClick={event => { setTaskFilter(String(value)); setVisibleCount(50); event.currentTarget.scrollIntoView({ block: 'nearest', inline: 'nearest' }); }}>{t(String(label))} <span className="tabular-nums">({count})</span></button>)}
            </div></div>
            {tasksLoading && !tasks.length ? <LoadingState label={t("download.loadingDownloads")} /> : !tasks.length ? <EmptyState compact icon={FileVideo} title={t("download.noDownloadsAdded")} description={t("download.enterAVODOrClipURLToStartDownloading")} /> : !filteredTasks.length ? <EmptyState compact icon={FileVideo} title={t("download.noDownloadsWithThisStatus")} description={t("download.selectAnotherStatusToViewYourDownloads")} /> : <>
                <div className={`download-task-list download-task-list--${mode}`}>{visibleTasks.map((task, index) => <DownloadTaskCard key={task.task_id} task={task} mode={mode} onAction={onAction} onMove={onMove} onDropTask={onDropTask} manualOrder={sort === 'manual' && !reordering} canMoveUp={sort === 'manual' && !reordering && index > 0} canMoveDown={sort === 'manual' && !reordering && index < visibleTasks.length - 1} retryActive={tasks.some(item => item.task_id === task.retry_task_id && ['queued', 'downloading', 'processing', 'paused'].includes(downloadState(item)))} />)}</div>
                {filteredTasks.length > visibleCount && <Button className="w-full" onClick={() => setVisibleCount(count => count + 50)}>{t("download.showMore")} ({Math.min(visibleCount, filteredTasks.length)} / {filteredTasks.length})</Button>}
            </>}
        </section>
    </div>;
}
