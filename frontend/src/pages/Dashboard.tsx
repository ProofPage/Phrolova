import { useEffect, useState } from "react";
import { GripVertical, Radio, WifiOff } from "lucide-react";
import { api, type Channel, type PlatformStatus } from "../api/client";
import { AddChannelForm } from "../components/dashboard/AddChannelForm";
import { ChannelCard } from "../components/dashboard/ChannelCard";
import { ChannelRow } from "../components/dashboard/ChannelRow";
import { DashboardFilters, type StatusFilter, type ViewMode } from "../components/dashboard/DashboardFilters";
import { useConfirm } from "../components/ui/ConfirmModal";
import { Badge, EmptyState, PageHeader } from "../components/ui/primitives";
import { useToast } from "../components/ui/Toast";
import { useChannelReorder } from "../hooks/useChannelReorder";
import { useChannelStream } from "../hooks/useChannelStream";
import { getChannelKey } from "../utils/channel";
import { getErrorMessage } from "../utils/error";

export default function Dashboard() {
    const { channels, initialLoading, connectionError, fetchChannels } = useChannelStream();
    const { orderedChannels, getReorderProps } = useChannelReorder(channels);
    const [platformStatus, setPlatformStatus] = useState<PlatformStatus | null>(null);
    const [filter, setFilter] = useState<StatusFilter>("all");
    const [viewMode, setViewMode] = useState<ViewMode>(() => (localStorage.getItem("dashboardViewMode") as ViewMode) || "grid");
    const [globalTags, setGlobalTags] = useState<string[]>([]);
    const [selectedFilterTags, setSelectedFilterTags] = useState<string[]>([]);
    const [actionLoading, setActionLoading] = useState<string | null>(null);
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
            toast.success("즉시 스캔 요청됨. 잠시 후 상태가 업데이트됩니다.");
        } catch {
            toast.error("즉시 스캔 요청에 실패했습니다.");
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

    const itemProps = {
        onStartRecord: handleStartRecord,
        onStopRecord: handleStopRecord,
        onRemove: handleRemoveChannel,
        onToggleAutoRecord: handleToggleAutoRecord,
        globalTags,
        onAddTag: handleChannelAddTag,
        onRemoveTag: handleChannelRemoveTag,
        onCreateTag: handleCreateGlobalTag,
    };

    return (
        <div className="space-y-6">
            <PageHeader
                icon={Radio}
                eyebrow="Live control"
                title="Live Dashboard"
                description="방송 상태를 한눈에 확인하고, 녹화와 채널 우선순위를 한 화면에서 제어합니다."
                meta={(
                    <>
                        <Badge tone="primary">{channels.length} monitored</Badge>
                        <Badge tone={liveCount > 0 ? "danger" : "neutral"}>{liveCount} live</Badge>
                        <Badge tone={recordingCount > 0 ? "ok" : "neutral"}>{recordingCount} recording</Badge>
                    </>
                )}
                actions={<AddChannelForm platformStatus={platformStatus} onAdded={fetchChannels} />}
            />

            {connectionError && !initialLoading && (
                <div className="flex items-center gap-3 px-4 py-3 bg-danger/10 border border-danger/20 rounded-[var(--radius-card)] text-danger text-sm">
                    <WifiOff className="w-5 h-5 shrink-0" />
                    <span>서버와 연결이 끊어졌습니다. 자동으로 재연결을 시도합니다...</span>
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
                    onScanNow={handleScanNow}
                    onStopAll={handleStopAll}
                />
                {channels.length > 1 && (
                    <p className="flex items-center gap-1.5 px-1 text-[11px] text-ink-faint">
                        <GripVertical className="w-3.5 h-3.5" /> 그립을 끌거나 포커스 후 방향키로 표시 순서를 바꿀 수 있습니다. 순서는 이 브라우저에 저장됩니다.
                    </p>
                )}
            </div>

            <div className={viewMode === "grid" ? "grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4" : "flex flex-col gap-3 overflow-x-auto"}>
                {initialLoading && [1, 2, 3].map((item) => (
                    <div key={item} className={`bg-surface-2 border border-line rounded-[var(--radius-card)] overflow-hidden ${viewMode === "list" ? "flex min-w-[900px]" : ""}`}>
                        <div className={`skeleton ${viewMode === "list" ? "w-48 min-h-[150px] shrink-0" : "w-full aspect-video"}`} />
                        <div className="p-4 space-y-3 flex-1"><div className="skeleton h-4 rounded w-3/4" /><div className="skeleton h-3 rounded w-1/2" /><div className="skeleton h-8 rounded mt-6" /></div>
                    </div>
                ))}

                {!initialLoading && filteredChannels.map((channel) => {
                    const key = getChannelKey(channel);
                    const props = {
                        ...itemProps,
                        channel,
                        ...getReorderProps(key),
                        isActionLoading: actionLoading === key,
                    };
                    return viewMode === "grid" ? <ChannelCard key={key} {...props} /> : <ChannelRow key={key} {...props} />;
                })}

                {!initialLoading && filteredChannels.length === 0 && (
                    <div className={viewMode === "grid" ? "col-span-full" : ""}>
                        <EmptyState icon={Radio} title={channels.length === 0 ? "감시 중인 채널이 없습니다." : "필터 조건에 맞는 채널이 없습니다."} description={channels.length === 0 ? "위에서 채널 ID를 입력해 모니터링을 시작하세요." : "상태 또는 태그 필터를 변경해 보세요."} />
                    </div>
                )}
            </div>
        </div>
    );
}
