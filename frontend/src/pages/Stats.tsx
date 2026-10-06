import { useCallback, useEffect, useRef, useState } from "react";
import {
    BarChart2,
    AlertCircle,
    Calendar,
    Clock,
    Database,
    Download,
    HardDrive,
    History,
    Loader2,
    Radio,
    RefreshCw,
    Video,
} from "lucide-react";
import { api, type ChannelLiveStat, type LiveSession, type StatsResponse } from "../api/client";
import { Button, Card, EmptyState, MetricCard, PageHeader } from "../components/ui/primitives";
import { useLanguage } from "../contexts/LanguageContext";
import { formatDuration as formatDurationBase, formatBytes } from "../utils/format";

const formatDuration = (seconds: number, language: string) => {
    const duration = formatDurationBase(seconds, "korean");
    return language === "en" ? duration.replace("시간", "h").replace("분", "m") : duration;
};

const formatStatsDate = (iso: string | null, language: string) => {
    if (!iso) return "-";
    const locale = language === "ko" ? "ko-KR" : language === "ja" ? "ja-JP" : "en-US";
    return new Date(iso).toLocaleString(locale, { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
};

const formatCount = (count: number, language: string, unit: "item" | "session" | "channel") => {
    if (language === "ko") return `${count}개`;
    if (language === "ja") return `${count}${unit === "channel" ? "チャンネル" : "件"}`;
    const word = count === 1 ? unit : `${unit}s`;
    return `${count} ${word}`;
};

function StorageCard({ used, total, free, dir, t }: { used: number; total: number; free: number; dir: string; t: (text: string) => string }) {
    const percentage = total > 0 ? Math.round((used / total) * 100) : 0;
    const tone = percentage >= 90 ? "var(--color-danger)" : percentage >= 70 ? "var(--color-warn)" : "var(--color-ok)";

    return (
        <Card className="relative overflow-hidden">
            <span className="absolute inset-x-0 top-0 h-px opacity-70" style={{ background: `linear-gradient(90deg, transparent, ${tone}, transparent)` }} />
            <div className="flex items-start justify-between gap-4">
                <div>
                    <p className="text-[11px] font-medium text-ink-faint uppercase tracking-[0.08em]">{t("디스크 사용률")}</p>
                    <p className="text-2xl font-bold tracking-tight text-ink mt-2">{percentage}%</p>
                    <p className="text-xs text-ink-faint mt-1.5">{formatBytes(free)} {t("여유 공간")}</p>
                </div>
                <span className="w-9 h-9 rounded-[var(--radius-control)] grid place-items-center bg-info/10 text-info">
                    <HardDrive className="w-[18px] h-[18px]" />
                </span>
            </div>
            <div className="mt-4 h-1.5 rounded-full bg-surface-4 overflow-hidden">
                <div className="h-full rounded-full transition-all" style={{ width: `${percentage}%`, backgroundColor: tone }} />
            </div>
            <div className="mt-2 flex min-w-0 items-center justify-between gap-3 text-[11px] text-ink-faint font-mono">
                <p className="shrink-0 whitespace-nowrap">{formatBytes(used)} / {formatBytes(total)}</p>
                <p className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap text-right leading-4" title={`${t("용량 확인 기준 경로")}: ${dir}`}>{dir}</p>
            </div>
        </Card>
    );
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
        <div className="space-y-6">
            <PageHeader
                icon={BarChart2}
                eyebrow={t("녹화 현황 분석")}
                title={t("통계")}
                description={t("녹화 시간, 파일 용량, 채널 활동과 저장소 상태를 한눈에 파악합니다.")}
                actionsPlacement="inline-top"
                actions={(
                    <div className="flex flex-wrap items-center justify-between gap-2 md:justify-end">
                        <span className="inline-flex items-center gap-2 whitespace-nowrap rounded-full border border-line bg-surface-3/70 px-3 py-2 text-xs text-ink-faint">
                            <span className="h-1.5 w-1.5 rounded-full bg-ok" aria-hidden="true" />
                            {updatedAt ? `${t("30초마다 갱신")} · ${updatedAt.toLocaleTimeString(language === "ko" ? "ko-KR" : language === "ja" ? "ja-JP" : "en-US")}` : loadError ? t("통계 조회 실패") : t("통계 정보를 불러오는 중")}
                        </span>
                        <Button icon={RefreshCw} onClick={() => void loadStats()} loading={loading} variant={loadError ? "primary" : "secondary"}>{t(loadError ? "다시 시도" : "새로고침")}</Button>
                    </div>
                )}
            />

            {loading && !data && (
                <Card className="min-h-56 grid place-items-center text-ink-faint">
                    <span className="inline-flex items-center gap-2 text-sm"><Loader2 className="w-5 h-5 animate-spin" /> {t("통계를 집계하고 있습니다")}</span>
                </Card>
            )}

            {!loading && !data && loadError && (
                <Card className="flex min-h-52 flex-col items-center justify-center gap-3 text-center">
                    <AlertCircle className="size-6 text-danger" />
                    <div>
                        <p className="text-sm font-medium text-ink">{t("통계 정보를 불러오지 못했습니다")}</p>
                        <p className="mt-1 text-xs text-ink-faint">{t("서버 연결을 확인한 뒤 다시 시도해 주세요.")}</p>
                    </div>
                </Card>
            )}

            {data && loadError && (
                <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-control)] border border-warn/20 bg-warn/5 px-4 py-3 text-sm text-ink-muted">
                    <span className="flex min-w-0 items-center gap-2"><AlertCircle className="size-4 shrink-0 text-warn" />{t("통계 갱신에 실패했습니다. 이전 데이터를 표시합니다.")}</span>
                    <Button icon={RefreshCw} onClick={() => void loadStats()}>{t("다시 시도")}</Button>
                </div>
            )}

            {data && (() => {
                const { live, vod, storage, recent_sessions: recentSessions } = data;
                return (
                    <>
                        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
                            <MetricCard icon={Clock} label={t("완료된 라이브 녹화 시간")} value={formatDuration(live.total_duration_seconds, language)} detail={`${formatCount(live.total_sessions, language, "session")} · ${live.active_recordings} ${t("활성 녹화")}`} tone="ok" />
                            <MetricCard icon={Video} label={t("완료된 녹화 용량")} value={formatBytes(live.total_size_bytes)} detail={t("완료된 라이브 파일 합계")} tone="live" />
                            <MetricCard icon={Download} label={t("영상 다운로드")} value={formatCount(vod.total_completed, language, "item")} detail={`${t("치지직")} ${vod.by_type.chzzk} · ${t("외부")} ${vod.by_type.external}`} tone="primary" />
                            <StorageCard used={storage.used_bytes} total={storage.total_bytes} free={storage.free_bytes} dir={storage.download_dir} t={t} />
                        </div>

                        <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.55fr)_minmax(320px,0.75fr)] gap-4">
                            <Card padded={false} className="overflow-hidden">
                                <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-4 border-b border-line">
                                    <div className="flex items-center gap-2">
                                        <span className="w-8 h-8 rounded-[var(--radius-control)] bg-ok/10 text-ok grid place-items-center"><Radio className="w-4 h-4" /></span>
                                        <div>
                                            <h2 className="text-sm font-semibold text-ink">{t("채널별 기록")}</h2>
                                            <p className="text-[11px] text-ink-faint">{t("라이브 감지는 최근 30일 기준")}</p>
                                        </div>
                                    </div>
                                    <span className="text-xs text-ink-faint font-mono">{formatCount(live.by_channel.length, language, "channel")}</span>
                                </div>

                                {live.by_channel.length === 0 ? (
                                    <EmptyState compact icon={Database} title={t("아직 집계할 녹화가 없습니다")} description={t("첫 녹화가 완료되면 채널별 통계가 표시됩니다.")} />
                                ) : (
                                    <div className="overflow-x-auto">
                                        <table className="w-full min-w-[680px] text-sm">
                                            <thead>
                                                <tr className="bg-surface-3/60 border-b border-line">
                                                    <th className="text-left px-5 py-3 text-[11px] font-semibold text-ink-faint uppercase tracking-wider">{t("채널")}</th>
                                                    <th className="text-right px-4 py-3 text-[11px] font-semibold text-ink-faint">{t("녹화")}</th>
                                                    <th className="text-right px-4 py-3 text-[11px] font-semibold text-ink-faint">{t("라이브 감지")}</th>
                                                    <th className="text-right px-4 py-3 text-[11px] font-semibold text-ink-faint">{t("총 시간")}</th>
                                                    <th className="text-right px-5 py-3 text-[11px] font-semibold text-ink-faint">{t("용량")}</th>
                                                </tr>
                                            </thead>
                                            <tbody className="divide-y divide-line/70">
                                                {live.by_channel.map((channel: ChannelLiveStat) => (
                                                    <tr key={channel.channel_id} className="hover:bg-surface-3/50 transition-colors">
                                                        <td className="px-5 py-3.5">
                                                            <p className="font-medium text-ink">{channel.channel_name}</p>
                                                            <p className="text-[11px] text-ink-faint font-mono mt-0.5">{channel.channel_id}</p>
                                                        </td>
                                                        <td className="px-4 py-3.5 text-right text-ink-muted font-mono">{formatCount(channel.session_count, language, "session")}</td>
                                                        <td className="px-4 py-3.5 text-right text-info font-mono font-medium">{language === "en" ? `${channel.live_detected_count} days` : `${channel.live_detected_count}${t("일")}`}</td>
                                                        <td className="px-4 py-3.5 text-right text-ink-muted font-mono">{formatDuration(channel.total_duration_seconds, language)}</td>
                                                        <td className="px-5 py-3.5 text-right text-ink-muted font-mono">{formatBytes(channel.total_size_bytes)}</td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    </div>
                                )}
                            </Card>

                            <Card padded={false} className="overflow-hidden">
                                <div className="flex items-center justify-between gap-2 px-5 py-4 border-b border-line">
                                    <div className="flex items-center gap-2">
                                        <span className="w-8 h-8 rounded-[var(--radius-control)] bg-surface-4 text-ink-muted grid place-items-center"><Calendar className="w-4 h-4" /></span>
                                        <div>
                                            <h2 className="text-sm font-semibold text-ink">{t("최근 녹화")}</h2>
                                            <p className="text-[11px] text-ink-faint">{t("최근 완료된 10개 세션")}</p>
                                        </div>
                                    </div>
                                </div>

                                {recentSessions.length === 0 ? (
                                    <EmptyState compact icon={History} title={t("녹화 이력이 없습니다")} description={t("완료된 세션이 여기에 쌓입니다.")} />
                                ) : (
                                    <div className="divide-y divide-line/70">
                                        {recentSessions.map((session: LiveSession, index: number) => (
                                            <div key={`${session.channel_name}-${session.ended_at}-${index}`} className="flex items-center gap-4 px-5 py-3.5 hover:bg-surface-3/50 transition-colors">
                                                <span className="w-2 h-2 rounded-full bg-ok shrink-0 shadow-[0_0_10px_var(--color-ok)]" />
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
