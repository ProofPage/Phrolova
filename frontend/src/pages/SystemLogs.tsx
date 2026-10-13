import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { clsx } from "clsx";
import { formatDateTime, formatNumber } from "../i18n";
import { localizedStatus } from "../utils/error";
import { api, type SystemLogFile } from "../api/client";
import { useToast } from "../components/ui/Toast";
import { useLanguage } from "../contexts/LanguageContext";
import { useConfirm } from "../components/ui/ConfirmModal";
import { Button, EmptyState, Input, PageHeader } from "../components/ui/primitives";
import { formatBytes, formatDate } from "../utils/format";

type LogLevel = "error" | "warning" | "info" | "other";
type LevelFilter = "all" | Exclude<LogLevel, "other">;
const LEVELS: LevelFilter[] = ["all", "error", "warning", "info"];
const LEVEL_KEYS = { all: "logs.severityAll", error: "logs.severityError", warning: "logs.severityWarning", info: "logs.severityInfo" };

// Read only the logger's level column, never severity words in a message.
function logLevel(line: string): LogLevel {
    const level = line.match(/^[^|]*\|\s*(TRACE|DEBUG|INFO|SUCCESS|WARNING|WARN|ERROR|CRITICAL|FATAL)\s*\|/)?.[1];
    if (level === "ERROR" || level === "CRITICAL" || level === "FATAL") return "error";
    if (level === "WARNING" || level === "WARN") return "warning";
    if (level === "INFO" || level === "SUCCESS") return "info";
    return "other";
}

export default function SystemLogs() {
    const { t } = useLanguage();
    const [files, setFiles] = useState<SystemLogFile[]>([]);
    const [selectedName, setSelectedName] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [listError, setListError] = useState(false);
    const [clearing, setClearing] = useState(false);
    const autoSelected = useRef(false);
    const listRequest = useRef<AbortController | null>(null);
    const toast = useToast();
    const confirm = useConfirm();

    const loadFiles = useCallback(async (silent = false) => {
        if (listRequest.current) return;
        const request = new AbortController();
        listRequest.current = request;
        if (!silent) setLoading(true);
        try {
            const data = await api.getSystemLogFiles(request.signal);
            if (request.signal.aborted) return;
            setFiles(data);
            setListError(false);
            if (!autoSelected.current && data.length) {
                autoSelected.current = true;
                setSelectedName(data.find(file => file.filename === "service.log")?.filename ?? data[0].filename);
            }
        } catch {
            if (!request.signal.aborted) setListError(true);
        } finally {
            if (listRequest.current === request) {
                listRequest.current = null;
                setLoading(false);
            }
        }
    }, []);

    useEffect(() => {
        void loadFiles();
        const timer = window.setInterval(() => void loadFiles(true), 5000);
        return () => {
            window.clearInterval(timer);
            listRequest.current?.abort();
            listRequest.current = null;
        };
    }, [loadFiles]);

    const handleClearLogs = async () => {
        const ok = await confirm({
            title: "logs.clearLogs",
            message: "logs.clearTheActiveLogAndAllDatedBackupLogsNewLogsWillContinueToBeSaved",
            confirmText: "logs.clearLogs",
            variant: "danger",
        });
        if (!ok) return;
        setClearing(true);
        try {
            const result = await api.clearSystemLogs();
            listRequest.current?.abort();
            listRequest.current = null;
            setSelectedName(null);
            await loadFiles();
            toast.success(localizedStatus(result.message, "logs.logsCleared"));
        } catch {
            toast.error("logs.couldNotClearLogs");
        } finally {
            setClearing(false);
        }
    };

    const selectedFile = files.find(file => file.filename === selectedName) ?? null;
    const fileGroups = [{key:"logs.live",values:files.filter(file => file.filename === "service.log")},{key:"logs.backup",values:files.filter(file => file.filename !== "service.log")}];
    const latest = files.reduce<string | null>((value, file) =>
        !value || new Date(file.modified_at).getTime() > new Date(value).getTime() ? file.modified_at : value, null);
    const summaries = [
        { label: "logs.totalFiles", value: (loading || listError) && !files.length ? "—" : formatNumber(files.length), detail: null },
        { label: "logs.totalSize", value: (loading || listError) && !files.length ? "—" : formatBytes(files.reduce((total, file) => total + file.size_bytes, 0)), detail: null },
        { label: "logs.latestActivity", value: latest ? formatDateTime(latest, { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—", detail: latest ? formatDateTime(latest, { year: "numeric", month: "short", day: "numeric" }) : t("logs.noLogEntries") },
    ];

    return <div className="product-page logs-page space-y-4">
        <PageHeader title={t("logs.title")} actions={<Button variant="danger" disabled={clearing} aria-busy={clearing || undefined} onClick={() => void handleClearLogs()}>{t("logs.clearLogs")}</Button>} />
        <dl className="logs-summary">
            {summaries.map(({label,value,detail}) => <div className="ui-metric" key={label}><dt className="ui-metric-label">{t(label)}</dt><dd className="ui-metric-value">{value}</dd>{detail && <dd className="ui-metric-detail">{detail}</dd>}</div>)}
        </dl>
        <div className="logs-workspace">
            <section className={clsx("logs-file-panel", selectedFile && "logs-panel-mobile-hidden")} aria-label={t("logs.logFiles")}>
                <header className="logs-panel-heading"><h2>{t("logs.logFilesInSystemLogs")}</h2><Button variant="ghost" disabled={loading} aria-busy={loading || undefined} onClick={() => void loadFiles()}>{t("common.refresh")}</Button></header>
                <p className="logs-panel-hint">{t("logs.listRefreshInterval")}</p>
                {listError && files.length > 0 && <div role="status" className="logs-list-error">{t("logs.couldNotLoadTheLogList")}</div>}
                {loading && !files.length ? <p className="logs-empty" role="status">{t("logs.loadingLogFiles")}</p> : !files.length ? <EmptyState title={t(listError ? "logs.couldNotLoadTheLogList" : "logs.noLogFiles")} description={listError ? t("settings.checkTheServerConnectionAndTryAgain") : undefined} compact /> : <div className="logs-file-list">
                    {files.map(file => <button type="button" key={file.filename} onClick={() => setSelectedName(file.filename)} aria-pressed={file.filename === selectedName} className={clsx("logs-file-option", file.filename === selectedName && "logs-file-selected")}>
                        <span className="logs-file-name">{file.filename}</span>
                        <span className="logs-file-meta"><span>{formatBytes(file.size_bytes)}</span><span className={file.filename === "service.log" ? "logs-file-kind" : undefined}>{file.filename === "service.log" ? t("logs.live") : t("logs.backup")}</span></span>
                        <span className="logs-file-date">{t("logs.modified")} {formatDate(file.modified_at, true)}</span>
                    </button>)}
                </div>}
                <div className="logs-file-breakdown"><h3>{t("logs.fileBreakdown")}</h3><dl>{fileGroups.map(group => <div key={group.key}><dt>{t(group.key)} <strong>{formatNumber(group.values.length)}</strong></dt><dd>{formatBytes(group.values.reduce((total,file) => total + file.size_bytes,0))}</dd></div>)}</dl></div>
            </section>
            <section className={clsx("logs-content-panel", !selectedFile && "logs-panel-mobile-hidden")} aria-label={t("logs.title")}>
                {selectedFile ? <>
                    <div className="logs-back"><Button variant="ghost" onClick={() => setSelectedName(null)}>{t("logs.logFiles")}</Button></div>
                    <LogContentViewer key={selectedFile.filename} file={selectedFile} />
                </> : <EmptyState title={t("logs.chooseALogFileFromTheListOnTheLeft")} compact />}
            </section>
        </div>
    </div>;
}

function LogContentViewer({ file }: { file: SystemLogFile }) {
    const { t } = useLanguage();
    const [content, setContent] = useState("");
    const [totalLines, setTotalLines] = useState(0);
    const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
    const [linesLimit, setLinesLimit] = useState(1000);
    const [searchTerm, setSearchTerm] = useState("");
    const [levelFilter, setLevelFilter] = useState<LevelFilter>("all");
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState(false);
    const [exporting, setExporting] = useState(false);
    const exportPending = useRef(false);
    const toast = useToast();
    const [autoScroll, setAutoScroll] = useState(true);
    const [autoRefresh, setAutoRefresh] = useState(file.filename === "service.log");
    const terminalRef = useRef<HTMLDivElement>(null);
    const contentRequest = useRef<AbortController | null>(null);

    const loadContent = useCallback(async (silent = false) => {
        if (contentRequest.current) return;
        const request = new AbortController();
        contentRequest.current = request;
        if (!silent) setLoading(true);
        try {
            const data = await api.getSystemLogContent(file.filename, linesLimit, request.signal);
            if (request.signal.aborted) return;
            setContent(data.content);
            setTotalLines(data.total_lines);
            setUpdatedAt(new Date());
            setLoadError(false);
        } catch {
            if (!request.signal.aborted) setLoadError(true);
        } finally {
            if (contentRequest.current === request) {
                contentRequest.current = null;
                setLoading(false);
            }
        }
    }, [file.filename, linesLimit]);

    useEffect(() => {
        void loadContent();
        return () => {
            contentRequest.current?.abort();
            contentRequest.current = null;
        };
    }, [loadContent]);

    useEffect(() => {
        if (!autoRefresh) return;
        const timer = window.setInterval(() => void loadContent(true), 2000);
        return () => window.clearInterval(timer);
    }, [autoRefresh, loadContent]);

    useEffect(() => {
        if (autoScroll && terminalRef.current) terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }, [content, autoScroll, searchTerm, levelFilter]);

    const exportLog = async () => {
        if (exportPending.current) return;
        exportPending.current = true;
        setExporting(true);
        try {
            const blob = await api.exportSystemLog(file.filename);
            const url = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = file.filename;
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.setTimeout(() => URL.revokeObjectURL(url), 1000);
            toast.success(t("logs.exportStarted"));
        } catch {
            toast.error(t("logs.couldNotExport"));
        } finally {
            exportPending.current = false;
            setExporting(false);
        }
    };

    const { lines, counts } = useMemo(() => {
        const raw = content.split(/\r?\n/);
        if (raw.at(-1) === "") raw.pop();
        const entries = raw.map((text, index) => ({text, index, level: logLevel(text)}));
        const totals = {all:entries.length,error:0,warning:0,info:0};
        for (const entry of entries) if (entry.level !== "other") totals[entry.level]++;
        return {lines:entries,counts:totals};
    }, [content]);
    const visibleLines = lines.filter(line => (levelFilter === "all" || line.level === levelFilter) && line.text.toLowerCase().includes(searchTerm.toLowerCase()));
    const highlight = (text: string) => {
        if (!searchTerm) return text;
        const escaped = searchTerm.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        return text.split(new RegExp(`(${escaped})`, "gi")).map((part,index) => part.toLowerCase() === searchTerm.toLowerCase() ? <mark key={index}>{part}</mark> : part);
    };

    return <div>
        <header className="logs-content-heading"><h2>{file.filename}</h2><p>{formatBytes(file.size_bytes)} · {t("logs.modified")} {formatDate(file.modified_at,true)}</p></header>
        <div className="logs-level-summary" aria-label={t("logs.loadedScope",{count:lines.length})}>
            {LEVELS.map(level => <button type="button" key={level} data-log-level={level} aria-pressed={levelFilter === level} onClick={() => setLevelFilter(level)} className={clsx("logs-level",`logs-level-${level}`)}><span>{t(LEVEL_KEYS[level])}</span><strong>{updatedAt ? formatNumber(counts[level]) : "—"}</strong></button>)}
        </div>
        <div className="logs-controls">
            <div className="logs-limit-row"><span>{t("logs.loadedScope",{count:lines.length})}</span><div className="logs-line-limits" role="group" aria-label={t("logs.lineRange")}>
                {[100,500,1000,0].map(value => <Button variant="ghost" key={value} aria-pressed={linesLimit === value} disabled={loading} onClick={() => setLinesLimit(value)}>{value === 0 ? t("live.all") : t("logs.lineLimit",{count:value})}</Button>)}
            </div></div>
            <div className="log-toolbar-row"><Input placeholder={t("logs.searchLogs")} aria-label={t("logs.searchLogsInSystemLogs")} value={searchTerm} onChange={event => setSearchTerm(event.target.value)} />
                <div className="logs-actions"><Button disabled={exporting} aria-busy={exporting || undefined} title={t("logs.exportHint")} onClick={() => void exportLog()}>{t(exporting ? "logs.exporting" : "logs.export")}</Button><Button variant="ghost" aria-pressed={autoRefresh} title={t("logs.refreshingLiveEvery2Seconds")} aria-label={t(autoRefresh ? "logs.disableLiveRefresh" : "logs.enableLiveRefresh")} onClick={() => setAutoRefresh(value => !value)}>{t("logs.liveRefresh")}</Button><Button variant="ghost" aria-pressed={autoScroll} title={t("logs.scrollToBottomAutomatically")} onClick={() => setAutoScroll(value => !value)}>{t("logs.autoScroll")}</Button><Button disabled={loading} aria-busy={loading || undefined} onClick={() => void loadContent()}>{t("common.refresh")}</Button></div>
            </div>
        </div>
        {loadError && content && <div role="status" className="logs-load-error">{t("logs.couldNotRefreshLogsShowingThePreviousContent")}</div>}
        <div ref={terminalRef} className="log-viewer" role="region" tabIndex={0} aria-label={t("logs.logEntries")} aria-busy={loading || undefined}>
            {loading && !content ? <p className="logs-empty" role="status">{t("logs.loadingLogs")}</p> : loadError && !content ? <EmptyState compact title={t("logs.couldNotLoadTheLogContent")} description={t("settings.checkTheServerConnectionAndTryAgain")} action={<Button onClick={() => void loadContent()}>{t("live.tryAgain")}</Button>} /> : !lines.length ? <p className="logs-empty">{t(autoRefresh ? "logs.noLogsYetWaitingForNewEntries" : "logs.noLogEntries")}</p> : !visibleLines.length ? <p className="logs-empty">{t("common.noResultsFound")}</p> : visibleLines.map(line => <div key={line.index} className={clsx("logs-entry",`logs-entry-${line.level}`)}>{highlight(line.text)}</div>)}
        </div>
        <footer className="logs-content-footer"><span>{t("logs.lineSummary",{shown:visibleLines.length,total:totalLines})}</span><span>{updatedAt ? `${t("logs.refresh")} ${formatDateTime(updatedAt,{hour:"2-digit",minute:"2-digit",second:"2-digit"})}` : "—"}</span></footer>
    </div>;
}
