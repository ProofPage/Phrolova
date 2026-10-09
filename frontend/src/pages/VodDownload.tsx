import { useListboxPosition } from "../hooks/useListboxPosition";
import { useListboxKeyboard } from "../hooks/useListboxKeyboard";
import { useState, useRef, useEffect } from "react";
import {
    ChevronDown,
    Download,
    Play,
    AlertCircle,
    CheckCircle,
    Loader2,
    Pause,
    Square,
    FileVideo,
    Clock,
    RotateCw,
    GripVertical,
    ArrowUp,
    ArrowDown,
    FolderOpen,
    Trash2,
    Check,
} from "lucide-react";
import { useVod } from "../contexts/VodContext";
import { api, VodTask } from "../api/client";
import { useToast } from "../components/ui/Toast";
import { useConfirm } from "../components/ui/ConfirmModal";
import { ActionMenu } from "../components/ui/ActionMenu";
import { Badge, Button, EmptyState, Input, LoadingState, PageHeader } from "../components/ui/primitives";
import { clsx } from "clsx";
import { formatBytes, formatDuration } from "../utils/format";
import { getErrorMessage } from "../utils/error";
import { useLanguage } from "../contexts/LanguageContext";

export default function VodDownload() {
    const { t } = useLanguage();
    const { loading: tasksLoading, loadError, tasks, imports, refreshTasks, activeCount, addTask, cancelTask, pauseTask, resumeTask, retryTask, clearCompleted, openFileLocation } = useVod();
    const [source, setSelectedSource] = useState<"chzzk" | "youtube">("chzzk");
    const selectedSource = source === "youtube" ? "youtube" : "chzzk";
    const [sourceMenuOpen, setSourceMenuOpen] = useState(false);
    const sourceMenuRef = useRef<HTMLDivElement>(null);
    const [url, setUrl] = useState("");
    const [loading, setLoading] = useState(false);
    const [importActionId, setImportActionId] = useState<string | null>(null);
    const reorderBusyRef = useRef(false);
    const [reordering, setReordering] = useState(false);
    const [draggedIndex, setDraggedIndex] = useState<number | null>(null);
    const [taskFilter, setTaskFilter] = useState("all");
    const [visibleCount, setVisibleCount] = useState(50);
    const isInitialLoad = tasksLoading && tasks.length === 0;
    const toast = useToast();
    const confirm = useConfirm();
    const clearableTaskCount = tasks.filter((task) =>
        task.state === "idle" || task.state === "completed" || task.state === "error"
    ).length;
    const queuedCount = tasks.filter((task) => task.state === "idle").length;
    const errorCount = tasks.filter((task) => task.state === "error").length;
    const filteredTasks = tasks.filter(task => taskFilter === "all" || task.state === taskFilter);
    const visibleTasks = filteredTasks.slice(0, visibleCount);
    const sourceOptions = [
        { id: "chzzk", label: t("Chzzk"), dot: "bg-chzzk" },
        { id: "youtube", label: t("YouTube"), dot: "bg-youtube" },
    ] as const;
    const selectedSourceOption = sourceOptions.find((option) => option.id === selectedSource)!;

    const sourcePlaceholder = selectedSource === "chzzk"
        ? t("다시보기·클립 링크")
        : t("@핸들 또는 동영상 ID");


    useEffect(() => {
        if (!sourceMenuOpen) return;
        const closeOutside = (event: MouseEvent) => {
            if (!sourceMenuRef.current?.contains(event.target as Node)) setSourceMenuOpen(false);
        };
        const closeEscape = (event: KeyboardEvent) => { if (event.key === "Escape") setSourceMenuOpen(false); };
        document.addEventListener("mousedown", closeOutside);
        document.addEventListener("keydown", closeEscape);
        return () => { document.removeEventListener("mousedown", closeOutside); document.removeEventListener("keydown", closeEscape); };
    }, [sourceMenuOpen]);

    const listboxPosition = useListboxPosition(sourceMenuOpen, sourceMenuRef);
    useListboxKeyboard(sourceMenuOpen, sourceMenuRef, () => setSourceMenuOpen(false));

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!url) return;

        const input = url.trim();
        let downloadUrl = input;
        if (selectedSource === "youtube") {
            const handle = input.match(/^@([^\s/?#]+)$/);
            const videoId = input.match(/^[A-Za-z0-9_-]{11}$/);
            if (handle) downloadUrl = `https://www.youtube.com/@${handle[1]}`;
            else if (videoId) downloadUrl = `https://www.youtube.com/watch?v=${videoId[0]}`;
        }

        let hostname: string;
        try {
            hostname = new URL(downloadUrl).hostname.toLowerCase();
        } catch {
            toast.error(selectedSource === "youtube"
                ? t("YouTube 링크, @핸들 또는 11자리 동영상 ID를 입력해 주세요.")
                : t("올바른 영상 주소를 입력해 주세요."));
            return;
        }
        const isChzzk = hostname === "chzzk.naver.com" || hostname.endsWith(".chzzk.naver.com");
        const isYouTube = hostname === "youtube.com" || hostname.endsWith(".youtube.com")
            || hostname === "youtu.be" || hostname === "youtube-nocookie.com"
            || hostname.endsWith(".youtube-nocookie.com");
        const matchesSource = selectedSource === "chzzk"
            ? isChzzk
            : isYouTube;

        if (!matchesSource) {
            toast.error(selectedSource === "chzzk"
                ? t("Chzzk 다시보기 또는 클립 주소를 입력해 주세요.")
                : t("YouTube 링크, @핸들 또는 동영상 ID를 입력해 주세요."));
            return;
        }

        setLoading(true);

        try {
            const result = await addTask(downloadUrl);
            setUrl("");
            toast.success(result.import_id
                ? t("채널 영상 목록 불러오기를 시작했습니다.")
                : t("다운로드 목록에 추가했습니다."));
        } catch (err: unknown) {
            toast.error(getErrorMessage(err, t("영상 추가에 실패했습니다.")));
        } finally {
            setLoading(false);
        }
    };

    const handleCancel = async (taskId: string, title: string) => {
        const ok = await confirm({
            title: t("다운로드를 취소할까요?"),
            message: t("‘{title}’ 다운로드를 취소합니다.").replace("{title}", title),
            confirmText: t("다운로드 취소"),
            variant: "danger",
        });
        if (!ok) return;
        try {
            await cancelTask(taskId);
            toast.success(t("다운로드 취소를 요청했습니다."));
        } catch (err: unknown) {
            toast.error(getErrorMessage(err, t("다운로드를 취소하지 못했습니다.")));
        }
    };

    const handleRetry = async (taskId: string, title: string) => {
        const ok = await confirm({
            title: t("다운로드를 다시 시작할까요?"),
            message: t("‘{title}’을(를) 다시 다운로드합니다.").replace("{title}", title),
            confirmText: t("다시 시도"),
        });
        if (!ok) return;
        try {
            await retryTask(taskId);
            toast.success(t("다운로드를 다시 시작했습니다."));
        } catch (err: unknown) {
            toast.error(getErrorMessage(err, t("다운로드를 다시 시작하지 못했습니다.")));
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
        const ok = await confirm({
            title: t("다운로드 목록을 정리할까요?"),
            message: t("대기 중·완료·실패한 작업만 목록에서 삭제합니다. 진행 중이거나 일시정지한 작업과 저장된 파일은 유지됩니다."),
            confirmText: t("목록 정리"),
            variant: "danger",
        });
        if (!ok) return;

        try {
            const result = await clearCompleted();
            toast.success(t("다운로드 목록에서 {count}개 항목을 삭제했습니다.").replace("{count}", String(result.deleted_count)));
        } catch (err: unknown) {
            toast.error(getErrorMessage(err, t("목록 정리에 실패했습니다.")));
        }
    };

    const handleDragStart = (index: number) => {
        setDraggedIndex(index);
    };

    const handleDragOver = (e: React.DragEvent, _index: number) => {
        e.preventDefault();
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
            toast.error(t("작업 순서 변경에 실패했습니다."));
        } finally {
            reorderBusyRef.current = false;
            setReordering(false);
        }
    };

    const handleDrop = async (e: React.DragEvent, dropIndex: number) => {
        e.preventDefault();
        if (draggedIndex === null || draggedIndex === dropIndex) {
            setDraggedIndex(null);
            return;
        }

        const task = tasks[draggedIndex];
        if (task) await reorderTask(task.task_id, dropIndex);

        setDraggedIndex(null);
    };

    return (
        <div className="product-page downloads-page space-y-4">
            <PageHeader
                icon={Download}
                eyebrow={t("다운로드 관리")}
                title={t("다운로드")}
                description={t("다시보기, 클립 및 지원되는 영상을 다운로드합니다.")}
                meta={(
                    <>
                        <Badge tone={activeCount > 0 ? "ok" : "neutral"}>{t("진행 중")} {activeCount}</Badge>
                        <Badge tone="neutral">{t("대기 중")} {queuedCount}</Badge>
                        <Badge tone={errorCount > 0 ? "danger" : "neutral"}>{t("실패")} {errorCount}</Badge>
                        <Badge tone="neutral">{t("전체")} {tasks.length}</Badge>
                    </>
                )}
                actions={(
                    <form onSubmit={handleSubmit}>
                        <div className="download-form">
                            <div className="relative w-fit shrink-0" ref={sourceMenuRef}>
                                <button
                                    type="button"
                                    onClick={() => setSourceMenuOpen((open) => !open)}
                                    className="ui-input w-auto px-3 text-ink text-sm flex items-center gap-1.5 hover:bg-surface-3 transition-colors whitespace-nowrap"
                                    aria-expanded={sourceMenuOpen}
                                    aria-haspopup="listbox"
                                    aria-label={`${t("플랫폼 선택")}: ${selectedSourceOption.label}`}
                                >
                                    <span className={`inline-block h-2 w-2 rounded-full ${selectedSourceOption.dot}`} />
                                    <span>{selectedSourceOption.label}</span>
                                    <ChevronDown className="h-3 w-3 text-ink-faint" />
                                </button>
                                {sourceMenuOpen && (
                                    <div style={listboxPosition} className="ui-popover absolute left-0 top-full z-20 mt-2 min-w-[180px] overflow-hidden rounded-[var(--radius-control)]" role="listbox" aria-label={t("다운로드 플랫폼")}>
                                        {sourceOptions.map((option) => (
                                            <button
                                                key={option.id}
                                                type="button"
                                                role="option"
                                                aria-selected={selectedSource === option.id}
                                                onClick={() => {
                                                    setSelectedSource(option.id);
                                                    setSourceMenuOpen(false);
                                                }}
                                                className={clsx(
                                                    "flex min-h-10 w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors",
                                                    selectedSource === option.id ? "bg-info/12 text-ink" : "text-ink-muted hover:bg-surface-3 hover:text-ink",
                                                )}
                                            >
                                                <span className={`inline-block size-2 shrink-0 rounded-full ${option.dot}`} />
                                                <span className="flex-1">{option.label}</span>
                                                {selectedSource === option.id && <Check className="size-4 shrink-0 text-info" aria-hidden="true" />}
                                            </button>
                                        ))}
                                    </div>
                                )}
                            </div>
                            <div className="vod-submit">
                                <Input
                                    id="vod-url"
                                    type="text"
                                    className="min-w-0 flex-1"
                                    aria-label={selectedSource === "youtube"
                                        ? "YouTube 링크, 채널 핸들 또는 동영상 ID"
                                        : `${selectedSourceOption.label} 영상 주소`}
                                    placeholder={sourcePlaceholder}
                                    value={url}
                                    onChange={(event) => setUrl(event.target.value)}
                                    autoComplete="off"
                                />
                                <Button type="submit" icon={Download} loading={loading} disabled={!url} variant="primary" className="shrink-0 px-3 sm:px-5">
                                    {t("다운로드 시작")}
                                </Button>
                            </div>
                        </div>
                    </form>
                )}
                actionsPlacement="below"
            />

            {loadError && <div role="status" className="flex flex-wrap items-center justify-between gap-2 border-y border-line py-3 text-xs text-ink-muted"><span>{t("다운로드 목록을 불러오지 못했습니다. 잠시 후 다시 시도하세요.")}</span><Button icon={RotateCw} onClick={() => void refreshTasks()}>{t("다시 시도")}</Button></div>}
            {imports.map((job) => {
                const running = job.state === "queued" || job.state === "collecting";
                const label = job.state === "queued" ? "채널 영상 목록 불러오기 대기 중"
                    : job.state === "collecting" ? "채널 영상 목록을 불러오는 중"
                    : job.state === "completed" ? "채널 영상 목록 불러오기 완료"
                    : job.state === "cancelled" ? "채널 영상 목록 불러오기 중지됨" : "채널 영상 목록을 불러오지 못했습니다.";
                return (
                    <div key={job.id} role="status" className="download-import rounded-[var(--radius-card)] border border-line bg-surface-2 p-4 flex flex-wrap sm:flex-nowrap items-start gap-3 [overflow-wrap:anywhere]">
                        {running ? <Loader2 className="w-5 h-5 animate-spin text-[var(--primary)] shrink-0 mt-0.5" />
                            : job.state === "error" ? <AlertCircle className="w-5 h-5 text-danger shrink-0 mt-0.5" />
                            : <CheckCircle className="w-5 h-5 text-[var(--primary)] shrink-0 mt-0.5" />}
                        <div className="min-w-0 flex-1 space-y-1">
                            <p className="text-sm font-semibold text-ink">{t(label)}</p>
                            <p className="text-xs text-ink-muted break-all">{job.url}</p>
                            <p className="text-xs text-ink-muted">{t("추가한 영상")}: {job.added_count} · {t("이미 목록에 있는 영상")}: {job.skipped_count}</p>
                            {running && <p className="text-xs text-ink-muted">{t("찾은 영상부터 다운로드합니다. 목록 불러오기를 중지해도 이미 추가된 영상은 유지됩니다.")}</p>}
                            {job.error && <details className="text-xs text-danger">
                                <summary className="cursor-pointer">{t("오류 세부 정보")}</summary>
                                <p className="mt-1 break-words">{job.error}</p>
                            </details>}
                        </div>
                        <Button className="max-sm:w-full" loading={importActionId === job.id} disabled={importActionId !== null} onClick={async () => {
                            if (importActionId !== null) return;
                            setImportActionId(job.id);
                            try { await api.cancelVodImport(job.id); await refreshTasks(); }
                            catch (err) { toast.error(getErrorMessage(err, t("요청에 실패했습니다."))); }
                            finally { setImportActionId(null); }
                        }}>{t(running ? "불러오기 중지" : "닫기")}</Button>
                    </div>
                );
            })}

            <div className="space-y-4">
                <div className="flex flex-wrap gap-2 items-center justify-between">
                    <h3 className="text-base font-semibold text-ink flex items-center gap-2">
                        {t("다운로드 목록")}
                        <Badge tone="neutral">{tasks.length}</Badge>
                    </h3>
                    {tasks.length > 0 && (
                        <Button
                            icon={Trash2}
                            onClick={handleClearCompleted}
                            disabled={clearableTaskCount === 0}
                            title={clearableTaskCount > 0
                                ? "대기·완료·오류 항목을 정리합니다."
                                : "진행 중이거나 일시정지한 항목은 정리할 수 없습니다."}
                        >
                            목록 정리
                        </Button>
                    )}
                </div>

                <div className="min-w-0 overflow-x-auto border-b border-line" role="group" aria-label={t("다운로드 상태 필터")}>
                    <div className="flex w-max min-w-full gap-1 pb-2">
                        {[["all", "전체"], ["downloading", "다운로드 중"], ["idle", "대기 중"], ["paused", "일시정지"], ["completed", "완료"], ["error", "실패"]].map(([value,label]) => <button key={value} type="button" onClick={(event) => { setTaskFilter(value); setVisibleCount(50); event.currentTarget.scrollIntoView({ block: "nearest", inline: "nearest" }); }} aria-pressed={taskFilter === value} className={clsx("dashboard-filter min-h-11 sm:min-h-8 shrink-0 rounded-[5px] px-2.5 py-1.5 text-xs whitespace-nowrap", taskFilter === value && "is-selected")}>
                            {t(label)} <span className="ml-1 text-ink-faint">{value === "all" ? tasks.length : tasks.filter(task => task.state === value).length}</span>
                        </button>)}
                    </div>
                </div>
                {isInitialLoad ? (
                    <LoadingState label="다운로드 목록을 불러오는 중" />
                ) : tasks.length === 0 && imports.some(job => job.state === "queued" || job.state === "collecting") ? (
                    <p className="py-8 text-center text-sm text-ink-muted">{t("영상을 찾으면 이곳에 표시됩니다.")}</p>
                ) : loadError && tasks.length === 0 ? null : tasks.length === 0 ? (
                    <EmptyState icon={FileVideo} title={t("아직 추가한 영상이 없습니다")} description={t("영상 주소를 추가하면 다운로드 진행 상황과 저장 위치를 확인할 수 있습니다.")} />
                ) : (
                    <div>
                        {visibleTasks.map((task, visibleIndex) => (
                            <div
                                key={task.task_id}
                                draggable={!reordering}
                                onDragEnd={() => setDraggedIndex(null)}
                                onDragStart={() => handleDragStart(tasks.indexOf(task))}
                                onDragOver={(e) => handleDragOver(e, tasks.indexOf(task))}
                                onDrop={(e) => handleDrop(e, tasks.indexOf(task))}
                                className={clsx(
                                    "min-w-0 transition-opacity",
                                    draggedIndex === tasks.indexOf(task) && "opacity-50"
                                )}
                            >
                                <TaskCard
                                    task={task}
                                    canMoveUp={!reordering && visibleIndex > 0}
                                    canMoveDown={!reordering && visibleIndex < visibleTasks.length - 1}
                                    onMove={(direction) => { const target = visibleTasks[visibleIndex + direction]; if (target) void reorderTask(task.task_id, tasks.indexOf(target), true); }}
                                    onCancel={() => handleCancel(task.task_id, task.title)}
                                    onPause={() => void handleTaskAction(() => pauseTask(task.task_id), "다운로드를 일시정지했습니다.", "다운로드를 일시정지하지 못했습니다.")}
                                    onResume={() => void handleTaskAction(() => resumeTask(task.task_id), "다운로드를 재개했습니다.", "다운로드를 재개하지 못했습니다.")}
                                    onRetry={() => handleRetry(task.task_id, task.title)}
                                    onOpenLocation={() => openFileLocation(task.task_id)}
                                />
                            </div>
                        ))}
                        {filteredTasks.length === 0 && <EmptyState compact icon={FileVideo} title="해당 상태의 다운로드가 없습니다." description="다른 상태를 선택해 작업을 확인하세요." />}
                        {filteredTasks.length > visibleCount && <Button className="w-full" onClick={() => setVisibleCount(count => count + 50)}>
                            {t("더 보기")} ({Math.min(visibleCount, filteredTasks.length)} / {filteredTasks.length})
                        </Button>}
                    </div>
                )}
            </div>
        </div>
    );
}

// ── 다운로드 태스크 카드 ─────────────────────────────

interface TaskCardProps {
    task: VodTask;
    canMoveUp: boolean;
    canMoveDown: boolean;
    onMove: (direction: number) => void;
    onCancel: () => void;
    onPause: () => void;
    onResume: () => void;
    onRetry: () => void;
    onOpenLocation: () => void;
}

function TaskCard({ task, canMoveUp, canMoveDown, onMove, onCancel, onPause, onResume, onRetry, onOpenLocation }: TaskCardProps) {
    const { t } = useLanguage();
    const statusLabels: Record<string,string> = { idle: "대기 중", downloading: "다운로드 중", paused: "일시정지", completed: "완료", error: "실패", cancelling: "취소 중" };
    const tone = task.state === "error" ? "danger" : task.state === "completed" ? "ok" : task.state === "paused" ? "warn" : task.state === "downloading" ? "info" : "neutral";
    const source = (() => { try { const host = new URL(task.url).hostname; return host.includes("youtube") || host === "youtu.be" ? "YouTube" : host.includes("chzzk") ? t("Chzzk") : host.includes("x.com") || host.includes("twitter.com") ? "X Spaces" : host; } catch { return t("외부 영상"); } })();
    return <div className="download-row">
        <div className="download-content min-w-0 [overflow-wrap:anywhere]">
            <div className="download-heading flex min-w-0 flex-wrap items-start gap-2">
                <span className="download-state-icon grid size-5 shrink-0 place-items-center text-ink-faint" aria-hidden="true">
            {task.state === "downloading" || task.state === "cancelling" ? <Loader2 className="size-4 animate-spin" /> : task.state === "completed" ? <CheckCircle className="size-4 text-ok" /> : task.state === "error" ? <AlertCircle className="size-4 text-danger" /> : task.state === "paused" ? <Pause className="size-4 text-warn" /> : <Clock className="size-4" />}
                </span>
                <h3 className="download-title min-w-0 flex-1 break-words font-medium text-ink" title={task.title}>{task.title}</h3><Badge tone={tone}>{t(statusLabels[task.state] || task.state)}</Badge>
            <ActionMenu className="download-mobile-menu" label={`${t("작업 순서 변경")}: ${task.title}`}>{close => <>
                <button type="button" disabled={!canMoveUp} onClick={() => { onMove(-1); close(); }}><ArrowUp className="size-4" />{t("위로 이동")}</button>
                <button type="button" disabled={!canMoveDown} onClick={() => { onMove(1); close(); }}><ArrowDown className="size-4" />{t("아래로 이동")}</button>
            </>}</ActionMenu>
            </div>
            <p className="text-xs text-ink-faint">{source} · {task.quality === "best" ? t("최고 화질") : task.quality}{source === t("Chzzk") && task.url.includes("chzzk.naver.com/video/") && ` · ${task.cdn === "akamai" ? "Akamai CDN" : "기본 CDN"}`}</p>
            {(task.state === "downloading" || task.state === "paused" || task.state === "cancelling") && <>
                <div className="flex items-center gap-3"><div className="h-1 flex-1 overflow-hidden rounded bg-surface-4" role="progressbar" aria-label={t("다운로드 진행률")} aria-valuenow={Math.round(task.progress)} aria-valuemin={0} aria-valuemax={100}><div className="h-full bg-info transition-[width]" style={{width:`${task.progress}%`}} /></div><span className="text-xs text-ink-muted tabular-nums">{Math.round(task.progress)}%</span></div>
                <div className="download-transfer flex flex-wrap gap-x-4 gap-y-1 text-ink-muted tabular-nums"><span>{formatBytes(task.downloaded_bytes)}{task.total_bytes > 0 && ` / ${formatBytes(task.total_bytes)}`}</span>{task.state === "downloading" && <span>{task.download_speed.toFixed(2)} MB/s</span>}{task.eta_seconds > 0 && <span>{t("남은 시간")} {formatDuration(task.eta_seconds)}</span>}</div>
            </>}
            {task.state === "completed" && <p className="text-xs text-ink-faint">{formatBytes(task.total_bytes || task.downloaded_bytes)}{task.completed_at && ` · ${new Date(task.completed_at).toLocaleString()}`}</p>}
            {task.warning_message && <p className="text-xs text-warn" role="status">{task.warning_message}</p>}
            {task.error_message && <div className="text-xs text-danger"><p>{t("다운로드를 완료하지 못했습니다. 다시 시도하거나 영상 주소와 인증 설정을 확인하세요.")}</p><details className="mt-1"><summary className="cursor-pointer text-ink-faint">{t("오류 세부 정보")}</summary><p className="mt-1 break-words">{task.error_message}</p></details></div>}
            {task.output_path && <details className="text-xs text-ink-faint"><summary className="cursor-pointer">{t("저장 위치")}</summary><p className="mt-1 break-all">{task.output_path}</p></details>}
        </div>
        <div className="download-footer">
            <div className="download-actions">
            {task.state === "downloading" && <Button variant="ghost" icon={Pause} onClick={onPause}>{t("일시정지하기")}</Button>}
            {task.state === "paused" && <Button variant="secondary" icon={Play} onClick={onResume}>{t("재개")}</Button>}
            {(task.state === "downloading" || task.state === "paused") && <Button variant="danger" icon={Square} onClick={onCancel}>{t("취소")}</Button>}
            {(task.state === "completed" || task.state === "error") && <Button variant="secondary" icon={RotateCw} onClick={onRetry}>{t(task.state === "error" ? "다시 시도" : "다시 다운로드")}</Button>}
            {task.state === "completed" && task.output_path && <Button variant="ghost" icon={FolderOpen} onClick={onOpenLocation} title={t("파일 위치 열기")}>{t("폴더 열기")}</Button>}
        </div>
        <div className="download-reorder" role="group" aria-label={`${t("작업 순서 변경")}: ${task.title}`}>
            <span className="text-xs text-ink-faint">{t("작업 순서 변경")}</span>
            <span className="download-drag-handle text-ink-faint" title={t("작업 순서 변경")} aria-hidden="true"><GripVertical className="size-4" /></span>
            <button type="button" className="icon-button disabled:opacity-30" disabled={!canMoveUp} aria-label={`${t("위로 이동")}: ${task.title}`} onClick={() => onMove(-1)}><ArrowUp className="size-4" /></button>
            <button type="button" className="icon-button disabled:opacity-30" disabled={!canMoveDown} aria-label={`${t("아래로 이동")}: ${task.title}`} onClick={() => onMove(1)}><ArrowDown className="size-4" /></button>
        </div>
        </div>
    </div>;
}
