import { useState, useRef, useEffect } from "react";
import {
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
    Trash2,
} from "lucide-react";
import { useVod } from "../contexts/VodContext";
import { api, VodTask } from "../api/client";
import { useToast } from "../components/ui/Toast";
import { useConfirm } from "../components/ui/ConfirmModal";
import { Badge, Button, EmptyState, Field, Input, PageHeader } from "../components/ui/primitives";
import { clsx } from "clsx";
import { formatDuration } from "../utils/format";
import { getErrorMessage } from "../utils/error";

export default function VodDownload() {
    const { tasks, activeCount, addTask, cancelTask, pauseTask, resumeTask, retryTask, clearCompleted, openFileLocation } = useVod();
    const [url, setUrl] = useState("");
    const [loading, setLoading] = useState(false);
    const [draggedIndex, setDraggedIndex] = useState<number | null>(null);
    const [isInitialLoad, setIsInitialLoad] = useState(true);
    const toast = useToast();
    const confirm = useConfirm();

    useEffect(() => {
        const timer = setTimeout(() => setIsInitialLoad(false), 500);
        return () => clearTimeout(timer);
    }, []);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!url) return;

        setLoading(true);

        try {
            await addTask(url);
            setUrl("");
            toast.success("다운로드가 시작되었습니다.");
        } catch (err: unknown) {
            toast.error(getErrorMessage(err, "다운로드 시작에 실패했습니다."));
        } finally {
            setLoading(false);
        }
    };

    const handleCancel = async (taskId: string, title: string) => {
        const ok = await confirm({
            title: "다운로드 취소",
            message: `'${title}' 다운로드를 취소할까요?`,
            confirmText: "중단",
            variant: "danger",
        });
        if (ok) cancelTask(taskId);
    };

    const handleRetry = async (taskId: string, title: string) => {
        const ok = await confirm({
            title: "재다운로드",
            message: `'${title}'을(를) 다시 다운로드할까요?`,
            confirmText: "재다운로드",
        });
        if (ok) retryTask(taskId);
    };

    const handleClearCompleted = async () => {
        const ok = await confirm({
            title: "완료된 작업 정리",
            message: "완료 및 오류 상태의 작업을 모두 삭제할까요?",
            confirmText: "정리",
            variant: "danger",
        });
        if (ok) clearCompleted();
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
                eyebrow="Download queue"
                title="VOD Downloader"
                description="치지직 VOD와 클립, 외부 영상 주소를 대기열에 추가하고 진행 상황을 관리합니다."
                meta={(
                    <>
                        <Badge tone={activeCount > 0 ? "ok" : "neutral"}>{activeCount} active</Badge>
                        <Badge tone="neutral">{tasks.length} total</Badge>
                    </>
                )}
            />

            <form
                onSubmit={handleSubmit}
                className="relative overflow-hidden bg-surface-2 p-5 sm:p-6 rounded-[var(--radius-card)] border border-line surface-raise space-y-4"
            >
                <span className="absolute inset-x-0 top-0 h-px bg-linear-to-r from-transparent via-[var(--primary)] to-transparent opacity-70" />
                <Field label="영상 URL" htmlFor="vod-url" hint="치지직 VOD·클립 및 yt-dlp가 지원하는 외부 영상 링크를 사용할 수 있습니다.">
                    <div className="flex flex-col sm:flex-row gap-2">
                        <Input
                            id="vod-url"
                            type="url"
                            className="flex-1"
                            placeholder="https://chzzk.naver.com/video/..."
                            value={url}
                            onChange={(event) => setUrl(event.target.value)}
                            autoComplete="off"
                        />
                        <Button type="submit" icon={Download} loading={loading} disabled={!url} variant="primary" className="sm:px-5">
                            다운로드 시작
                        </Button>
                    </div>
                </Field>

                <div className="flex flex-wrap gap-2 pt-1">
                    {["1080p60 지원", "MP4 자동 리먹싱", "클립 다운로드", "다중 대기열"].map((feature) => (
                        <span key={feature} className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-surface-3 border border-line text-[11px] text-ink-faint">
                            <CheckCircle className="w-3 h-3 text-ok" /> {feature}
                        </span>
                    ))}
                </div>
            </form>

            <div className="space-y-4">
                <div className="flex items-center justify-between">
                    <h3 className="text-base font-semibold text-ink flex items-center gap-2">
                        다운로드 목록
                        <Badge tone="neutral">{tasks.length}</Badge>
                    </h3>
                    {tasks.some(t => t.state === "completed" || t.state === "error") && (
                        <Button icon={Trash2} onClick={handleClearCompleted}>완료된 작업 정리</Button>
                    )}
                </div>

                {isInitialLoad ? (
                    <div className="space-y-3">
                        {[1, 2, 3].map(i => (
                            <div key={i} className="bg-surface-2 border border-line p-4 rounded-[var(--radius-card)] flex items-start gap-4 animate-pulse">
                                <div className="w-24 h-20 bg-surface-3 rounded-[var(--radius-control)] shrink-0" />
                                <div className="flex-1 space-y-3 pt-2">
                                    <div className="skeleton h-4 rounded w-1/3" />
                                    <div className="skeleton w-full h-2 rounded-full" />
                                    <div className="skeleton h-3 rounded w-1/4" />
                                </div>
                            </div>
                        ))}
                    </div>
                ) : tasks.length === 0 ? (
                    <EmptyState icon={FileVideo} title="대기열이 비어 있습니다" description="위에 영상 URL을 입력하면 다운로드 작업이 이곳에 표시됩니다." />
                ) : (
                    <div className="space-y-3">
                        {tasks.map((task, index) => (
                            <div
                                key={task.task_id}
                                draggable
                                onDragStart={() => handleDragStart(index)}
                                onDragOver={(e) => handleDragOver(e, index)}
                                onDrop={(e) => handleDrop(e, index)}
                                className={clsx(
                                    "transition-opacity",
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
        <div className="bg-surface-2 border border-line p-4 rounded-[var(--radius-card)] flex items-start gap-4 hover:border-line-strong transition-colors surface-raise">
            {/* 드래그 핸들 */}
            <div className="flex items-center justify-center text-ink-faint hover:text-ink-muted cursor-grab active:cursor-grabbing pt-8">
                <GripVertical className="w-5 h-5" />
            </div>

            {/* 상태 아이콘 영역 */}
            <div className="w-24 h-20 bg-surface-1 border border-line rounded-[var(--radius-control)] flex items-center justify-center flex-shrink-0">
                {task.state === "completed" && <CheckCircle className="text-ok w-8 h-8" />}
                {task.state === "downloading" && (
                    <div className="text-ink font-mono font-bold text-lg">
                        {Math.round(task.progress)}%
                    </div>
                )}
                {task.state === "paused" && <Pause className="text-warn w-8 h-8" />}
                {task.state === "error" && <AlertCircle className="text-danger w-8 h-8" />}
                {task.state === "idle" && <Clock className="text-ink-faint w-8 h-8" />}
                {task.state === "cancelling" && (
                    <Loader2 className="text-danger w-6 h-6 animate-spin" />
                )}
            </div>

            <div className="flex-1 min-w-0 w-full space-y-2">
                <div className="flex justify-between items-start gap-2">
                    <h4 className="font-semibold text-ink truncate text-sm flex-1">
                        {task.title}
                    </h4>
                    <span
                        className={clsx(
                            "text-[11px] font-medium px-2 py-1 rounded-full border capitalize whitespace-nowrap",
                            statusBadgeClass
                        )}
                    >
                        {statusLabels[task.state] || task.state}
                    </span>
                </div>

                <div className="text-xs text-ink-faint font-mono flex flex-wrap gap-x-4">
                    <span>화질: {task.quality}</span>
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
                            title="재다운로드"
                        >
                            <RotateCw className="w-3 h-3" />
                            <span>재다운로드</span>
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
