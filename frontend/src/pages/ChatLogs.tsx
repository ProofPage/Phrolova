import { useState, useEffect, useCallback } from "react";
import {
    MessageSquare,
    Search,
    Download,
    FileText,
    Loader2,
    X,
    ChevronLeft,
    ChevronRight,
    FolderOpen,
} from "lucide-react";
import { clsx } from "clsx";
import { api, ChatLogFile, ChatMessageItem, MessagesResponse } from "../api/client";
import { useToast } from "../components/ui/Toast";
import { Button, Input, PageHeader } from "../components/ui/primitives";
import { formatBytes, formatDate as _formatDate, formatTime } from "../utils/format";

function formatDate(iso: string): string {
    return _formatDate(iso, true);
}

// ── 메인 페이지 ──────────────────────────────────────────

export default function ChatLogs() {
    const [selectedFile, setSelectedFile] = useState<ChatLogFile | null>(null);
    const toast = useToast();

    return (
        <div className="flex flex-col gap-6 xl:h-[calc(100vh-4rem)]">
            <PageHeader
                icon={MessageSquare}
                eyebrow="Conversation archive"
                title="Chat Logs"
                description="녹화 중 수집한 채팅을 채널과 세션별로 찾아보고 원본 로그를 내려받습니다."
            />

            <div className="flex flex-col lg:flex-row flex-1 gap-4 min-h-[680px] xl:min-h-0">
                <div className="lg:w-[340px] xl:w-[30%] flex flex-col bg-surface-2 border border-line rounded-[var(--radius-card)] overflow-hidden surface-raise min-h-[260px]">
                    <FileListView 
                        selectedFile={selectedFile} 
                        onSelect={setSelectedFile} 
                        toast={toast} 
                    />
                </div>

                <div className="flex-1 flex flex-col bg-surface-2 border border-line rounded-[var(--radius-card)] overflow-hidden surface-raise min-h-[420px]">
                    {selectedFile === null ? (
                        <div className="flex-1 flex flex-col items-center justify-center text-ink-faint p-8 text-center">
                            <span className="w-14 h-14 rounded-2xl bg-surface-3 border border-line grid place-items-center mb-4"><MessageSquare className="w-6 h-6 opacity-60" /></span>
                            <p className="text-sm">왼쪽 목록에서 채팅 로그 파일을 선택하세요.</p>
                        </div>
                    ) : (
                        <MessageViewer
                            file={selectedFile}
                            toast={toast}
                        />
                    )}
                </div>
            </div>
        </div>
    );
}

// ── 파일 목록 뷰 ────────────────────────────────────────

interface FileListViewProps {
    selectedFile: ChatLogFile | null;
    onSelect: (file: ChatLogFile) => void;
    toast: ReturnType<typeof useToast>;
}

function FileListView({ selectedFile, onSelect, toast }: FileListViewProps) {
    const [files, setFiles] = useState<ChatLogFile[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        loadFiles();
    }, []);

    const loadFiles = async () => {
        setLoading(true);
        try {
            const data = await api.getChatFiles();
            setFiles(data);
        } catch {
            toast.error("채팅 로그 파일 목록을 불러오는 데 실패했습니다.");
        } finally {
            setLoading(false);
        }
    };

    const grouped = files.reduce<Record<string, ChatLogFile[]>>((acc, f) => {
        if (!acc[f.channel]) acc[f.channel] = [];
        acc[f.channel].push(f);
        return acc;
    }, {});

    if (loading) {
        return (
            <div className="flex flex-1 items-center justify-center text-ink-faint">
                <Loader2 className="w-5 h-5 animate-spin mr-2" />
                <span className="text-sm">목록 불러오는 중...</span>
            </div>
        );
    }

    if (files.length === 0) {
        return (
            <div className="flex flex-col flex-1 items-center justify-center p-8 text-center">
                <MessageSquare className="w-8 h-8 text-ink-faint mb-3" />
                <p className="text-ink-muted font-medium text-sm mb-1">채팅 로그가 없습니다.</p>
            </div>
        );
    }

    return (
        <div className="flex-1 overflow-y-auto scrollbar-thin">
            {Object.entries(grouped).map(([channel, channelFiles]) => (
                <div key={channel} className="border-b border-line/70 last:border-0">
                    <div className="sticky top-0 z-10 flex items-center gap-2 px-4 py-2.5 bg-surface-2/95 backdrop-blur-md border-b border-line">
                        <FolderOpen className="w-4 h-4 text-info" />
                        <span className="text-xs font-semibold text-ink-muted truncate">{channel}</span>
                        <span className="text-[10px] text-ink-faint ml-auto font-mono">
                            {channelFiles.length}
                        </span>
                    </div>

                    <div className="divide-y divide-line/50">
                        {channelFiles.map((file) => {
                            const isSelected = selectedFile?.file_id === file.file_id;
                            return (
                                <div
                                    key={file.file_id}
                                    onClick={() => onSelect(file)}
                                    className={clsx(
                                        "flex items-center gap-3 px-4 py-3 cursor-pointer transition-colors group",
                                        isSelected ? "btn-ghost-primary" : "hover:bg-surface-3/70"
                                    )}
                                >
                                    <FileText className={clsx(
                                        "w-4 h-4 shrink-0", 
                                        isSelected ? "text-[var(--primary)]" : "text-ink-faint group-hover:text-ink-muted"
                                    )} />

                                    <div className="flex-1 min-w-0">
                                        <p className={clsx(
                                            "text-xs font-medium truncate transition-colors",
                                            isSelected ? "text-ink" : "text-ink-muted group-hover:text-ink"
                                        )}>
                                            {file.filename}
                                        </p>
                                        <div className="flex items-center gap-2 mt-1">
                                            <p className="text-[10px] text-ink-faint">
                                                {formatDate(file.created_at)}
                                            </p>
                                            <span className="text-[10px] text-ink-faint font-mono">
                                                {formatBytes(file.size_bytes)}
                                            </span>
                                        </div>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            ))}
        </div>
    );
}

// ── 메시지 뷰어 ─────────────────────────────────────────

interface MessageViewerProps {
    file: ChatLogFile;
    toast: ReturnType<typeof useToast>;
}

function MessageViewer({ file, toast }: MessageViewerProps) {
    const [data, setData] = useState<MessagesResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [page, setPage] = useState(1);

    const [pendingSearch, setPendingSearch] = useState("");
    const [pendingNickname, setPendingNickname] = useState("");
    const [appliedSearch, setAppliedSearch] = useState("");
    const [appliedNickname, setAppliedNickname] = useState("");

    const LIMIT = 100;

    const loadMessages = useCallback(async (
        targetPage: number,
        search: string,
        nickname: string,
    ) => {
        setLoading(true);
        try {
            const res = await api.getChatMessages(file.file_id, {
                page: targetPage,
                limit: LIMIT,
                search: search || undefined,
                nickname: nickname || undefined,
            });
            setData(res);
        } catch {
            toast.error("메시지를 불러오는 데 실패했습니다.");
        } finally {
            setLoading(false);
        }
    }, [file.file_id, toast]);

    useEffect(() => {
        loadMessages(page, appliedSearch, appliedNickname);
    }, [page, appliedSearch, appliedNickname, loadMessages]);

    // 파일이 변경되면 필터와 페이지 초기화
    useEffect(() => {
        setPage(1);
        setPendingSearch("");
        setPendingNickname("");
        setAppliedSearch("");
        setAppliedNickname("");
    }, [file.file_id]);

    const handleSearch = () => {
        setAppliedSearch(pendingSearch);
        setAppliedNickname(pendingNickname);
        setPage(1);
    };

    const handleClearSearch = () => {
        setPendingSearch("");
        setPendingNickname("");
        setAppliedSearch("");
        setAppliedNickname("");
        setPage(1);
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === "Enter") handleSearch();
    };

    const hasFilter = appliedSearch || appliedNickname;

    return (
        <div className="flex flex-col h-full bg-surface-1/30">
            <div className="flex items-center gap-3 p-4 border-b border-line bg-surface-2 shrink-0">
                <div className="min-w-0 flex-1">
                    <h3 className="text-sm font-semibold text-ink truncate">{file.filename}</h3>
                    <p className="text-[11px] text-ink-faint mt-0.5">{file.message_count.toLocaleString()}개 메시지</p>
                </div>
                <a
                    href={api.getChatDownloadUrl(file.file_id)}
                    download={file.filename}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-[var(--radius-control)] text-xs text-ink-muted hover:text-ink hover:bg-surface-3 border border-line transition-colors shrink-0"
                    title="JSONL 파일 다운로드"
                >
                    <Download className="w-3.5 h-3.5" />
                    다운로드
                </a>
            </div>

            <div className="p-3 border-b border-line bg-surface-2/70 shrink-0 flex flex-wrap gap-2">
                <div className="flex items-center gap-2 w-full sm:w-auto flex-1">
                    <div className="relative flex-1">
                        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-ink-faint" />
                        <Input
                            type="text"
                            value={pendingSearch}
                            onChange={(e) => setPendingSearch(e.target.value)}
                            onKeyDown={handleKeyDown}
                            placeholder="내용 검색..."
                            className="w-full pl-8 pr-3 py-1.5 text-xs"
                        />
                    </div>
                    <div className="w-1/3 min-w-[100px]">
                        <Input
                            type="text"
                            value={pendingNickname}
                            onChange={(e) => setPendingNickname(e.target.value)}
                            onKeyDown={handleKeyDown}
                            placeholder="닉네임..."
                            className="w-full px-3 py-1.5 text-xs"
                        />
                    </div>
                    <Button icon={Search} onClick={handleSearch} variant="primary" className="px-3 py-1.5 text-xs shrink-0">적용</Button>
                    {hasFilter && (
                        <button
                            onClick={handleClearSearch}
                            className="p-1.5 text-ink-faint hover:text-ink bg-surface-3 hover:bg-surface-4 rounded-md transition-colors shrink-0"
                            title="검색 초기화"
                        >
                            <X className="w-3.5 h-3.5" />
                        </button>
                    )}
                </div>
            </div>

            <div className="flex-1 overflow-y-auto bg-surface-0/45 relative min-h-0">
                {loading && (
                    <div className="absolute inset-0 z-10 bg-surface-0/65 backdrop-blur-[1px] flex items-center justify-center text-ink-faint">
                        <Loader2 className="w-5 h-5 animate-spin mr-2" />
                        <span className="text-sm">불러오는 중...</span>
                    </div>
                )}
                
                {!data || data.messages.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-full text-ink-faint">
                        <MessageSquare className="w-8 h-8 mb-3 opacity-20" />
                        <p className="text-sm">{hasFilter ? "검색 결과가 없습니다." : "메시지가 없습니다."}</p>
                    </div>
                ) : (
                    <div className="divide-y divide-line/40 py-2">
                        {data.messages.map((msg, idx) => (
                            <MessageRow key={idx} msg={msg} />
                        ))}
                    </div>
                )}
            </div>

            {data && data.total > 0 && (
                <div className="flex items-center justify-between px-4 py-2 border-t border-line bg-surface-2 shrink-0">
                    <span className="text-[10px] text-ink-faint">
                        총 <span className="text-ink-muted">{data.total.toLocaleString()}</span>개
                    </span>
                    <div className="flex items-center gap-1.5">
                        <button
                            disabled={page <= 1}
                            onClick={() => setPage((p) => p - 1)}
                            className="p-1 rounded-md bg-surface-3 hover:bg-surface-4 text-ink-muted disabled:opacity-30 transition-colors"
                        >
                            <ChevronLeft className="w-4 h-4" />
                        </button>
                        <span className="text-[10px] text-ink-muted min-w-[50px] text-center font-mono">
                            {page} / {Math.ceil(data.total / LIMIT) || 1}
                        </span>
                        <button
                            disabled={!data.has_next}
                            onClick={() => setPage((p) => p + 1)}
                            className="p-1 rounded-md bg-surface-3 hover:bg-surface-4 text-ink-muted disabled:opacity-30 transition-colors"
                        >
                            <ChevronRight className="w-4 h-4" />
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
}

// ── 메시지 행 ────────────────────────────────────────────

function MessageRow({ msg }: { msg: ChatMessageItem }) {
    return (
        <div className="flex items-start gap-3 px-4 py-1.5 hover:bg-surface-3/50 transition-colors">
            <span className="text-[10px] text-ink-faint font-mono shrink-0 pt-[3px] w-[64px]">
                {formatTime(msg.timestamp)}
            </span>

            <div className="flex-1 min-w-0 flex flex-wrap items-baseline gap-1.5 leading-snug">
                <span className="text-[11px] font-semibold text-info shrink-0">{msg.nickname}</span>
                <span className="text-[13px] text-ink-muted break-words">{msg.message}</span>
            </div>
        </div>
    );
}
