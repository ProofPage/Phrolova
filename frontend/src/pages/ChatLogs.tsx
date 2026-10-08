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
    RefreshCw,
    AlertCircle,
} from "lucide-react";
import { clsx } from "clsx";
import { api, ChatLogFile, ChatMessageItem, MessagesResponse } from "../api/client";
import { Button, EmptyState, Input, LoadingState, PageHeader } from "../components/ui/primitives";
import { formatBytes, formatDate as _formatDate, formatTime } from "../utils/format";
import { useLanguage } from "../contexts/LanguageContext";

function formatDate(iso: string): string {
    return _formatDate(iso, true);
}

// ── 메인 페이지 ──────────────────────────────────────────

export default function ChatLogs() {
    const { t } = useLanguage();
    const [selectedFile, setSelectedFile] = useState<ChatLogFile | null>(null);
    const [refreshKey, setRefreshKey] = useState(0);

    return (
        <div className="product-page chat-page flex flex-col gap-4 lg:h-[calc(100dvh-6.5rem)]">
            <PageHeader
                icon={MessageSquare}
                eyebrow={t("라이브 채팅 아카이브")}
                title={t("채팅 기록")}
                description={t("채널별 채팅 기록을 검색하고, 녹화 세션의 원본 로그를 다운로드하세요.")}
                actions={<Button icon={RefreshCw} onClick={() => setRefreshKey((value) => value + 1)}>{t("새로고침")}</Button>}
            />

            <div className="flex flex-col lg:flex-row flex-1 gap-4 min-h-[480px] max-lg:min-h-0 max-sm:gap-3 xl:min-h-0">
                <div className={clsx("lg:w-[280px] lg:shrink-0 flex flex-col bg-surface-2 border border-line rounded-[var(--radius-card)] overflow-hidden surface-raise min-h-[260px] max-sm:min-h-0", selectedFile && "hidden lg:flex")}>
                    <div className="px-4 py-3 border-b border-line text-xs font-semibold text-ink-muted">{t("로그 파일")}</div>
                    <FileListView 
                        refreshKey={refreshKey}
                        selectedFile={selectedFile} 
                        onSelect={setSelectedFile} 
                    />
                </div>

                <div className={clsx("min-w-0 flex-1 flex flex-col bg-surface-2 border border-line rounded-[var(--radius-card)] overflow-hidden surface-raise min-h-[320px]", !selectedFile && "hidden lg:flex")}>
                    <div className="flex min-h-12 items-center gap-3 px-4 py-2 border-b border-line text-xs font-semibold text-ink-muted">
                        {selectedFile && <button type="button" onClick={() => setSelectedFile(null)} className="inline-flex min-h-11 items-center gap-1.5 text-ink-muted hover:text-ink lg:hidden"><ChevronLeft className="size-4" />{t("로그 파일")}</button>}
                        <span className={selectedFile ? "hidden lg:inline" : ""}>{t("채팅 내용")}</span>
                    </div>
                    {selectedFile === null ? (
                        <div className="flex-1 flex flex-col items-center justify-center text-ink-faint p-8 text-center">
                            <span className="w-8 h-8 grid place-items-center mb-4"><MessageSquare className="w-6 h-6 opacity-60" /></span>
                            <p className="text-sm">{t("채팅 로그를 선택해 내용을 확인하세요.")}</p>
                        </div>
                    ) : (
                        <MessageViewer file={selectedFile} />
                    )}
                </div>
            </div>
        </div>
    );
}

// ── 파일 목록 뷰 ────────────────────────────────────────

interface FileListViewProps {
    refreshKey: number;
    selectedFile: ChatLogFile | null;
    onSelect: (file: ChatLogFile) => void;
}

function FileListView({ selectedFile, onSelect, refreshKey }: FileListViewProps) {
    const { t } = useLanguage();
    const [files, setFiles] = useState<ChatLogFile[]>([]);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState(false);

    useEffect(() => {
        loadFiles();
    }, [refreshKey]);

    const loadFiles = async () => {
        setLoading(true);
        setLoadError(false);
        try {
            const data = await api.getChatFiles();
            setFiles(data);
        } catch {
            setLoadError(true);
        } finally {
            setLoading(false);
        }
    };

    const grouped = files.reduce<Record<string, ChatLogFile[]>>((acc, f) => {
        if (!acc[f.channel]) acc[f.channel] = [];
        acc[f.channel].push(f);
        return acc;
    }, {});

    if (loading && files.length === 0) return <LoadingState label="채팅 기록을 불러오는 중" />;

    if (files.length === 0) {
        if (loadError) {
            return <EmptyState icon={AlertCircle} title={t("채팅 로그를 불러오지 못했습니다.")} description={t("서버 연결을 확인한 뒤 다시 시도해 주세요.")} action={<Button icon={RefreshCw} onClick={() => void loadFiles()}>{t("다시 시도")}</Button>} />;
        }
        return (
            <div className="flex flex-col flex-1 items-center justify-center p-8 text-center">
                <MessageSquare className="w-8 h-8 text-ink-faint mb-3" />
                <p className="text-ink-muted font-medium text-sm mb-1">저장된 채팅 로그가 없습니다.</p>
                <p className="text-xs text-ink-faint leading-relaxed">설정에서 채팅 저장을 켜면 라이브 녹화 중 저장된 채팅이 여기에 표시됩니다.</p>
            </div>
        );
    }

    return (
        <div className="flex-1 overflow-y-auto scrollbar-thin">
            {Object.entries(grouped).map(([channel, channelFiles]) => (
                <div key={channel} className="border-b border-line/70 last:border-0">
                    <div className="sticky top-0 z-10 flex items-center gap-2 px-4 py-2.5 bg-surface-1 border-b border-line">
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
                                <button
                                    type="button"
                                    key={file.file_id}
                                    onClick={() => onSelect(file)}
                                    aria-pressed={isSelected}
                                    className={clsx(
                                        "flex w-full items-center gap-3 px-4 py-3 text-left transition-colors group",
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
                                </button>
                            );
                        })}
                    </div>
                </div>
            ))}
        </div>
    );
}

// ── 메시지 뷰어 ─────────────────────────────────────────

interface MessageViewerProps { file: ChatLogFile }

function MessageViewer({ file }: MessageViewerProps) {
    const { t } = useLanguage();
    const [data, setData] = useState<MessagesResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState(false);
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
        setLoadError(false);
        try {
            const res = await api.getChatMessages(file.file_id, {
                page: targetPage,
                limit: LIMIT,
                search: search || undefined,
                nickname: nickname || undefined,
            });
            setData(res);
        } catch {
            setLoadError(true);
        } finally {
            setLoading(false);
        }
    }, [file.file_id]);

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
                    className="chat-download-link flex items-center gap-1.5 px-3 py-1.5 rounded-[var(--radius-control)] text-xs text-ink-muted hover:text-ink hover:bg-surface-3 border border-line transition-colors shrink-0"
                    title="JSONL 파일 다운로드"
                >
                    <Download className="w-3.5 h-3.5" />
                    다운로드
                </a>
            </div>

            <div className="p-3 border-b border-line bg-surface-1 shrink-0 flex flex-wrap gap-2">
                <div className="chat-search-grid flex flex-wrap items-center gap-2 w-full min-w-0 flex-1">
                    <div className="relative max-lg:min-w-0 flex-1">
                        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-ink-faint" />
                        <Input
                            type="text"
                            value={pendingSearch}
                            onChange={(e) => setPendingSearch(e.target.value)}
                            onKeyDown={handleKeyDown}
                            aria-label={t("채팅 내용 검색")} placeholder="내용 검색..."
                            className="w-full pl-8 pr-3 py-1.5 text-xs"
                        />
                    </div>
                    <div className="w-1/3 min-w-[100px] max-sm:min-w-0">
                        <Input
                            type="text"
                            value={pendingNickname}
                            onChange={(e) => setPendingNickname(e.target.value)}
                            onKeyDown={handleKeyDown}
                            aria-label={t("닉네임 검색")} placeholder="닉네임..."
                            className="w-full px-3 py-1.5 text-xs"
                        />
                    </div>
                    <Button icon={Search} onClick={handleSearch} variant="primary" className="px-3 py-1.5 text-xs shrink-0">검색</Button>
                    {hasFilter && (
                        <button
                            onClick={handleClearSearch}
                            aria-label={t("검색 초기화")} className="chat-clear-search icon-button p-1.5 text-ink-faint hover:text-ink bg-surface-3 hover:bg-surface-4 rounded-md transition-colors shrink-0"
                            title="검색 초기화"
                        >
                            <X className="w-3.5 h-3.5" />
                        </button>
                    )}
                </div>
            </div>

            {loadError && data && <div role="status" className="flex flex-wrap gap-2 items-center justify-between border-b border-line px-3 py-2 text-xs text-ink-muted"><span>{t("메시지 갱신에 실패했습니다. 이전 내용을 표시합니다.")}</span><Button onClick={() => void loadMessages(page, appliedSearch, appliedNickname)}>{t("다시 시도")}</Button></div>}
            <div className="flex-1 overflow-y-auto bg-surface-0/45 relative min-h-0">
                {loading && !data && (
                    <div className="absolute inset-0 z-10 bg-surface-0/65 flex items-center justify-center text-ink-faint">
                        <Loader2 className="w-5 h-5 animate-spin mr-2" />
                        <span className="text-sm">불러오는 중...</span>
                    </div>
                )}
                
                {loadError && !data ? (
                    <div className="flex h-full items-center justify-center">
                        <EmptyState icon={AlertCircle} title={t("메시지를 불러오지 못했습니다.")} description={t("서버 연결을 확인한 뒤 다시 시도해 주세요.")} compact action={<Button icon={RefreshCw} onClick={() => void loadMessages(page, appliedSearch, appliedNickname)}>{t("다시 시도")}</Button>} />
                    </div>
                ) : !data || data.messages.length === 0 ? (
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
                            aria-label={t("이전 페이지")} title={t("이전 페이지")}
                            disabled={page <= 1}
                            onClick={() => setPage((p) => p - 1)}
                            className="icon-button disabled:opacity-30"
                        >
                            <ChevronLeft className="w-4 h-4" />
                        </button>
                        <span className="text-[10px] text-ink-muted min-w-[50px] text-center font-mono">
                            {page} / {Math.ceil(data.total / LIMIT) || 1}
                        </span>
                        <button
                            aria-label={t("다음 페이지")} title={t("다음 페이지")}
                            disabled={!data.has_next}
                            onClick={() => setPage((p) => p + 1)}
                            className="icon-button disabled:opacity-30"
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
        <div className="chat-message-row flex items-start gap-3 px-4 py-1.5 hover:bg-surface-3/50 transition-colors">
            <span className="text-[10px] text-ink-faint font-mono shrink-0 pt-[3px] w-[64px]">
                {formatTime(msg.timestamp)}
            </span>

            <div className="flex-1 min-w-0 flex flex-wrap items-baseline gap-1.5 leading-snug">
                <span title={msg.nickname} className="min-w-0 max-w-full break-all text-xs font-semibold text-ink-muted">{msg.nickname}</span>
                <span className="chat-message-text min-w-0 max-w-full text-[13px] text-ink-muted">{msg.message}</span>
            </div>
        </div>
    );
}
