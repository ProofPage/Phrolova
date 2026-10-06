import { useEffect, useState } from "react";
import { Radio, WifiOff } from "lucide-react";
import { api, type Channel, type PlatformStatus } from "../api/client";
import { AddChannelForm } from "../components/dashboard/AddChannelForm";
import { ChannelDownloadModal } from "../components/dashboard/ChannelDownloadModal";
import { LiveDownloadCondition } from "../components/dashboard/LiveDownloadCondition";
import { ChannelCard } from "../components/dashboard/ChannelCard";
import { ChannelRow } from "../components/dashboard/ChannelRow";
import { DashboardFilters, type StatusFilter, type ViewMode } from "../components/dashboard/DashboardFilters";
import { useConfirm } from "../components/ui/ConfirmModal";
import { Button, EmptyState, PageHeader } from "../components/ui/primitives";
import { useToast } from "../components/ui/Toast";
import { useChannelReorder } from "../hooks/useChannelReorder";
import { useChannelStream } from "../hooks/useChannelStream";
import { getChannelKey } from "../utils/channel";
import { getErrorMessage } from "../utils/error";
import { useLanguage } from "../contexts/LanguageContext";

function DashboardMetric({ label, value, tone }: { label: string; value: number; tone?: "live" | "recording" }) {
    const { t } = useLanguage();
    return (
        <div className="dashboard-metric">
            <span className={tone === "live" && value > 0 ? "dashboard-metric-dot is-live" : tone === "recording" && value > 0 ? "dashboard-metric-dot is-recording" : "dashboard-metric-dot"} />
            <span>{t(label)}</span>
            <strong>{value}</strong>
        </div>
    );
}

export default function Dashboard() {
    const { t } = useLanguage();
    const { channels, initialLoading, connectionError, fetchChannels } = useChannelStream();
    const { orderedChannels, getReorderProps } = useChannelReorder(channels);
    const [platformStatus, setPlatformStatus] = useState<PlatformStatus | null>(null);
    const [expandedChannelKeys, setExpandedChannelKeys] = useState<Set<string>>(() => new Set());
    const [filter, setFilter] = useState<StatusFilter>("all");
    const [viewMode, setViewMode] = useState<ViewMode>(() => {
        const saved = localStorage.getItem("dashboardViewMode");
        return saved === "grid" || saved === "list" ? saved : "list";
    });
    const [globalTags, setGlobalTags] = useState<string[]>([]);
    const [selectedFilterTags, setSelectedFilterTags] = useState<string[]>([]);
    const [actionLoading, setActionLoading] = useState<string | null>(null);
    const [editingChannel, setEditingChannel] = useState<Channel | null>(null);
    const toast = useToast();
    const confirm = useConfirm();

    useEffect(() => {
        localStorage.setItem("dashboardViewMode", viewMode);
    }, [viewMode]);

    useEffect(() => {
        api.getPlatformStatus().then(setPlatformStatus).catch(() => {});
        api.getTags().then((data) => setGlobalTags(data.tags)).catch(() => {});
    }, []);

    const handleRemoveChannel = async (channel: Channel) => {
        const displayName = channel.channel_name || channel.channel_id;
        const ok = await confirm({
            title: "채널 제거",
            message: `'${displayName}' 채널을 감시 목록에서 제거할까요?`,
            confirmText: "제거",
            variant: "danger",
        });
        if (!ok) return;
        try {
            const platform = channel.platform || "chzzk";
            if (platform === "chzzk") await api.removeChannel(channel.channel_id);
            else await api.removePlatformChannel(platform, channel.channel_id);
            toast.success("채널이 제거되었습니다.");
            fetchChannels();
        } catch {
            toast.error("채널 제거에 실패했습니다.");
        }
    };

    const handleStartRecord = async (channel: Channel) => {
        if (actionLoading) return;
        const key = getChannelKey(channel);
        setActionLoading(key);
        try {
            await api.startRecording(key);
            toast.success("녹화를 시작합니다.");
            fetchChannels();
        } catch (error) {
            toast.error(getErrorMessage(error, "녹화 시작에 실패했습니다."));
        } finally {
            setActionLoading(null);
        }
    };

    const handleStopRecord = async (channel: Channel) => {
        if (actionLoading) return;
        const ok = await confirm({
            title: "녹화 중지",
            message: "현재 진행 중인 녹화를 중지할까요?",
            confirmText: "중지",
            variant: "danger",
        });
        if (!ok) return;
        const key = getChannelKey(channel);
        setActionLoading(key);
        try {
            await api.stopRecording(key);
            toast.success("녹화가 중지되었습니다.");
            fetchChannels();
        } catch (error) {
            toast.error(getErrorMessage(error, "녹화 중지에 실패했습니다."));
        } finally {
            setActionLoading(null);
        }
    };

    const handleStopAll = async () => {
        const ok = await confirm({
            title: "전체 녹화 중지",
            message: "현재 진행 중인 모든 녹화를 중지하시겠습니까?",
            confirmText: "모두 중지",
            variant: "danger",
            requireTyping: "모두 중지",
        });
        if (!ok) return;
        try {
            const response = await api.stopAllRecordings();
            toast.success(response.message);
            fetchChannels();
        } catch (error) {
            toast.error(getErrorMessage(error, "전체 녹화 중지에 실패했습니다."));
        }
    };

    const handleScanNow = async () => {
        try {
            await api.scanNow();
            toast.success("채널 상태 확인을 요청했습니다. 잠시 후 결과가 반영됩니다.");
        } catch {
            toast.error("채널 상태를 확인하지 못했습니다.");
        }
    };

    const handleToggleAutoRecord = async (channel: Channel) => {
        try {
            const platform = channel.platform || "chzzk";
            if (platform === "chzzk") await api.toggleAutoRecord(channel.channel_id);
            else await api.togglePlatformAutoRecord(platform, channel.channel_id);
            fetchChannels();
        } catch {
            toast.error("자동 녹화 설정 변경에 실패했습니다.");
        }
    };

    const handleChannelAddTag = async (channel: Channel, tag: string) => {
        const tags = channel.tags || [];
        if (tags.includes(tag)) return;
        try {
            await api.updateChannelTags(getChannelKey(channel), [...tags, tag]);
            fetchChannels();
        } catch {
            toast.error("태그 추가 실패");
        }
    };

    const handleChannelRemoveTag = async (channel: Channel, tag: string) => {
        try {
            await api.updateChannelTags(getChannelKey(channel), (channel.tags || []).filter((item) => item !== tag));
            fetchChannels();
        } catch {
            toast.error("태그 제거 실패");
        }
    };

    const handleCreateGlobalTag = async (tagName: string) => {
        try {
            const data = await api.createTag(tagName);
            setGlobalTags(data.tags);
        } catch {
            toast.error("태그 생성 실패");
        }
    };

    const handleDeleteGlobalTag = async (tagName: string) => {
        // 전역 삭제라 이 태그가 붙어 있던 채널에서도 함께 떨어진다.
        // 몇 개가 영향받는지 먼저 보여주고 확인을 받는다.
        const affected = channels.filter((channel) => (channel.tags || []).includes(tagName)).length;
        const ok = await confirm({
            title: "태그 삭제",
            message: affected > 0
                ? `'${tagName}' 태그를 삭제하면 이 태그가 붙은 채널 ${affected}개에서도 함께 떨어집니다.\n채널과 녹화 파일은 그대로 남습니다.`
                : `'${tagName}' 태그를 삭제할까요?`,
            confirmText: "삭제",
            variant: "danger",
        });
        if (!ok) return;

        try {
            await api.deleteTag(tagName);
            const data = await api.getTags();
            setGlobalTags(data.tags);
            // 지운 태그가 필터에 걸려 있으면 아무 채널도 안 보이게 되므로 함께 푼다.
            setSelectedFilterTags((current) => current.filter((tag) => tag !== tagName));
            fetchChannels();
            toast.success(`'${tagName}' 태그를 삭제했습니다.`);
        } catch (error) {
            toast.error(getErrorMessage(error, "태그 삭제에 실패했습니다."));
        }
    };

    const liveCount = channels.filter((channel) => channel.is_live).length;
    const recordingCount = channels.filter((channel) => channel.recording?.is_recording).length;
    const filteredChannels = orderedChannels.filter((channel) => {
        if (filter === "recording" && !channel.recording?.is_recording) return false;
        if (filter === "live" && !channel.is_live) return false;
        if (filter === "offline" && channel.is_live) return false;
        return selectedFilterTags.length === 0 || selectedFilterTags.some((tag) => (channel.tags || []).includes(tag));
    });

    useEffect(() => {
        if (initialLoading) return;
        const availableKeys = new Set(channels.map(getChannelKey));
        setExpandedChannelKeys(current => {
            const next = new Set([...current].filter(key => availableKeys.has(key)));
            return next.size === current.size ? current : next;
        });
    }, [channels, initialLoading]);

    const itemProps = {
        onStartRecord: handleStartRecord,
        onStopRecord: handleStopRecord,
        onRemove: handleRemoveChannel,
        onToggleAutoRecord: handleToggleAutoRecord,
        onEditDownloadSettings: setEditingChannel,
        globalTags,
        onAddTag: handleChannelAddTag,
        onRemoveTag: handleChannelRemoveTag,
        onCreateTag: handleCreateGlobalTag,
    };

    const renderChannel = (channel: Channel) => {
        const key = getChannelKey(channel);
        const props = { ...itemProps, channel, isSelected: expandedChannelKeys.has(key), onSelect: () => setExpandedChannelKeys(current => {
            const next = new Set(current);
            if (next.has(key)) next.delete(key);
            else next.add(key);
            return next;
        }), ...getReorderProps(key), isActionLoading: actionLoading === key };
        return viewMode === "grid" ? <ChannelCard key={key} {...props} /> : <ChannelRow key={key} {...props} />;
    };

    return (
        <div className="product-page dashboard-page space-y-4">
            <PageHeader
                icon={Radio}
                eyebrow={t("실시간 방송 관리")}
                title={t("라이브")}
                description={t("등록한 채널의 방송 상태와 녹화를 관리합니다.")}
                meta={(
                    <>
                        <DashboardMetric label="감시 채널" value={channels.length} />
                        <DashboardMetric label="라이브" value={liveCount} tone="live" />
                        <DashboardMetric label="녹화 중" value={recordingCount} tone="recording" />
                    </>
                )}
                actions={<AddChannelForm platformStatus={platformStatus} onAdded={fetchChannels} />}
                actionsPlacement="below"
                variant="plain"
            />

            {connectionError && !initialLoading && (
                <div className="flex items-center gap-3 px-4 py-3 bg-danger/10 border border-danger/20 rounded-[var(--radius-card)] text-danger text-sm">
                    <WifiOff className="w-5 h-5 shrink-0" />
                    <span>{t("서버 연결이 끊겼습니다. 다시 연결하는 중입니다.")}</span>
                </div>
            )}

            <div className="flex flex-col gap-3">
                <DashboardFilters
                    filter={filter}
                    onFilterChange={setFilter}
                    globalTags={globalTags}
                    selectedTags={selectedFilterTags}
                    onSelectedTagsChange={setSelectedFilterTags}
                    onCreateTag={handleCreateGlobalTag}
                    onDeleteTag={handleDeleteGlobalTag}
                    viewMode={viewMode}
                    onViewModeChange={setViewMode}
                    recordingCount={recordingCount}
                    totalCount={channels.length}
                    liveCount={liveCount}
                    offlineCount={channels.length - liveCount}
                    onScanNow={handleScanNow}
                    onStopAll={handleStopAll}
                ><LiveDownloadCondition /></DashboardFilters>
            </div>

            {initialLoading ? <div className="space-y-2" aria-label={t("채널 정보를 불러오는 중")} aria-busy="true">{[1,2,3].map(item => <div key={item} className="flex items-center gap-3 border-b border-line py-3"><div className="skeleton size-8 rounded-full" /><div className="flex-1 space-y-2"><div className="skeleton h-3 w-1/3" /><div className="skeleton h-3 w-1/2" /></div></div>)}</div>
            : filteredChannels.length === 0 ? <EmptyState icon={Radio} title={channels.length === 0 ? "등록된 채널이 없습니다." : "필터 조건에 맞는 채널이 없습니다."} description={channels.length === 0 ? "채널을 추가하면 방송 상태를 확인하고 자동으로 녹화할 수 있습니다." : "상태 또는 태그 필터를 변경해 보세요."} action={channels.length > 0 ? <Button onClick={() => { setFilter("all"); setSelectedFilterTags([]); }}>필터 초기화</Button> : undefined} />
            : viewMode === "grid" ? <div className="grid min-w-0 grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">{filteredChannels.map(renderChannel)}</div>
            : <div className="min-w-0 space-y-2">{filteredChannels.map(renderChannel)}</div>}
            {editingChannel && <ChannelDownloadModal
                platform={editingChannel.platform || "chzzk"}
                name={editingChannel.channel_name || editingChannel.channel_id}
                channel={editingChannel}
                onClose={() => setEditingChannel(null)}
                onSave={async (options) => {
                    await api.updateChannelDownloadOptions(editingChannel, options);
                    toast.success("채널 다운로드 설정이 저장되었습니다.");
                    fetchChannels();
                }}
            />}
        </div>
    );
}
