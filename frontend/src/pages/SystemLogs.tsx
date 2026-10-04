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
} from "lucide-react";
import { clsx } from "clsx";
import { api, SystemLogFile } from "../api/client";
import { useToast } from "../components/ui/Toast";
import { Input, PageHeader } from "../components/ui/primitives";
import { formatBytes, formatDate as _formatDate } from "../utils/format";

function formatDate(iso: string): string {
    return _formatDate(iso, true);
}

export default function SystemLogs() {
    const [selectedFile, setSelectedFile] = useState<SystemLogFile | null>(null);
    const toast = useToast();

    return (
        <div className="flex flex-col gap-6 xl:h-[calc(100vh-4rem)]">
            <PageHeader
                icon={Terminal}
                eyebrow="Runtime observability"
                title="System Logs"
                description="실시간 서비스 로그와 일자별 백업을 검색하고 서버 상태를 추적합니다."
            />

            <div className="flex flex-col lg:flex-row flex-1 gap-4 min-h-[680px] xl:min-h-0">
                <div className="lg:w-[340px] xl:w-[30%] flex flex-col bg-surface-2 border border-line rounded-[var(--radius-card)] overflow-hidden surface-raise min-h-[260px]">
                    <LogFileListView 
                        selectedFile={selectedFile} 
                        onSelect={setSelectedFile} 
                        toast={toast} 
                    />
                </div>

                <div className="flex-1 flex flex-col bg-surface-2 border border-line rounded-[var(--radius-card)] overflow-hidden surface-raise min-h-[420px]">
                    {selectedFile === null ? (
                        <div className="flex-1 flex flex-col items-center justify-center text-ink-faint p-8 text-center">
                            <span className="w-14 h-14 rounded-2xl bg-surface-3 border border-line grid place-items-center mb-4"><Terminal className="w-6 h-6 opacity-60" /></span>
                            <p className="text-sm">왼쪽 목록에서 조회할 시스템 로그 파일을 선택하세요.</p>
                        </div>
                    ) : (
                        <LogContentViewer
                            file={selectedFile}
                            toast={toast}
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
    toast: ReturnType<typeof useToast>;
}

function LogFileListView({ selectedFile, onSelect, toast }: LogFileListViewProps) {
    const [files, setFiles] = useState<SystemLogFile[]>([]);
    const [loading, setLoading] = useState(true);

    const loadFiles = useCallback(async (silent = false) => {
        if (!silent) setLoading(true);
        try {
            const data = await api.getSystemLogFiles();
            setFiles(data);
            // 만약 선택된 파일이 없고 파일 목록이 존재하면 자동으로 가장 첫번째 파일(보통 실시간 로그인 service.log)을 선택
            if (!selectedFile && data.length > 0) {
                onSelect(data[0]);
            }
        } catch {
            toast.error("로그 파일 목록을 불러오는 데 실패했습니다.");
        } finally {
            if (!silent) setLoading(false);
        }
    }, [selectedFile, onSelect, toast]);

    useEffect(() => {
        loadFiles();
    }, []);

    if (loading) {
        return (
            <div className="flex flex-1 items-center justify-center text-ink-faint">
                <Loader2 className="w-5 h-5 animate-spin mr-2" />
                <span className="text-sm">로그 목록 불러오는 중...</span>
            </div>
        );
    }

    if (files.length === 0) {
        return (
            <div className="flex flex-col flex-1 items-center justify-center p-8 text-center">
                <Terminal className="w-8 h-8 text-ink-faint mb-3" />
                <p className="text-ink-muted font-medium text-sm mb-1">시스템 로그 파일이 없습니다.</p>
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
            
            <div className="flex-1 overflow-y-auto divide-y divide-line/50 scrollbar-thin">
                {files.map((file) => {
                    const isSelected = selectedFile?.filename === file.filename;
                    const isLive = file.filename === "service.log";
                    
                    return (
                        <div
                            key={file.filename}
                            onClick={() => onSelect(file)}
                            className={clsx(
                                "flex items-center gap-3 px-4 py-3.5 cursor-pointer transition-colors group",
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
                                            LIVE
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
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

// ── 로그 내용 뷰어 컴포넌트 ─────────────────────────────────

interface LogContentViewerProps {
    file: SystemLogFile;
    toast: ReturnType<typeof useToast>;
}

function LogContentViewer({ file, toast }: LogContentViewerProps) {
    const [content, setContent] = useState("");
    const [totalLines, setTotalLines] = useState(0);
    const [linesLimit, setLinesLimit] = useState(1000); // 기본 1000줄
    const [searchTerm, setSearchTerm] = useState("");
    const [loading, setLoading] = useState(false);
    
    // 자동 스크롤 및 자동 갱신 상태
    const [autoScroll, setAutoScroll] = useState(true);
    const [autoRefresh, setAutoRefresh] = useState(false);
    
    const terminalRef = useRef<HTMLDivElement>(null);
    const refreshTimerRef = useRef<NodeJS.Timeout | null>(null);

    const loadContent = useCallback(async (silent = false) => {
        if (!silent) setLoading(true);
        try {
            const data = await api.getSystemLogContent(file.filename, linesLimit);
            setContent(data.content);
            setTotalLines(data.total_lines);
        } catch {
            toast.error(`로그 내용을 불러오는 데 실패했습니다.`);
        } finally {
            if (!silent) setLoading(false);
        }
    }, [file.filename, linesLimit, toast]);

    // 파일이나 가져올 줄 수가 바뀌면 로그 다시 로드
    useEffect(() => {
        loadContent(false);
    }, [file.filename, linesLimit]);

    // 자동 갱신 타이머 관리
    useEffect(() => {
        if (autoRefresh) {
            refreshTimerRef.current = setInterval(() => {
                loadContent(true);
            }, 5000); // 5초 주기
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
                <div key={idx} className={clsx("py-0.5 whitespace-pre-wrap breakdown-all", colorClass)}>
                    {line}
                </div>
            );
        }

        const parts = line.split(new RegExp(`(${searchTerm})`, "gi"));
        return (
            <div key={idx} className={clsx("py-0.5 whitespace-pre-wrap breakdown-all", colorClass)}>
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

    return (
        <div className="flex-1 flex flex-col min-h-0 bg-surface-0">
            <div className="p-3 border-b border-line bg-surface-2 flex flex-wrap items-center justify-between gap-3 shrink-0">
                <div className="flex items-center gap-3">
                    <span className="text-xs font-mono font-semibold text-ink-muted">
                        {file.filename} ({lines.length}/{totalLines} 줄)
                    </span>
                    
                    {/* 불러올 줄 수 버튼그룹 */}
                    <div className="flex bg-surface-3 rounded p-0.5 border border-line">
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

                <div className="flex items-center gap-3">
                    {/* 검색 바 */}
                    <div className="relative">
                        <Search className="w-3.5 h-3.5 text-ink-faint absolute left-2.5 top-1/2 -translate-y-1/2" />
                        <Input
                            type="text"
                            placeholder="로그 검색..."
                            value={searchTerm}
                            onChange={(e) => setSearchTerm(e.target.value)}
                            className="text-xs pl-8 pr-3 py-1.5 w-40"
                        />
                    </div>

                    {/* 실시간 갱신 */}
                    <button
                        onClick={() => setAutoRefresh(!autoRefresh)}
                        className={clsx(
                            "flex items-center gap-1.5 px-2.5 py-1 text-xs font-bold rounded-lg border transition-all",
                            autoRefresh
                                ? "bg-ok/10 text-ok border-ok/30"
                                : "bg-surface-3 text-ink-muted border-line hover:bg-surface-4"
                        )}
                        title={autoRefresh ? "5초마다 자동 새로고침 중" : "자동 새로고침 켜기"}
                    >
                        {autoRefresh ? (
                            <>
                                <Loader2 className="w-3 h-3 animate-spin text-ok" />
                                <Pause className="w-3 h-3" />
                            </>
                        ) : (
                            <>
                                <Play className="w-3 h-3 text-ink-faint" />
                                <span className="text-[10px]">자동 갱신</span>
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
                    >
                        <ArrowDown className={clsx("w-3.5 h-3.5", autoScroll && "animate-bounce")} />
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

            {/* 터미널 로그 출력창 */}
            <div 
                ref={terminalRef}
                className="flex-1 p-4 overflow-y-auto font-mono text-[11px] leading-relaxed select-text scrollbar-thin"
            >
                {loading && content.length === 0 ? (
                    <div className="h-full flex items-center justify-center text-ink-faint">
                        <Loader2 className="w-6 h-6 animate-spin mr-2 text-[var(--primary)]" />
                        <span>로그 로드 중...</span>
                    </div>
                ) : lines.length === 0 ? (
                    <div className="h-full flex items-center justify-center text-ink-faint">
                        <span>로그 기록이 없습니다.</span>
                    </div>
                ) : (
                    lines.map((line, idx) => {
                        const colorClass = parseLogLine(line);
                        return renderLineWithHighlight(line, colorClass, idx);
                    })
                )}
            </div>
        </div>
    );
}
