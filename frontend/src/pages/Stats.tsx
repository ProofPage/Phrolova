import { useEffect, useState } from "react";
import {
    BarChart2,
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
import { useToast } from "../components/ui/Toast";
import { formatDuration as formatDurationBase, formatBytes, formatDate } from "../utils/format";

const formatDuration = (seconds: number) => formatDurationBase(seconds, "korean");

function StorageCard({ used, total, free, dir }: { used: number; total: number; free: number; dir: string }) {
    const percentage = total > 0 ? Math.round((used / total) * 100) : 0;
    const tone = percentage >= 90 ? "var(--color-danger)" : percentage >= 70 ? "var(--color-warn)" : "var(--color-ok)";

    return (
        <Card className="relative overflow-hidden">
            <span className="absolute inset-x-0 top-0 h-px opacity-70" style={{ background: `linear-gradient(90deg, transparent, ${tone}, transparent)` }} />
            <div className="flex items-start justify-between gap-4">
                <div>
                    <p className="text-[11px] font-medium text-ink-faint uppercase tracking-[0.08em]">저장소 사용률</p>
                    <p className="text-2xl font-bold tracking-tight text-ink mt-2">{percentage}%</p>
                    <p className="text-xs text-ink-faint mt-1.5">{formatBytes(free)} 사용 가능</p>
                </div>
                <span className="w-9 h-9 rounded-[var(--radius-control)] grid place-items-center bg-info/10 text-info">
                    <HardDrive className="w-[18px] h-[18px]" />
                </span>
            </div>
            <div className="mt-4 h-1.5 rounded-full bg-surface-4 overflow-hidden">
                <div className="h-full rounded-full transition-all" style={{ width: `${percentage}%`, backgroundColor: tone }} />
            </div>
            <div className="mt-2 flex items-center justify-between gap-3 text-[11px] text-ink-faint font-mono">
                <span>{formatBytes(used)} / {formatBytes(total)}</span>
                <span className="truncate" title={dir}>{dir}</span>
            </div>
        </Card>
    );
}

export default function Stats() {
    const [data, setData] = useState<StatsResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const toast = useToast();

    const loadStats = async () => {
        setLoading(true);
        try {
            setData(await api.getStats());
        } catch {
            toast.error("통계 데이터를 불러오는 데 실패했습니다.");
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadStats();
    }, []);

    return (
        <div className="space-y-6">
            <PageHeader
                icon={BarChart2}
                eyebrow="Recording insights"
                title="Statistics"
                description="녹화 시간, 파일 용량, 채널 활동과 저장소 상태를 한눈에 파악합니다."
                actions={<Button icon={RefreshCw} onClick={loadStats} loading={loading}>새로고침</Button>}
            />

            {loading && !data && (
                <Card className="min-h-56 grid place-items-center text-ink-faint">
                    <span className="inline-flex items-center gap-2 text-sm"><Loader2 className="w-5 h-5 animate-spin" /> 통계를 집계하고 있습니다</span>
                </Card>
            )}

            {data && (() => {
                const { live, vod, storage, recent_sessions: recentSessions } = data;
                return (
                    <>
                        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
                            <MetricCard icon={Clock} label="총 라이브 녹화 시간" value={formatDuration(live.total_duration_seconds)} detail={`${live.total_sessions}개 세션`} tone="ok" />
                            <MetricCard icon={Video} label="총 녹화 용량" value={formatBytes(live.total_size_bytes)} detail="라이브 녹화 파일 합계" tone="live" />
                            <MetricCard icon={Download} label="VOD 다운로드" value={`${vod.total_completed}개`} detail={`치지직 ${vod.by_type.chzzk} · 외부 ${vod.by_type.external}`} tone="primary" />
                            <StorageCard used={storage.used_bytes} total={storage.total_bytes} free={storage.free_bytes} dir={storage.download_dir} />
                        </div>

                        <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.55fr)_minmax(320px,0.75fr)] gap-4">
                            <Card padded={false} className="overflow-hidden">
                                <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-4 border-b border-line">
                                    <div className="flex items-center gap-2">
                                        <span className="w-8 h-8 rounded-[var(--radius-control)] bg-ok/10 text-ok grid place-items-center"><Radio className="w-4 h-4" /></span>
                                        <div>
                                            <h2 className="text-sm font-semibold text-ink">채널별 기록</h2>
                                            <p className="text-[11px] text-ink-faint">라이브 감지는 최근 30일 기준</p>
                                        </div>
                                    </div>
                                    <span className="text-xs text-ink-faint font-mono">{live.by_channel.length} channels</span>
                                </div>

                                {live.by_channel.length === 0 ? (
                                    <EmptyState icon={Database} title="아직 집계할 녹화가 없습니다" description="첫 녹화가 완료되면 채널별 통계가 이곳에 표시됩니다." />
                                ) : (
                                    <div className="overflow-x-auto">
                                        <table className="w-full min-w-[680px] text-sm">
                                            <thead>
                                                <tr className="bg-surface-3/60 border-b border-line">
                                                    <th className="text-left px-5 py-3 text-[11px] font-semibold text-ink-faint uppercase tracking-wider">채널</th>
                                                    <th className="text-right px-4 py-3 text-[11px] font-semibold text-ink-faint">녹화</th>
                                                    <th className="text-right px-4 py-3 text-[11px] font-semibold text-ink-faint">라이브 감지</th>
                                                    <th className="text-right px-4 py-3 text-[11px] font-semibold text-ink-faint">총 시간</th>
                                                    <th className="text-right px-5 py-3 text-[11px] font-semibold text-ink-faint">용량</th>
                                                </tr>
                                            </thead>
                                            <tbody className="divide-y divide-line/70">
                                                {live.by_channel.map((channel: ChannelLiveStat) => (
                                                    <tr key={channel.channel_id} className="hover:bg-surface-3/50 transition-colors">
                                                        <td className="px-5 py-3.5">
                                                            <p className="font-medium text-ink">{channel.channel_name}</p>
                                                            <p className="text-[11px] text-ink-faint font-mono mt-0.5">{channel.channel_id}</p>
                                                        </td>
                                                        <td className="px-4 py-3.5 text-right text-ink-muted font-mono">{channel.session_count}회</td>
                                                        <td className="px-4 py-3.5 text-right text-info font-mono font-medium">{channel.live_detected_count}일</td>
                                                        <td className="px-4 py-3.5 text-right text-ink-muted font-mono">{formatDuration(channel.total_duration_seconds)}</td>
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
                                            <h2 className="text-sm font-semibold text-ink">최근 녹화</h2>
                                            <p className="text-[11px] text-ink-faint">최근 완료된 10개 세션</p>
                                        </div>
                                    </div>
                                </div>

                                {recentSessions.length === 0 ? (
                                    <EmptyState icon={History} title="녹화 이력이 없습니다" description="완료된 세션이 여기에 쌓입니다." />
                                ) : (
                                    <div className="divide-y divide-line/70">
                                        {recentSessions.map((session: LiveSession, index: number) => (
                                            <div key={`${session.channel_name}-${session.ended_at}-${index}`} className="flex items-center gap-4 px-5 py-3.5 hover:bg-surface-3/50 transition-colors">
                                                <span className="w-2 h-2 rounded-full bg-ok shrink-0 shadow-[0_0_10px_var(--color-ok)]" />
                                                <div className="flex-1 min-w-0">
                                                    <p className="text-sm font-medium text-ink truncate">{session.channel_name}</p>
                                                    <p className="text-[11px] text-ink-faint mt-0.5">{formatDate(session.ended_at)}</p>
                                                </div>
                                                <div className="text-right shrink-0">
                                                    <p className="text-xs font-mono text-ink-muted">{formatDuration(session.duration_seconds)}</p>
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
