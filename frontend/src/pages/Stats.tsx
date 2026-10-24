import { formatNumber, translatePlural } from '../i18n';
import { translate } from "../i18n";
import { useCallback, useEffect, useRef, useState } from "react";
import {
    BarChart2,
    AlertCircle,
    Copy,
    Clock,
    Database,
    Download,
    History,
    RefreshCw,
    Video,
} from "lucide-react";
import { api, type ChannelLiveStat, type LiveSession, type Platform, type StatsResponse } from "../api/client";
import { PlatformBadge } from "../components/ui/PlatformBadge";
import { Button, Card, EmptyState, LoadingState, MetricCard, PageHeader } from "../components/ui/primitives";
import { useLanguage } from "../contexts/LanguageContext";
import { useToast } from "../components/ui/Toast";
import { formatDuration as formatDurationBase, formatBytes } from "../utils/format";

const formatDuration = (seconds: number, _language: string) => formatDurationBase(seconds, "korean");
const formatStatsDate = (iso: string | null, language: string) => iso ? new Date(iso).toLocaleString(language, { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—";
const formatCount = (count: number, _language: string, unit: "item" | "session" | "channel") => translatePlural(`stats.count.${unit}`, count);

function StorageCard({ storage, t }: { storage: StatsResponse['storage']; t: ReturnType<typeof useLanguage>['t'] }) {
    useLanguage();
    const toast = useToast();
    const { used_bytes: used, total_bytes: total, free_bytes: free } = storage;
    const liveDir = storage.live_download_dir || storage.download_dir;
    const videoDir = storage.vod_download_dir || '';
    const chzzkDir = storage.vod_chzzk_dir || videoDir;
    const separateVideoDirs = !!chzzkDir && !!videoDir && chzzkDir !== videoDir;
    const paths = [
        { id: 'live', label: t('live.title'), path: liveDir, hint: t('setup.saveLiveRecordingsHere') },
        ...(separateVideoDirs ? [
            { id: 'chzzk', label: `${t('download.title')} · ${t('platform.chzzk')}`, path: chzzkDir, hint: t('setup.saveDownloadedVideosIncludingVODsAndClipsHere') },
            { id: 'external', label: `${t('download.title')} · ${t('stats.external')}`, path: videoDir, hint: t('setup.saveDownloadedVideosIncludingVODsAndClipsHere') },
        ] : [{ id: 'video', label: t('download.title'), path: videoDir || chzzkDir, hint: t('setup.saveDownloadedVideosIncludingVODsAndClipsHere') }]),
    ];
    const usageAvailable = storage.usage_available !== false && Number.isFinite(total) && total > 0;
    const percentage = usageAvailable ? Math.max(0, Math.min(100, Math.round((used / total) * 100))) : 0;
    const tone = !usageAvailable ? "var(--color-ink-faint)" : percentage >= 90 ? "var(--color-danger)" : percentage >= 70 ? "var(--color-warn)" : "var(--color-ok)";
    const spaceStatus = !usageAvailable ? 'stats.diskUnavailable' : percentage >= 90 ? 'stats.diskSpaceLow' : percentage >= 70 ? 'stats.diskSpaceCaution' : 'stats.diskSpaceHealthy';
    const copyPath = async (dir: string) => {
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
    return <Card padded={false} className="stats-storage grid min-w-0">
        <div className="stats-storage-section min-w-0">
            <div className="workspace-panel-heading stats-storage-heading"><h2>{t("stats.diskUsage")}</h2><span className="text-xs font-medium" style={{color:tone}}>{t(spaceStatus)}</span></div>
            <div className="stats-storage-body stats-disk-section">
            <strong className="stats-disk-percentage">{usageAvailable ? `${formatNumber(percentage)}%` : '—'}</strong>
            <div className="stats-disk-meter" role={usageAvailable ? 'progressbar' : undefined} aria-label={t('stats.diskUsage')} aria-valuemin={usageAvailable ? 0 : undefined} aria-valuemax={usageAvailable ? 100 : undefined} aria-valuenow={usageAvailable ? percentage : undefined}><div style={{width:`${percentage}%`,backgroundColor:tone}} /></div>
            <dl className="stats-disk-capacity">
                <div><dt>{t('stats.diskUsedCapacity')}</dt><dd>{usageAvailable ? formatBytes(used) : '—'}</dd></div>
                <div><dt>{t('stats.diskFreeCapacity')}</dt><dd>{usageAvailable ? formatBytes(free) : '—'}{usageAvailable && <span className="stats-disk-secondary">{t('stats.diskFreeShare', {percentage:formatNumber(Math.round(free / total * 100))})}</span>}</dd></div>
                <div><dt>{t('stats.diskTotalCapacity')}</dt><dd>{usageAvailable ? formatBytes(total) : '—'}</dd></div>
                <div><dt>{t('stats.diskDrive')}</dt><dd className="stats-disk-drive">{storage.disk_mountpoint || '—'}{storage.disk_filesystem && <span className="stats-disk-secondary">{storage.disk_filesystem}</span>}</dd></div>
            </dl>
            <p className="stats-disk-hint text-xs text-ink-faint">{t('stats.liveStorageDiskHint')}</p>
            </div>
        </div>
        <div className="stats-storage-section min-w-0">
            <div className="workspace-panel-heading stats-storage-heading"><h2>{t('download.storageLocation')}</h2></div>
            <dl className="stats-storage-body stats-storage-paths">
                {paths.map(({ id, label, path, hint }) => <div key={id} data-storage-path={id}>
                    <dt className="stats-storage-path-heading"><span className="text-xs font-medium text-ink">{label}</span><Button variant="ghost" icon={Copy} onClick={() => void copyPath(path)} disabled={!path} aria-label={t('stats.copyNamedStoragePath', { name: label })}>{t('stats.copy')}</Button></dt>
                    <dd className="stats-storage-path-value text-xs leading-6 text-ink-muted">{path || '—'}</dd>
                    <dd className="mt-1 text-xs text-ink-faint">{hint}</dd>
                </div>)}
            </dl>
        </div>
    </Card>;
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
                description={t("workspace.statsDescription")}
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
                        <div className="stats-summary workspace-summary gap-0">
                            <MetricCard icon={Clock} label={t("stats.completedLiveRecordingTime")} value={formatDuration(live.total_duration_seconds, language)} detail={`${formatCount(live.total_sessions, language, "session")} · ${t("live.recording")}: ${formatCount(live.active_recordings, language, "session")}`} tone="ok" />
                            <MetricCard icon={Video} label={t("stats.completedRecordingSize")} value={formatBytes(live.total_size_bytes)} detail={t("stats.totalCompletedLiveFiles")} tone="live" />
                            <MetricCard icon={Download} label={t("stats.videoDownloads")} value={formatCount(vod.total_completed, language, "item")} detail={`${t("platform.chzzk")} ${vod.by_type.chzzk} · ${t("stats.external")} ${vod.by_type.external}`} tone="primary" />

                        </div>

                        <StorageCard storage={storage} t={t} />
                        <div className="grid grid-cols-1 gap-4">
                            <Card padded={false} className="stats-history overflow-hidden">
                                <div className="workspace-panel-heading flex flex-wrap items-center justify-between gap-2">
                                    <div className="flex items-center gap-2">
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
                                    <div className="stats-history-list divide-y divide-line">{live.by_channel.map(channel => <div key={channel.composite_key || channel.channel_id} className="px-4 py-3"><div className="flex items-center gap-2"><p className="break-all text-sm max-w-64 break-words font-medium text-ink">{channel.channel_name}</p>{channel.platform && <PlatformBadge platform={channel.platform} />}</div><p className="mt-0.5 break-all text-xs text-ink-faint">{channel.channel_id}</p><div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-muted"><span>{t("live.recordings")}: {formatCount(channel.session_count, language, "session")}</span><span>{t("stats.liveDetections")} {translatePlural("stats.count.day", channel.live_detected_count)}</span><span>{formatDuration(channel.total_duration_seconds, language)}</span><span>{formatBytes(channel.total_size_bytes)}</span></div></div>)}</div>
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
                                                    <tr key={channel.composite_key || channel.channel_id} className="hover:bg-surface-3/50 transition-colors">
                                                        <td className="px-5 py-3.5">
                                                            <div className="flex items-center gap-2">
                                                                <p className="max-w-64 break-words font-medium text-ink">{channel.channel_name}</p>
                                                                {channel.platform && <PlatformBadge platform={channel.platform} />}
                                                            </div>
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
                                <div className="workspace-panel-heading flex items-center justify-between gap-2">
                                    <div className="flex items-center gap-2">
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
