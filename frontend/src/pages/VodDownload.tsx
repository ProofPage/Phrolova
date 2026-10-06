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
    FolderOpen,
    Plus,
    Trash2,
} from "lucide-react";
import { useVod } from "../contexts/VodContext";
import { api, VodTask } from "../api/client";
import { useToast } from "../components/ui/Toast";
import { useConfirm } from "../components/ui/ConfirmModal";
import { Badge, Button, EmptyState, Input, PageHeader } from "../components/ui/primitives";
import { clsx } from "clsx";
import { formatDuration } from "../utils/format";
import { getErrorMessage } from "../utils/error";
import { useLanguage } from "../contexts/LanguageContext";

export default function VodDownload() {
    const { t } = useLanguage();
    const { tasks, imports, refreshTasks, activeCount, addTask, cancelTask, pauseTask, resumeTask, retryTask, clearCompleted, openFileLocation } = useVod();
    const [selectedSource, setSelectedSource] = useState<"chzzk" | "youtube" | "external">("chzzk");
    const [sourceMenuOpen, setSourceMenuOpen] = useState(false);
    const [url, setUrl] = useState("");
    const [loading, setLoading] = useState(false);
    const [draggedIndex, setDraggedIndex] = useState<number | null>(null);
    const [visibleCount, setVisibleCount] = useState(50);
    const [isInitialLoad, setIsInitialLoad] = useState(true);
    const toast = useToast();
    const confirm = useConfirm();
    const clearableTaskCount = tasks.filter((task) =>
        task.state === "idle" || task.state === "completed" || task.state === "error"
    ).length;
    const queuedCount = tasks.filter((task) => task.state === "idle").length;
    const errorCount = tasks.filter((task) => task.state === "error").length;
    const sourceOptions = [
        { id: "chzzk", label: t("치지직"), dot: "bg-chzzk" },
        { id: "youtube", label: t("유튜브"), dot: "bg-youtube" },
        { id: "external", label: t("외부 영상"), dot: "bg-[var(--primary)]" },
    ] as const;
    const selectedSourceOption = sourceOptions.find((option) => option.id === selectedSource)!;

    const sourcePlaceholder = selectedSource === "chzzk"
        ? t("다시보기 URL 또는 클립 URL")
        : selectedSource === "youtube"
            ? t("핸들(@username) 또는 동영상 ID")
            : t("다운로드할 영상 링크");

    useEffect(() => {
        const timer = setTimeout(() => setIsInitialLoad(false), 500);
        return () => clearTimeout(timer);
    }, []);

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
                ? t("유튜브 링크, @핸들 또는 11자리 동영상 ID를 입력해 주세요.")
                : t("올바른 영상 주소를 입력해 주세요."));
            return;
        }
        const isChzzk = hostname === "chzzk.naver.com" || hostname.endsWith(".chzzk.naver.com");
        const isYouTube = hostname === "youtube.com" || hostname.endsWith(".youtube.com")
            || hostname === "youtu.be" || hostname === "youtube-nocookie.com"
            || hostname.endsWith(".youtube-nocookie.com");
        const matchesSource = selectedSource === "chzzk"
            ? isChzzk
            : selectedSource === "youtube"
                ? isYouTube
                : !isChzzk && !isYouTube;

        if (!matchesSource) {
            toast.error(selectedSource === "chzzk"
                ? t("치지직 다시보기 또는 클립 주소를 입력해 주세요.")
                : selectedSource === "youtube"
                    ? t("유튜브 링크, @핸들 또는 동영상 ID를 입력해 주세요.")
                    : t("지원되는 외부 영상 주소인지 확인해 주세요."));
            return;
        }

        setLoading(true);

        try {
            const result = await addTask(downloadUrl);
            setUrl("");
            toast.success(result.import_id
                ? t("채널 영상 수집을 시작했습니다.")
                : t("다운로드 목록에 추가했습니다."));
        } catch (err: unknown) {
            toast.error(getErrorMessage(err, t("영상 추가에 실패했습니다.")));
        } finally {
            setLoading(false);
        }
    };

    const handleCancel = async (taskId: string, title: string) => {
        const ok = await confirm({
            title: "다운로드 중지",
            message: `'${title}' 다운로드를 중지할까요?`,
            confirmText: "중지",
            variant: "danger",
        });
        if (ok) cancelTask(taskId);
    };

    const handleRetry = async (taskId: string, title: string) => {
        const ok = await confirm({
            title: "다시 다운로드",
            message: `'${title}'을(를) 다시 받을까요?`,
            confirmText: "다시 받기",
        });
        if (ok) retryTask(taskId);
    };

    const handleClearCompleted = async () => {
        const ok = await confirm({
            title: "목록 정리",
            message: "대기·완료·오류 항목을 목록에서 삭제할까요? 진행 중이거나 일시정지한 항목은 유지됩니다.",
            confirmText: "정리",
            variant: "danger",
        });
        if (!ok) return;

        try {
            const result = await clearCompleted();
            toast.success(`${result.deleted_count}개 항목을 정리했습니다.`);
        } catch (err: unknown) {
            toast.error(getErrorMessage(err, "목록 정리에 실패했습니다."));
        }
    };

    const handleDragStart = (index: number) => {
        setDraggedIndex(index);
    };

    const handleDragOver = (e: React.DragEvent, _index: number) => {
        e.preventDefault();
    };

    const handleDrop = async (e: React.DragEvent, dropIndex: number) => {
        e.preventDefault();
        if (draggedIndex === null || draggedIndex === dropIndex) {
            setDraggedIndex(null);
            return;
        }

        const newTasks = [...tasks];
        const [draggedTask] = newTasks.splice(draggedIndex, 1);
        newTasks.splice(dropIndex, 0, draggedTask);

        try {
            const taskIds = newTasks.map((t) => t.task_id);
            await api.reorderVodTasks(taskIds);
        } catch {
            toast.error("작업 순서 변경에 실패했습니다.");
        }

        setDraggedIndex(null);
    };

    return (
        <div className="space-y-6">
            <PageHeader
                icon={Download}
                eyebrow={t("영상 다운로드")}
                title={t("다시보기 대시보드")}
                description={t("여러 플랫폼의 다시보기와 클립을 추가하고 다운로드 상태를 한곳에서 관리합니다.")}
                meta={(
                    <>
                        <Badge tone={activeCount > 0 ? "ok" : "neutral"}>{t("진행 중")} {activeCount}</Badge>
                        <Badge tone="neutral">{t("대기")} {queuedCount}</Badge>
                        <Badge tone={errorCount > 0 ? "danger" : "neutral"}>{t("오류")} {errorCount}</Badge>
                        <Badge tone="neutral">{t("전체")} {tasks.length}</Badge>
                    </>
                )}
                actions={(
                    <form onSubmit={handleSubmit}>
                        <div className="flex flex-col items-start gap-2 sm:flex-row">
                            <div className="relative shrink-0">
                                <button
                                    type="button"
                                    onClick={() => setSourceMenuOpen((open) => !open)}
                                    className="h-11 bg-surface-2 border border-line rounded-[var(--radius-control)] px-3 text-ink text-sm flex items-center gap-1.5 hover:bg-surface-3 transition-colors whitespace-nowrap"
                                    aria-expanded={sourceMenuOpen}
                                    aria-haspopup="listbox"
                                    aria-label={`${t("플랫폼 선택")}: ${selectedSourceOption.label}`}
                                >
                                    <span className={`inline-block h-2 w-2 rounded-full ${selectedSourceOption.dot}`} />
                                    <span>{selectedSourceOption.label}</span>
                                    <ChevronDown className="h-3 w-3 text-ink-faint" />
                                </button>
                                {sourceMenuOpen && (
                                    <div className="absolute left-0 top-full z-20 mt-1 min-w-[180px] overflow-hidden rounded-[var(--radius-control)] border border-line-strong bg-surface-2 shadow-xl" role="listbox" aria-label={t("다운로드 플랫폼")}>
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
                                                className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-ink-muted transition-colors hover:bg-surface-3"
                                            >
                                                <span className={`inline-block h-2 w-2 rounded-full ${option.dot}`} />
                                                <span className="flex-1">{option.label}</span>
                                            </button>
                                        ))}
                                    </div>
                                )}
                            </div>
                            <Input
                                id="vod-url"
                                type="text"
                                className="min-w-0 flex-1"
                                aria-label={selectedSource === "youtube"
                                    ? "유튜브 링크, 채널 핸들 또는 동영상 ID"
                                    : `${selectedSourceOption.label} 영상 주소`}
                                placeholder={sourcePlaceholder}
                                value={url}
                                onChange={(event) => setUrl(event.target.value)}
                                autoComplete="off"
                            />
                                <Button type="submit" icon={Plus} loading={loading} disabled={!url} variant="primary" className="sm:px-5">
                                {t("추가")}
                            </Button>
                        </div>
                    </form>
                )}
                actionsPlacement="below"
            />

            {imports.map((job) => {
                const running = job.state === "queued" || job.state === "collecting";
                const label = job.state === "queued" ? "채널 영상 수집 대기 중"
                    : job.state === "collecting" ? "채널 영상을 불러오는 중"
                    : job.state === "completed" ? "채널 영상 수집 완료"
                    : job.state === "cancelled" ? "채널 영상 수집 중지됨" : "채널 영상 수집 실패";
                return (
                    <div key={job.id} role="status" className="rounded-[var(--radius-card)] border border-line bg-surface-2 p-4 flex items-start gap-3">
                        {running ? <Loader2 className="w-5 h-5 animate-spin text-accent shrink-0 mt-0.5" />
                            : job.state === "error" ? <AlertCircle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
                            : <CheckCircle className="w-5 h-5 text-accent shrink-0 mt-0.5" />}
                        <div className="min-w-0 flex-1 space-y-1">
                            <p className="text-sm font-semibold text-ink">{t(label)}</p>
                            <p className="text-xs text-ink-muted break-all">{job.url}</p>
                            <p className="text-xs text-ink-muted">{t("추가한 영상")}: {job.added_count} · {t("이미 목록에 있는 영상")}: {job.skipped_count}</p>
                            {running && <p className="text-xs text-ink-muted">{t("찾은 영상부터 다운로드합니다. 수집을 중지해도 추가된 영상은 유지됩니다.")}</p>}
                            {job.error && <p className="text-xs text-red-400 break-words">{job.error}</p>}
                        </div>
                        <Button onClick={async () => {
                            try { await api.cancelVodImport(job.id); await refreshTasks(); }
                            catch (err) { toast.error(getErrorMessage(err, t("요청에 실패했습니다."))); }
                        }}>{t(running ? "수집 중지" : "닫기")}</Button>
                    </div>
                );
            })}

            <div className="space-y-4">
                <div className="flex items-center justify-between">
                    <h3 className="text-base font-semibold text-ink flex items-center gap-2">
                        다운로드 목록
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

                {isInitialLoad ? (
                    <div className="space-y-3">
                        {[1, 2, 3].map(i => (
                            <div key={i} className="grid w-full min-w-0 grid-cols-[auto_auto_1fr] gap-x-3 gap-y-2 p-3 sm:flex sm:items-start sm:gap-4 sm:p-4 bg-surface-2 border border-line rounded-[var(--radius-card)] animate-pulse">
                                <div className="col-start-2 row-start-1 w-12 h-12 bg-surface-3 rounded-[var(--radius-control)] shrink-0 sm:w-24 sm:h-20" />
                                <div className="col-span-3 row-start-2 w-full min-w-0 space-y-3 pt-1 sm:col-span-1 sm:row-auto sm:flex-1 sm:pt-2">
                                    <div className="skeleton h-4 rounded w-1/3" />
                                    <div className="skeleton w-full h-2 rounded-full" />
                                    <div className="skeleton h-3 rounded w-1/4" />
                                </div>
                            </div>
                        ))}
                    </div>
                ) : tasks.length === 0 && imports.some(job => job.state === "queued" || job.state === "collecting") ? (
                    <p className="py-8 text-center text-sm text-ink-muted">{t("영상을 찾으면 이곳에 표시됩니다.")}</p>
                ) : tasks.length === 0 ? (
                    <EmptyState icon={FileVideo} title="아직 추가한 영상이 없습니다" description="위에서 영상 주소를 추가하면 진행 상황과 저장된 파일을 이곳에서 확인할 수 있습니다." />
                ) : (
                    <div className="space-y-3">
                        {tasks.slice(0, visibleCount).map((task, index) => (
                            <div
                                key={task.task_id}
                                draggable
                                onDragStart={() => handleDragStart(index)}
                                onDragOver={(e) => handleDragOver(e, index)}
                                onDrop={(e) => handleDrop(e, index)}
                                className={clsx(
                                    "min-w-0 transition-opacity",
                                    draggedIndex === index && "opacity-50"
                                )}
                            >
                                <TaskCard
                                    task={task}
                                    onCancel={() => handleCancel(task.task_id, task.title)}
                                    onPause={() => pauseTask(task.task_id)}
                                    onResume={() => resumeTask(task.task_id)}
                                    onRetry={() => handleRetry(task.task_id, task.title)}
                                    onOpenLocation={() => openFileLocation(task.task_id)}
                                />
                            </div>
                        ))}
                        {tasks.length > visibleCount && <Button className="w-full" onClick={() => setVisibleCount(count => count + 50)}>
                            {t("더 보기")} ({Math.min(visibleCount, tasks.length)} / {tasks.length})
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
    onCancel: () => void;
    onPause: () => void;
    onResume: () => void;
    onRetry: () => void;
    onOpenLocation: () => void;
}

function TaskCard({ task, onCancel, onPause, onResume, onRetry, onOpenLocation }: TaskCardProps) {
    const statusBadgeClass =
        task.state === "completed"
            ? "bg-ok/10 text-ok border-ok/20"
            : task.state === "downloading"
                ? "bg-info/10 text-info border-info/20"
                : task.state === "paused"
                    ? "bg-warn/10 text-warn border-warn/20"
                    : task.state === "error"
                        ? "bg-danger/10 text-danger border-danger/20"
                        : "bg-surface-4 text-ink-muted border-line";

    const statusLabels: Record<string, string> = {
        idle: "대기",
        downloading: "다운로드 중",
        paused: "일시정지",
        completed: "완료",
        error: "오류",
        cancelling: "취소 중",
    };

    const barColorClass =
        task.state === "completed"
            ? "bg-ok"
            : task.state === "error"
                ? "bg-danger"
                : task.state === "paused"
                    ? "bg-warn"
                    : "bg-info";

    return (
        <div className="grid w-full min-w-0 grid-cols-[auto_auto_1fr] gap-x-3 gap-y-2 p-3 sm:flex sm:items-start sm:gap-4 sm:p-4 bg-surface-2 border border-line rounded-[var(--radius-card)] hover:border-line-strong transition-colors surface-raise">
            {/* 드래그 핸들 */}
            <div className="col-start-1 row-start-1 flex self-stretch items-center justify-center text-ink-faint hover:text-ink-muted cursor-grab active:cursor-grabbing">
                <GripVertical className="w-5 h-5" />
            </div>

            {/* 상태 아이콘 영역 */}
            <div className={clsx(
                "col-start-2 row-start-1 w-12 h-12 bg-surface-1 border border-line rounded-[var(--radius-control)] flex items-center justify-center shrink-0 sm:w-24 sm:h-auto sm:self-stretch",
            )}>
                {task.state === "completed" && <CheckCircle className="text-ok w-6 h-6 sm:w-8 sm:h-8" />}
                {task.state === "downloading" && (
                    <div className="text-ink font-mono font-bold text-sm sm:text-lg">
                        {Math.round(task.progress)}%
                    </div>
                )}
                {task.state === "paused" && <Pause className="text-warn w-6 h-6 sm:w-8 sm:h-8" />}
                {task.state === "error" && <AlertCircle className="text-danger w-6 h-6 sm:w-8 sm:h-8" />}
                {task.state === "idle" && <Clock className="text-ink-faint w-6 h-6 sm:w-8 sm:h-8" />}
                {task.state === "cancelling" && (
                    <Loader2 className="text-danger w-6 h-6 animate-spin" />
                )}
            </div>

            <span className={clsx(
                "col-start-3 row-start-1 inline-flex items-center justify-self-end self-center text-[11px] font-medium px-2 py-1 rounded-full border whitespace-nowrap sm:hidden",
                statusBadgeClass,
            )}>
                {statusLabels[task.state] || task.state}
            </span>

            <div className="col-span-3 row-start-2 w-full min-w-0 space-y-2 sm:col-span-1 sm:row-auto sm:flex-1">
                <div className="flex justify-between items-start gap-2">
                    <h4 className="font-semibold text-ink truncate text-sm flex-1">
                        {task.title}
                    </h4>
                    <span
                        className={clsx(
                            "hidden sm:inline-flex text-[11px] font-medium px-2 py-1 rounded-full border capitalize whitespace-nowrap",
                            statusBadgeClass
                        )}
                    >
                        {statusLabels[task.state] || task.state}
                    </span>
                </div>

                <div className="text-xs text-ink-faint font-mono flex flex-wrap gap-x-4">
                    <span>화질: {task.quality === "best" ? "최고 화질" : task.quality}</span>
                    {task.error_message && (
                        <span className="text-danger">오류: {task.error_message}</span>
                    )}
                </div>

                {/* 진행률 바 */}
                <div className="w-full bg-surface-4 h-1.5 rounded-full overflow-hidden">
                    <div
                        className={clsx("h-full transition-all duration-300", barColorClass)}
                        style={{ width: `${task.progress}%` }}
                    />
                </div>

                {/* 다운로드 통계 (다운로드 중일 때만 표시) */}
                {task.state === "downloading" && task.total_bytes > 0 && (
                    <div className="text-xs text-ink-muted font-mono flex flex-wrap gap-x-4 gap-y-1">
                        <span>
                            속도: <span className="text-ok">{task.download_speed.toFixed(2)} MB/s</span>
                        </span>
                        <span>
                            용량: {(task.downloaded_bytes / (1024 * 1024)).toFixed(1)} MB / {(task.total_bytes / (1024 * 1024)).toFixed(1)} MB
                        </span>
                        {task.eta_seconds > 0 && (
                            <span>
                                남은 시간: {formatDuration(task.eta_seconds, "eta")}
                            </span>
                        )}
                    </div>
                )}

                {/* 제어 버튼 */}
                {(task.state === "downloading" || task.state === "paused") && (
                    <div className="flex gap-2">
                        {task.state === "downloading" ? (
                            <button
                                onClick={onPause}
                                className="p-1.5 bg-surface-3 hover:bg-surface-4 text-warn border border-line rounded-[var(--radius-control)] transition-colors flex items-center gap-1 text-xs"
                                title="일시정지"
                            >
                                <Pause className="w-3 h-3" />
                                <span>일시정지</span>
                            </button>
                        ) : (
                            <button
                                onClick={onResume}
                                className="p-1.5 bg-surface-3 hover:bg-surface-4 text-ok border border-line rounded-[var(--radius-control)] transition-colors flex items-center gap-1 text-xs"
                                title="재개"
                            >
                                <Play className="w-3 h-3" />
                                <span>재개</span>
                            </button>
                        )}
                        <button
                            onClick={onCancel}
                            className="p-1.5 bg-surface-3 hover:bg-surface-4 text-danger border border-line rounded-[var(--radius-control)] transition-colors flex items-center gap-1 text-xs"
                            title="취소"
                        >
                            <Square className="w-3 h-3" />
                            <span>취소</span>
                        </button>
                    </div>
                )}

                {/* 재다운로드 버튼 (완료/에러 상태일 때만 표시) */}
                {(task.state === "completed" || task.state === "error") && (
                    <div className="flex gap-2">
                        <button
                            onClick={onRetry}
                            className="p-1.5 bg-surface-3 hover:bg-surface-4 text-info border border-line rounded-[var(--radius-control)] transition-colors flex items-center gap-1 text-xs"
                            title="다시 받기"
                        >
                            <RotateCw className="w-3 h-3" />
                                <span>다시 받기</span>
                        </button>
                        {task.state === "completed" && task.output_path && (
                            <button
                                onClick={onOpenLocation}
                                className="p-1.5 bg-surface-3 hover:bg-surface-4 text-ok border border-line rounded-[var(--radius-control)] transition-colors flex items-center gap-1 text-xs"
                                title="파일 위치 열기"
                            >
                                <FolderOpen className="w-3 h-3" />
                                <span>폴더 열기</span>
                            </button>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}
