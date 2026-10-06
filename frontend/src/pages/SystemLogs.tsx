import { useState, useEffect, useCallback, useRef } from "react";
import {
    Terminal,
    Search,
    RefreshCw,
    FileText,
    Loader2,
    ArrowDown,
    Play,
    Pause,
    Trash2,
    AlertCircle,
    ChevronLeft,
} from "lucide-react";
import { clsx } from "clsx";
import { api, SystemLogFile } from "../api/client";
import { useToast } from "../components/ui/Toast";
import { useLanguage } from "../contexts/LanguageContext";
import { useConfirm } from "../components/ui/ConfirmModal";
import { Button, EmptyState, Input, LoadingState, PageHeader } from "../components/ui/primitives";
import { formatBytes, formatDate as _formatDate } from "../utils/format";

function formatDate(iso: string): string {
    return _formatDate(iso, true);
}

export default function SystemLogs() {
    const { t } = useLanguage();
    const [selectedFile, setSelectedFile] = useState<SystemLogFile | null>(null);
    const [listRefreshKey, setListRefreshKey] = useState(0);
    const [clearing, setClearing] = useState(false);
    const toast = useToast();
    const confirm = useConfirm();

    const handleClearLogs = async () => {
        const ok = await confirm({
            title: "로그 초기화",
            message: "현재 로그와 날짜별 백업 로그를 모두 비웁니다. 초기화 후 발생하는 새 로그는 계속 저장됩니다.",
            confirmText: "로그 초기화",
            variant: "danger",
        });
        if (!ok) return;

        setClearing(true);
        try {
            const result = await api.clearSystemLogs();
            setSelectedFile(null);
            setListRefreshKey((value) => value + 1);
            toast.success(result.message);
        } catch {
            toast.error("로그 초기화에 실패했습니다.");
        } finally {
            setClearing(false);
        }
    };

    return (
        <div className="product-page flex flex-col gap-4 lg:h-[calc(100dvh-6.5rem)]">
            <PageHeader
                icon={Terminal}
                eyebrow={t("서비스 상태 확인")}
                title={t("로그")}
                description={t("실시간 서비스 로그와 일자별 백업을 검색하고 서버 상태를 추적합니다.")}
                actions={(
                    <Button
                        icon={Trash2}
                        variant="danger"
                        loading={clearing}
                        onClick={handleClearLogs}
                    >
                        {t("로그 초기화")}
                    </Button>
                )}
            />

            <div className="flex flex-col lg:flex-row flex-1 gap-4 min-h-[440px] lg:min-h-0">
                <div className={clsx("shrink-0 flex flex-col bg-surface-2 border border-line rounded-[var(--radius-card)] overflow-hidden surface-raise min-h-[178px] max-h-[290px] lg:w-[260px] lg:min-h-0 lg:max-h-none", selectedFile && "hidden lg:flex")}>
                    <LogFileListView 
                        selectedFile={selectedFile} 
                        onSelect={setSelectedFile} 
                        refreshKey={listRefreshKey}
                    />
                </div>

                <div className={clsx("flex-1 flex flex-col bg-surface-2 border border-line rounded-[var(--radius-card)] overflow-hidden surface-raise min-w-0 min-h-[320px] lg:min-h-0", !selectedFile && "hidden lg:flex")}>
                    {selectedFile && <div className="flex min-h-12 items-center gap-3 border-b border-line px-4 py-2 text-xs font-semibold text-ink-muted lg:hidden"><button type="button" onClick={() => setSelectedFile(null)} className="inline-flex min-h-11 items-center gap-1.5 text-ink-muted hover:text-ink"><ChevronLeft className="size-4" />로그 파일</button><span className="truncate">{selectedFile.filename}</span></div>}
                    {selectedFile === null ? (
                        <div className="flex-1 flex flex-col items-center justify-center text-ink-faint p-8 text-center">
                            <span className="w-8 h-8 grid place-items-center mb-4"><Terminal className="w-6 h-6 opacity-60" /></span>
                            <p className="text-sm">왼쪽 목록에서 조회할 로그 파일을 선택하세요.</p>
                        </div>
                    ) : (
                        <LogContentViewer
                            file={selectedFile}
                        />
                    )}
                </div>
            </div>
        </div>
    );
}

// ── 로그 파일 목록 컴포넌트 ─────────────────────────────────

interface LogFileListViewProps {
    selectedFile: SystemLogFile | null;
    onSelect: (file: SystemLogFile) => void;
    refreshKey: number;
}

function LogFileListView({ selectedFile, onSelect, refreshKey }: LogFileListViewProps) {
    const { t } = useLanguage();
    const [files, setFiles] = useState<SystemLogFile[]>([]);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState(false);

    const loadFiles = useCallback(async (silent = false) => {
        if (!silent) setLoading(true);
        try {
            const data = await api.getSystemLogFiles();
            setFiles(data);
            setLoadError(false);
            // 만약 선택된 파일이 없고 파일 목록이 존재하면 자동으로 가장 첫번째 파일(보통 실시간 로그인 service.log)을 선택
            if (!selectedFile && data.length > 0) {
                onSelect(data[0]);
            }
        } catch {
            if (!silent) setLoadError(true);
        } finally {
            if (!silent) setLoading(false);
        }
    }, [selectedFile, onSelect]);

    useEffect(() => {
        void loadFiles();
        const timer = window.setInterval(() => {
            void loadFiles(true);
        }, 5000);
        return () => window.clearInterval(timer);
    }, [refreshKey, loadFiles]);

    if (loading && files.length === 0) return <LoadingState label="로그 목록을 불러오는 중" />;

    if (files.length === 0) {
        if (loadError) {
            return <EmptyState icon={AlertCircle} title={t("로그 목록을 불러오지 못했습니다.")} description={t("서버 연결을 확인한 뒤 다시 시도해 주세요.")} action={<Button icon={RefreshCw} onClick={() => void loadFiles()}>{t("다시 시도")}</Button>} />;
        }
        return (
            <div className="flex flex-col flex-1 items-center justify-center p-8 text-center">
                <Terminal className="w-8 h-8 text-ink-faint mb-3" />
                <p className="text-ink-muted font-medium text-sm mb-1">로그 파일이 없습니다.</p>
            </div>
        );
    }

    return (
        <div className="flex-1 flex flex-col min-h-0">
            <div className="p-3 border-b border-line bg-surface-2 flex items-center justify-between shrink-0">
                <span className="text-xs font-semibold text-ink-muted">로그 파일 목록</span>
                <button 
                    onClick={() => loadFiles(false)} 
                    className="p-1.5 hover:bg-surface-3 rounded transition-colors text-ink-faint hover:text-ink"
                    title="목록 새로고침"
                >
                    <RefreshCw className="w-3.5 h-3.5" />
                </button>
            </div>
            
            <div className="flex-1 overflow-y-auto divide-y divide-line/50 scrollbar-thin ">
                {files.map((file) => {
                    const isSelected = selectedFile?.filename === file.filename;
                    const isLive = file.filename === "service.log";
                    
                    return (
                        <button
                            type="button"
                            key={file.filename}
                            onClick={() => onSelect(file)}
                            aria-pressed={isSelected}
                            className={clsx(
                                "flex w-full items-center gap-3 px-4 py-3.5 text-left transition-colors group ",
                                isSelected ? "btn-ghost-primary" : "hover:bg-surface-3/70"
                            )}
                        >
                            <FileText className={clsx(
                                "w-4 h-4 shrink-0", 
                                isSelected ? "text-[var(--primary)]" : "text-ink-faint group-hover:text-ink-muted"
                            )} />

                            <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 mb-0.5">
                                    <p className={clsx(
                                        "text-xs font-bold truncate transition-colors",
                                        isSelected ? "text-ink" : "text-ink-muted group-hover:text-ink"
                                    )}>
                                        {file.filename}
                                    </p>
                                    {isLive && (
                                        <span className="px-1.5 py-0.5 bg-ok/15 text-ok border border-ok/20 text-[9px] font-extrabold rounded uppercase tracking-wider animate-pulse">
                                            {t("실시간")}
                                        </span>
                                    )}
                                </div>
                                <p className="text-[10px] text-ink-faint">
                                    수정: {formatDate(file.modified_at)}
                                </p>
                            </div>

                            <span className="text-[10px] font-mono text-ink-faint shrink-0">
                                {formatBytes(file.size_bytes)}
                            </span>
                        </button>
                    );
                })}
            </div>
        </div>
    );
}

// ── 로그 내용 뷰어 컴포넌트 ─────────────────────────────────

interface LogContentViewerProps { file: SystemLogFile }

function LogContentViewer({ file }: LogContentViewerProps) {
    const { t } = useLanguage();
    const [content, setContent] = useState("");
    const [totalLines, setTotalLines] = useState(0);
    const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null);
    const [linesLimit, setLinesLimit] = useState(1000); // 기본 1000줄
    const [searchTerm, setSearchTerm] = useState("");
    const [loading, setLoading] = useState(false);
    const [loadError, setLoadError] = useState(false);
    
    // 자동 스크롤 및 자동 갱신 상태
    const [autoScroll, setAutoScroll] = useState(true);
    const [autoRefresh, setAutoRefresh] = useState(file.filename === "service.log");

    const terminalRef = useRef<HTMLDivElement>(null);
    const refreshTimerRef = useRef<NodeJS.Timeout | null>(null);
    const requestInFlightRef = useRef(false);

    const loadContent = useCallback(async (silent = false) => {
        if (requestInFlightRef.current) return;
        requestInFlightRef.current = true;
        if (!silent) setLoading(true);
        try {
            const data = await api.getSystemLogContent(file.filename, linesLimit);
            setContent(data.content);
            setTotalLines(data.total_lines);
            setLastUpdatedAt(new Date());
            setLoadError(false);
        } catch {
            if (!silent) setLoadError(true);
        } finally {
            requestInFlightRef.current = false;
            if (!silent) setLoading(false);
        }
    }, [file.filename, linesLimit]);

    useEffect(() => {
        setAutoRefresh(file.filename === "service.log");
    }, [file.filename]);

    // 파일이나 가져올 줄 수가 바뀌면 로그 다시 로드
    useEffect(() => {
        loadContent(false);
    }, [file.filename, linesLimit]);

    // 자동 갱신 타이머 관리
    useEffect(() => {
        if (autoRefresh) {
            refreshTimerRef.current = setInterval(() => {
                loadContent(true);
            }, 2000); // live log polling interval
        } else {
            if (refreshTimerRef.current) {
                clearInterval(refreshTimerRef.current);
                refreshTimerRef.current = null;
            }
        }
        
        return () => {
            if (refreshTimerRef.current) {
                clearInterval(refreshTimerRef.current);
            }
        };
    }, [autoRefresh, loadContent]);

    // 자동 스크롤 수행
    useEffect(() => {
        if (autoScroll && terminalRef.current) {
            terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
        }
    }, [content, autoScroll]);

    // 로그 한 줄을 파싱하여 레벨에 따른 색상 매핑
    const parseLogLine = (line: string) => {
        let colorClass = "text-ink-muted"; // 기본값
        
        if (line.includes(" | ERROR    |") || line.includes(" | ERROR |")) {
            colorClass = "text-danger font-semibold";
        } else if (line.includes(" | WARNING  |") || line.includes(" | WARNING |") || line.includes(" | WARN |")) {
            colorClass = "text-warn";
        } else if (line.includes(" | DEBUG    |") || line.includes(" | DEBUG |")) {
            colorClass = "text-ink-faint";
        } else if (line.includes(" | INFO     |") || line.includes(" | INFO |")) {
            colorClass = "text-ink-muted";
        }
        
        return colorClass;
    };

    // 검색어 강조 렌더링
    const renderLineWithHighlight = (line: string, colorClass: string, idx: number) => {
        if (!searchTerm) {
            return (
                <div key={idx} className={clsx("py-0.5 whitespace-pre-wrap break-all", colorClass)}>
                    {line}
                </div>
            );
        }

        const escapedSearchTerm = searchTerm.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        const parts = line.split(new RegExp(`(${escapedSearchTerm})`, "gi"));
        return (
            <div key={idx} className={clsx("py-0.5 whitespace-pre-wrap break-all", colorClass)}>
                {parts.map((part, i) => 
                    part.toLowerCase() === searchTerm.toLowerCase() ? (
                        <mark key={i} className="bg-warn/25 text-warn px-0.5 rounded border-b border-warn/50">
                            {part}
                        </mark>
                    ) : (
                        part
                    )
                )}
            </div>
        );
    };

    const lines = content.split("\n");
    // 마지막 줄이 개행으로 끝나 분리되어 생긴 빈 줄 제거
    if (lines.length > 0 && lines[lines.length - 1] === "") {
        lines.pop();
    }
    const visibleLines = searchTerm
        ? lines.filter((line) => line.toLowerCase().includes(searchTerm.toLowerCase()))
        : lines;

    return (
        <div className="flex-1 flex flex-col min-h-0 bg-surface-0">
            <div className="p-3 border-b border-line bg-surface-2 flex flex-wrap items-center justify-between gap-3 shrink-0">
                <div className="log-toolbar-row w-full justify-between">
                    <span className="text-xs font-mono font-semibold text-ink-muted">
                        {file.filename} ({visibleLines.length}/{totalLines} 줄)
                    </span>
                    {lastUpdatedAt && (
                        <span className="text-[10px] text-ink-faint" aria-live="polite">
                            갱신 {lastUpdatedAt.toLocaleTimeString()}
                        </span>
                    )}

                    {/* 불러올 줄 수 버튼그룹: 파일명 줄의 오른쪽 */}
                    <div className="ml-auto flex shrink-0 bg-surface-3 rounded p-0.5 border border-line">
                        {[100, 500, 1000, 0].map((val) => (
                            <button
                                key={val}
                                onClick={() => setLinesLimit(val)}
                                className={clsx(
                                    "px-2 py-1 text-[10px] font-bold rounded transition-colors",
                                    linesLimit === val
                                        ? "btn-ghost-primary"
                                        : "text-ink-faint hover:text-ink"
                                )}
                            >
                                {val === 0 ? "전체" : `${val}줄`}
                            </button>
                        ))}
                    </div>
                </div>

                <div className="log-toolbar-row w-full justify-between">
                    {/* 검색 바 */}
                    <div className="relative">
                        <Search className="w-3.5 h-3.5 text-ink-faint absolute left-2.5 top-1/2 -translate-y-1/2" />
                        <Input
                            type="text"
                            placeholder="로그 검색..."
                            aria-label="로그 검색"
                            value={searchTerm}
                            onChange={(e) => setSearchTerm(e.target.value)}
                            className="text-xs pl-8 pr-3 py-1.5 w-40"
                        />
                    </div>

                    <div className="flex flex-wrap items-center gap-2">
                        {/* 실시간 갱신 */}
                        <button
                        onClick={() => setAutoRefresh(!autoRefresh)}
                        className={clsx(
                            "flex items-center gap-1.5 px-2.5 py-1 text-xs font-bold rounded-lg border transition-all",
                            autoRefresh
                                ? "bg-ok/10 text-ok border-ok/30"
                                : "bg-surface-3 text-ink-muted border-line hover:bg-surface-4"
                        )}
                        title={autoRefresh ? "2초마다 실시간 갱신 중" : "실시간 갱신 켜기"}
                        aria-label={autoRefresh ? "실시간 갱신 끄기" : "실시간 갱신 켜기"}
                        >
                        {autoRefresh ? (
                            <>
                                <span className="size-1.5 rounded-full bg-ok" aria-hidden="true" />
                                <Pause className="w-3 h-3" />
                                <span className="text-[10px]">실시간</span>
                            </>
                        ) : (
                            <>
                                <Play className="w-3 h-3 text-ink-faint" />
                                <span className="text-[10px]">실시간 갱신</span>
                            </>
                        )}
                        </button>

                        {/* 자동 스크롤 */}
                        <button
                        onClick={() => setAutoScroll(!autoScroll)}
                        className={clsx(
                            "p-1.5 rounded-lg border transition-colors",
                            autoScroll
                                ? "bg-ok/10 text-ok border-ok/30"
                                : "bg-surface-3 text-ink-muted border-line hover:bg-surface-4 hover:text-ink"
                        )}
                        title="자동 최하단 스크롤"
                        aria-label="자동 최하단 스크롤"
                        aria-pressed={autoScroll}
                        >
                        <ArrowDown className="w-3.5 h-3.5" />
                        </button>

                        {/* 수동 새로고침 */}
                        <button
                        onClick={() => loadContent(false)}
                        disabled={loading}
                        className="p-1.5 bg-surface-3 border border-line hover:bg-surface-4 text-ink-muted hover:text-ink rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        title="새로고침"
                        >
                        <RefreshCw className={clsx("w-3.5 h-3.5", loading && "animate-spin")} />
                        </button>
                    </div>
                </div>
            </div>

            {loadError && content.length > 0 && <div role="status" className="flex flex-wrap items-center justify-between gap-2 border-b border-warn/20 bg-warn/5 px-4 py-2 text-xs text-ink-muted"><span>{t("로그 갱신에 실패했습니다. 기존 내용을 표시합니다.")}</span><Button icon={RefreshCw} onClick={() => void loadContent()}>{t("다시 시도")}</Button></div>}

            {/* 터미널 로그 출력창 */}
            <div 
                ref={terminalRef}
                className="log-viewer flex-1 min-w-0 p-3 overflow-y-auto font-mono text-[11px] leading-relaxed select-text scrollbar-thin"
            >
                {loading && content.length === 0 ? (
                    <div className="h-full flex items-center justify-center text-ink-faint">
                        <Loader2 className="w-6 h-6 animate-spin mr-2 text-[var(--primary)]" />
                        <span>로그 로드 중...</span>
                    </div>
                ) : loadError && content.length === 0 ? (
                    <div className="flex h-full items-center justify-center">
                        <EmptyState icon={AlertCircle} title={t("로그 내용을 불러오지 못했습니다.")} description={t("서버 연결을 확인한 뒤 다시 시도해 주세요.")} compact action={<Button icon={RefreshCw} onClick={() => void loadContent()}>{t("다시 시도")}</Button>} />
                    </div>
                ) : lines.length === 0 ? (
                    <div className="h-full flex items-center justify-center text-ink-faint">
                        <span>{autoRefresh ? "로그 기록이 없습니다. 새 로그를 기다리는 중입니다." : "로그 기록이 없습니다."}</span>
                    </div>
                ) : visibleLines.length === 0 ? (
                    <div className="h-full flex items-center justify-center text-ink-faint">
                        <span>검색 결과가 없습니다.</span>
                    </div>
                ) : (
                    visibleLines.map((line, idx) => {
                        const colorClass = parseLogLine(line);
                        return renderLineWithHighlight(line, colorClass, idx);
                    })
                )}
            </div>
        </div>
    );
}
