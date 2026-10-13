import { translatePlural } from '../i18n';
import { translate } from "../i18n";
import { useCallback, useEffect, useRef, useState } from "react";
import {
    BarChart2,
    AlertCircle,
    Calendar,
    Copy,
    Clock,
    Database,
    Download,
    HardDrive,
    History,
    Radio,
    RefreshCw,
    Video,
} from "lucide-react";
import { api, type ChannelLiveStat, type LiveSession, type StatsResponse } from "../api/client";
import { Button, Card, EmptyState, LoadingState, MetricCard, PageHeader } from "../components/ui/primitives";
import { useLanguage } from "../contexts/LanguageContext";
import { useToast } from "../components/ui/Toast";
import { formatDuration as formatDurationBase, formatBytes } from "../utils/format";

const formatDuration = (seconds: number, _language: string) => formatDurationBase(seconds, "korean");
const formatStatsDate = (iso: string | null, language: string) => iso ? new Date(iso).toLocaleString(language, { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—";
const formatCount = (count: number, _language: string, unit: "item" | "session" | "channel") => translatePlural(`stats.count.${unit}`, count);

function StorageCard({ used, total, free, dir, t }: { used: number; total: number; free: number; dir: string; t: (text: string) => string }) {
    useLanguage();
    const toast = useToast();
    const percentage = total > 0 ? Math.round((used / total) * 100) : 0;
    const tone = percentage >= 90 ? "var(--color-danger)" : percentage >= 70 ? "var(--color-warn)" : "var(--color-ok)";
    const copyPath = async () => {
        try {
            if (navigator.clipboard) await navigator.clipboard.writeText(dir);
            else {
                const field = document.createElement("textarea");
                field.value = dir; field.style.position = "fixed"; field.style.opacity = "0";
                document.body.appendChild(field);
                try { field.select(); if (!document.execCommand("copy")) throw new Error("Copy failed"); } finally { field.remove(); }
            }
            toast.success(t("stats.storagePathCopied"));
        } catch { toast.error(t("stats.couldNotCopyTheStoragePath")); }
    };
    return <div className="grid min-w-0 gap-6 border-y border-line py-4 md:grid-cols-2">
        <div className="min-w-0">
            <div className="flex items-center justify-between"><p className="text-xs text-ink-faint">{t("stats.diskUsage")}</p><HardDrive className="size-4 text-ink-faint" /></div>
            <div className="mt-1 flex flex-wrap items-baseline gap-3"><strong className="text-xl font-semibold text-ink">{percentage}%</strong><span className="text-xs text-ink-faint">{formatBytes(free)} {t("stats.free")}</span></div>
            <div className="mt-3 h-1 overflow-hidden rounded bg-surface-4"><div className="h-full" style={{width:`${percentage}%`,backgroundColor:tone}} /></div>
            <p className="mt-2 text-xs text-ink-faint tabular-nums">{formatBytes(used)} / {formatBytes(total)}</p>
        </div>
        <div className="min-w-0"><div className="flex items-center justify-between gap-3"><p className="text-xs text-ink-faint">{t("download.storageLocation")}</p><Button variant="ghost" icon={Copy} onClick={() => void copyPath()} disabled={!dir} aria-label={t("stats.copyStoragePath")}>{t("stats.copy")}</Button></div><p className="mt-1 break-all text-xs leading-6 text-ink-muted">{dir || "—"}</p></div>
    </div>;
}

export default function Stats() {
    const { language, t } = useLanguage();
    const [data, setData] = useState<StatsResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
    const [loadError, setLoadError] = useState(false);
    const requestInFlightRef = useRef(false);

    const loadStats = useCallback(async (silent = false) => {
        if (requestInFlightRef.current) return;
        requestInFlightRef.current = true;
        if (!silent) {
            setLoading(true);
            setLoadError(false);
        }
        try {
            setData(await api.getStats());
            setUpdatedAt(new Date());
            setLoadError(false);
        } catch {
            setLoadError(true);
        } finally {
            requestInFlightRef.current = false;
            if (!silent) setLoading(false);
        }
    }, []);

    useEffect(() => {
        void loadStats();
        const timer = window.setInterval(() => void loadStats(true), 30000);
        return () => window.clearInterval(timer);
    }, [loadStats]);

    return (
        <div className="product-page stats-page space-y-4">
            <PageHeader
                icon={BarChart2}
                eyebrow={t("stats.recordingOverview")}
                title={t("stats.title")}
                description={t("stats.seeRecordingTimeFileSizesChannelActivityAndStorageAtAGlance")}
                actionsPlacement="inline-top"
                actions={(
                    <div className="flex flex-wrap items-center justify-between gap-2 md:justify-end">
                        <span className="inline-flex items-center gap-2 flex-wrap text-xs text-ink-faint">
                            <span className="h-1.5 w-1.5 rounded-full bg-ok" aria-hidden="true" />
                            {updatedAt ? `${t("stats.refreshesEvery30Sec")} · ${updatedAt.toLocaleTimeString(language)}` : loadError ? t("stats.couldNotLoadStatistics") : t("stats.loadingStatistics")}
                        </span>
                        <Button icon={RefreshCw} onClick={() => void loadStats()} loading={loading} variant={loadError ? "primary" : "secondary"}>{t(loadError ? translate("live.tryAgain") : translate("common.refresh"))}</Button>
                    </div>
                )}
            />

            {loading && !data && <LoadingState label={translate("stats.loadingStatisticsInStats")} />}

            {!loading && !data && loadError && (
                <Card className="flex min-h-52 flex-col items-center justify-center gap-3 text-center">
                    <AlertCircle className="size-6 text-danger" />
                    <div>
                        <p className="text-sm font-medium text-ink">{t("stats.couldNotLoadStatisticsInStats")}</p>
                        <p className="mt-1 text-xs text-ink-faint">{t("settings.checkTheServerConnectionAndTryAgain")}</p>
                    </div>
                </Card>
            )}

            {data && loadError && (
                <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-control)] border border-warn/20 bg-warn/5 px-4 py-3 text-sm text-ink-muted">
                    <span className="flex min-w-0 items-center gap-2"><AlertCircle className="size-4 shrink-0 text-warn" />{t("stats.couldNotRefreshStatisticsShowingThePreviousData")}</span>
                    <Button icon={RefreshCw} onClick={() => void loadStats()}>{t("live.tryAgain")}</Button>
                </div>
            )}

            {data && (() => {
                const { live, vod, storage, recent_sessions: recentSessions } = data;
                return (
                    <>
                        <div className="stats-summary gap-0">
                            <MetricCard icon={Clock} label={t("stats.completedLiveRecordingTime")} value={formatDuration(live.total_duration_seconds, language)} detail={`${formatCount(live.total_sessions, language, "session")} · ${live.active_recordings} ${t("stats.activeRecordings")}`} tone="ok" />
                            <MetricCard icon={Video} label={t("stats.completedRecordingSize")} value={formatBytes(live.total_size_bytes)} detail={t("stats.totalCompletedLiveFiles")} tone="live" />
                            <MetricCard icon={Download} label={t("stats.videoDownloads")} value={formatCount(vod.total_completed, language, "item")} detail={`${t("platform.chzzk")} ${vod.by_type.chzzk} · ${t("stats.external")} ${vod.by_type.external}`} tone="primary" />

                        </div>

                        <StorageCard used={storage.used_bytes} total={storage.total_bytes} free={storage.free_bytes} dir={storage.download_dir} t={t} />
                        <div className="grid grid-cols-1 gap-4">
                            <Card padded={false} className="stats-history overflow-hidden">
                                <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-4 border-b border-line">
                                    <div className="flex items-center gap-2">
                                        <span className="w-8 h-8 rounded-[var(--radius-control)] bg-ok/10 text-ok grid place-items-center"><Radio className="w-4 h-4" /></span>
                                        <div>
                                            <h2 className="text-sm font-semibold text-ink">{t("stats.channelHistory")}</h2>
                                            <p className="text-[11px] text-ink-faint">{t("stats.liveDetectionOverTheLast30Days")}</p>
                                        </div>
                                    </div>
                                    <span className="text-xs text-ink-faint font-mono">{formatCount(live.by_channel.length, language, "channel")}</span>
                                </div>

                                {live.by_channel.length === 0 ? (
                                    <EmptyState compact icon={Database} title={t("stats.noRecordingsToReportYet")} description={t("stats.channelStatisticsWillAppearAfterTheFirstRecordingCompletes")} />
                                ) : (
                                    <div>
                                    <div className="stats-history-list divide-y divide-line">{live.by_channel.map(channel => <div key={channel.channel_id} className="px-4 py-3"><p className="break-all text-sm max-w-64 break-words font-medium text-ink">{channel.channel_name}</p><p className="mt-0.5 break-all text-xs text-ink-faint">{channel.channel_id}</p><div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-muted"><span>{t("live.recordings")} {channel.session_count}</span><span>{t("stats.liveDetections")} {channel.live_detected_count}{t("stats.days")}</span><span>{formatDuration(channel.total_duration_seconds, language)}</span><span>{formatBytes(channel.total_size_bytes)}</span></div></div>)}</div>
                                    <div className="stats-history-table">
                                        <table className="w-full min-w-[680px] text-sm">
                                            <thead>
                                                <tr className="bg-surface-3/60 border-b border-line">
                                                    <th className="text-left px-5 py-3 text-[11px] font-semibold text-ink-faint uppercase tracking-wider">{t("live.channels")}</th>
                                                    <th className="text-right px-4 py-3 text-[11px] font-semibold text-ink-faint">{t("live.recordings")}</th>
                                                    <th className="text-right px-4 py-3 text-[11px] font-semibold text-ink-faint">{t("stats.liveDetections")}</th>
                                                    <th className="text-right px-4 py-3 text-[11px] font-semibold text-ink-faint">{t("stats.totalTime")}</th>
                                                    <th className="text-right px-5 py-3 text-[11px] font-semibold text-ink-faint">{t("stats.size")}</th>
                                                </tr>
                                            </thead>
                                            <tbody className="divide-y divide-line/70">
                                                {live.by_channel.map((channel: ChannelLiveStat) => (
                                                    <tr key={channel.channel_id} className="hover:bg-surface-3/50 transition-colors">
                                                        <td className="px-5 py-3.5">
                                                            <p className="max-w-64 break-words font-medium text-ink">{channel.channel_name}</p>
                                                            <p className="text-[11px] text-ink-faint font-mono mt-0.5 break-all">{channel.channel_id}</p>
                                                        </td>
                                                        <td className="px-4 py-3.5 text-right text-ink-muted font-mono">{formatCount(channel.session_count, language, "session")}</td>
                                                        <td className="px-4 py-3.5 text-right text-info font-mono font-medium">{translatePlural("stats.count.day", channel.live_detected_count)}</td>
                                                        <td className="px-4 py-3.5 text-right text-ink-muted font-mono">{formatDuration(channel.total_duration_seconds, language)}</td>
                                                        <td className="px-5 py-3.5 text-right text-ink-muted font-mono">{formatBytes(channel.total_size_bytes)}</td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    </div></div>
                                )}
                            </Card>

                            <Card padded={false} className="stats-history overflow-hidden">
                                <div className="flex items-center justify-between gap-2 px-5 py-4 border-b border-line">
                                    <div className="flex items-center gap-2">
                                        <span className="w-8 h-8 rounded-[var(--radius-control)] bg-surface-4 text-ink-muted grid place-items-center"><Calendar className="w-4 h-4" /></span>
                                        <div>
                                            <h2 className="text-sm font-semibold text-ink">{t("stats.recentRecordings")}</h2>
                                            <p className="text-[11px] text-ink-faint">{t("stats.10MostRecentCompletedSessions")}</p>
                                        </div>
                                    </div>
                                </div>

                                {recentSessions.length === 0 ? (
                                    <EmptyState compact icon={History} title={t("stats.noRecordingHistory")} description={t("stats.completedSessionsWillAppearHere")} />
                                ) : (
                                    <div className="divide-y divide-line/70">
                                        {recentSessions.map((session: LiveSession, index: number) => (
                                            <div key={`${session.channel_name}-${session.ended_at}-${index}`} className="flex items-center gap-4 px-5 py-3.5 hover:bg-surface-3/50 transition-colors">
                                                <span className="w-2 h-2 rounded-full bg-ok shrink-0 " />
                                                <div className="flex-1 min-w-0">
                                                    <p className="text-sm font-medium text-ink truncate">{session.channel_name}</p>
                                                    <p className="text-[11px] text-ink-faint mt-0.5">{formatStatsDate(session.ended_at, language)}</p>
                                                </div>
                                                <div className="text-right shrink-0">
                                                    <p className="text-xs font-mono text-ink-muted">{formatDuration(session.duration_seconds, language)}</p>
                                                    <p className="text-[11px] font-mono text-ink-faint mt-0.5">{formatBytes(session.file_size_bytes)}</p>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </Card>
                        </div>
                    </>
                );
            })()}
        </div>
    );
}
