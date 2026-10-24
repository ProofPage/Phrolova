import { formatNumber, translate } from "../i18n";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Radio, WifiOff } from "lucide-react";
import { api, type Channel, type PlatformStatus } from "../api/client";
import { AddChannelForm } from "../components/dashboard/AddChannelForm";
import { ChannelDownloadModal } from "../components/dashboard/ChannelDownloadModal";
import { LiveDownloadCondition } from "../components/dashboard/LiveDownloadCondition";
import { RecordingChannelCard, RecordingChannelPanel } from "../components/dashboard/RecordingChannelCard";
import { RecordingJobsPanel } from "../components/dashboard/RecordingJobsPanel";
import { DashboardFilters, type StatusFilter, type ViewMode } from "../components/dashboard/DashboardFilters";
import { useConfirm } from "../components/ui/ConfirmModal";
import { Button, EmptyState, MetricCard, PageHeader } from "../components/ui/primitives";
import { useToast } from "../components/ui/Toast";
import { useChannelReorder } from "../hooks/useChannelReorder";
import { useChannelStream } from "../hooks/useChannelStream";
import { useCardGrid } from "../hooks/useCardGrid";
import { getBroadcastStatus, getChannelKey } from "../utils/channel";
import { getErrorMessage, localizedStatus } from "../utils/error";
import { useLanguage } from "../contexts/LanguageContext";

export default function Dashboard() {
    const { t } = useLanguage();
    const { channels, initialLoading, connectionError, fetchChannels } = useChannelStream();
    const { orderedChannels, sortMode, setSortMode, getReorderProps } = useChannelReorder(channels);
    const [platformStatus, setPlatformStatus] = useState<PlatformStatus | null>(null);
    const [expandedChannelKeys, setExpandedChannelKeys] = useState<Set<string>>(() => new Set());
    const [filter, setFilter] = useState<StatusFilter>("all");
    const [viewMode, setViewMode] = useState<ViewMode>(() => {
        const saved = localStorage.getItem("dashboardViewMode");
        return saved === "grid" || saved === "list" ? saved : "list";
    });
    const [globalTags, setGlobalTags] = useState<string[]>([]);
    const [selectedFilterTags, setSelectedFilterTags] = useState<string[]>([]);
    const [pendingActions, setPendingActions] = useState<Record<string, 'start' | 'stop' | 'remove'>>({});
    const actionRequests = useRef(new Set<string>());
    const autoRequests = useRef(new Set<string>());
    const [autoLoading, setAutoLoading] = useState(new Set<string>());
    const tagRequests = useRef(new Set<string>());
    const [tagLoading, setTagLoading] = useState(new Set<string>());
    const finishAction = (key: string) => {
        actionRequests.current.delete(key);
        setPendingActions(current => { const next = { ...current }; delete next[key]; return next; });
    };
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
        const key = getChannelKey(channel);
        if (actionRequests.current.has(key)) return;
        actionRequests.current.add(key);
        const displayName = channel.channel_name || channel.channel_id;
        const ok = await confirm({
            title: "live.removeChannel",
            message: t("live.removeChannelConfirm",{name:displayName}) + (channel.recording?.is_recording ? "\n"+t("live.activeRecordingsWillAlsoStop") : ""),
            confirmText: "live.remove",
            variant: "danger",
        });
        if (!ok) { actionRequests.current.delete(key); return; }
        setPendingActions(current => ({ ...current, [key]: 'remove' }));
        try {
            const platform = channel.platform || "chzzk";
            if (platform === "chzzk") await api.removeChannel(channel.channel_id);
            else await api.removePlatformChannel(platform, channel.channel_id);
            toast.success("live.channelRemoved");
            await fetchChannels();
        } catch {
            toast.error("live.couldNotRemoveChannel");
        } finally {
            finishAction(key);
        }
    };

    const handleStartRecord = async (channel: Channel) => {
        const key = getChannelKey(channel);
        if (actionRequests.current.has(key)) return;
        actionRequests.current.add(key);
        setPendingActions(current => ({ ...current, [key]: 'start' }));
        try {
            await api.startRecording(key);
            toast.success("live.startingRecording");
            await fetchChannels();
        } catch (error) {
            toast.error(getErrorMessage(error, "live.couldNotStartRecording"));
        } finally {
            finishAction(key);
        }
    };

    const handleStopRecord = async (channel: Channel) => {
        const key = getChannelKey(channel);
        if (actionRequests.current.has(key)) return;
        actionRequests.current.add(key);
        const ok = await confirm({
            title: "live.stopRecording",
            message: "live.stopTheCurrentRecording",
            confirmText: "live.stop",
            variant: "danger",
        });
        if (!ok) { actionRequests.current.delete(key); return; }
        setPendingActions(current => ({ ...current, [key]: 'stop' }));
        try {
            await api.stopRecording(key);
            toast.success("live.recordingStopped");
            await fetchChannels();
        } catch (error) {
            toast.error(getErrorMessage(error, "live.couldNotStopRecording"));
        } finally {
            finishAction(key);
        }
    };

    const handleStopAll = async () => {
        const ok = await confirm({
            title: "live.stopAllRecordings",
            message: "live.stopAllActiveRecordings",
            confirmText: "live.stopAllInDashboard",
            variant: "danger",
            requireTyping: "live.stopAllInDashboard",
        });
        if (!ok) return;
        try {
            const response = await api.stopAllRecordings();
            toast.success(localizedStatus(response.message, 'live.allRecordingsStopped'));
            fetchChannels();
        } catch (error) {
            toast.error(getErrorMessage(error, "live.couldNotStopAllRecordings"));
        }
    };

    const handleScanNow = async () => {
        try {
            await api.scanNow();
            toast.success("live.channelStatusCheckRequestedResultsWillAppearShortly");
        } catch {
            toast.error("live.couldNotCheckChannelStatus");
        }
    };

    const handleToggleAutoRecord = async (channel: Channel) => {
        const key = getChannelKey(channel);
        if (autoRequests.current.has(key) || actionRequests.current.has(key)) return;
        autoRequests.current.add(key);
        setAutoLoading(new Set(autoRequests.current));
        try {
            const platform = channel.platform || "chzzk";
            if (platform === "chzzk") await api.toggleAutoRecord(channel.channel_id);
            else await api.togglePlatformAutoRecord(platform, channel.channel_id);
            await fetchChannels();
        } catch {
            toast.error("live.couldNotChangeAutomaticRecordingSettings");
        } finally {
            autoRequests.current.delete(key);
            setAutoLoading(new Set(autoRequests.current));
        }
    };

    const handleChannelAddTag = async (channel: Channel, tag: string) => {
        const key = getChannelKey(channel);
        const tags = channel.tags || [];
        if (tags.includes(tag) || tagRequests.current.has(key)) return;
        tagRequests.current.add(key);
        setTagLoading(new Set(tagRequests.current));
        try {
            await api.updateChannelTags(getChannelKey(channel), [...tags, tag]);
            await fetchChannels();
        } catch {
            toast.error("live.couldNotAddTag");
        } finally {
            tagRequests.current.delete(key);
            setTagLoading(new Set(tagRequests.current));
        }
    };

    const handleChannelRemoveTag = async (channel: Channel, tag: string) => {
        const key = getChannelKey(channel);
        if (tagRequests.current.has(key)) return;
        tagRequests.current.add(key);
        setTagLoading(new Set(tagRequests.current));
        try {
            await api.updateChannelTags(getChannelKey(channel), (channel.tags || []).filter((item) => item !== tag));
            await fetchChannels();
        } catch {
            toast.error("live.couldNotRemoveTag");
        } finally {
            tagRequests.current.delete(key);
            setTagLoading(new Set(tagRequests.current));
        }
    };

    const handleCreateGlobalTag = async (tagName: string) => {
        try {
            const data = await api.createTag(tagName);
            setGlobalTags(data.tags);
        } catch {
            toast.error("live.couldNotCreateTag");
        }
    };

    const handleDeleteGlobalTag = async (tagName: string) => {
        // 전역 삭제라 이 태그가 붙어 있던 채널에서도 함께 떨어진다.
        // 몇 개가 영향받는지 먼저 보여주고 확인을 받는다.
        const affected = channels.filter((channel) => (channel.tags || []).includes(tagName)).length;
        const ok = await confirm({
            title: "live.removeTag",
            message: affected > 0
                ? t("common.deleteUsedTagConfirm",{tag:tagName,count:affected})
                : t("common.deleteTagConfirm",{tag:tagName}),
            confirmText: "common.delete",
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
            toast.success("common.tagDeleted", {tag:tagName});
        } catch (error) {
            toast.error(getErrorMessage(error, "live.couldNotRemoveTagInDashboard"));
        }
    };

    const liveCount = channels.filter((channel) => getBroadcastStatus(channel) === 'live').length;
    const offlineCount = channels.filter((channel) => getBroadcastStatus(channel) === 'offline').length;
    const recordingCount = channels.filter((channel) => channel.recording?.is_recording).length;
    const filteredChannels = orderedChannels.filter((channel) => {
        if (filter === "recording" && !channel.recording?.is_recording) return false;
        if (filter === "live" && getBroadcastStatus(channel) !== 'live') return false;
        if (filter === "offline" && getBroadcastStatus(channel) !== 'offline') return false;
        return selectedFilterTags.length === 0 || selectedFilterTags.some((tag) => (channel.tags || []).includes(tag));
    });
    const gridRef = useCardGrid(viewMode === 'grid', filteredChannels.map(getChannelKey).join('|'));

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

    const renderChannel = (channel: Channel, index: number) => {
        const key = getChannelKey(channel);
        const props = { ...itemProps, channel, isSelected: expandedChannelKeys.has(key), onSelect: () => setExpandedChannelKeys(current => {
            const next = new Set(current);
            if (next.has(key)) next.delete(key);
            else next.add(key);
            return next;
        }), ...getReorderProps(key, filteredChannels.map(getChannelKey)), isActionLoading: !!pendingActions[key], pendingAction: pendingActions[key], isAutoRecordLoading: autoLoading.has(key), isTagLoading: tagLoading.has(key) };
        const id = `channel-details-${encodeURIComponent(key)}`;
        const style = (detail: boolean) => ({ '--channel-order': index * 2 + Number(detail), '--channel-pair-order': Math.floor(index / 2) * 4 + (detail ? 2 : 0) + index % 2 }) as CSSProperties;
        return [
            <RecordingChannelCard key={key} {...props} detailsId={id} layoutStyle={style(false)} mode={viewMode} />,
            <RecordingChannelPanel key={`${key}:details`} channel={channel} id={id} selected={props.isSelected} onClose={() => {
                props.onSelect();
                document.querySelector<HTMLElement>(`[aria-controls="${id}"]`)?.focus();
            }} layoutStyle={style(true)} />,
        ];
    };

    const channelElements = filteredChannels.map(renderChannel);
    const visibleChannelElements = channelElements.flatMap((row, index) => {
        if (index % 2) return [];
        const next = channelElements[index + 1];
        return next ? [row[0], next[0], row[1], next[1]] : row;
    });

    return (
        <div className="product-page dashboard-page space-y-4">
            <PageHeader
                icon={Radio}
                eyebrow={t("live.liveStreamManagement")}
                title={t("live.title")}
                description={t("workspace.liveDescription")}
                meta={(
                    <div className="workspace-summary live-summary">
                        <MetricCard label={translate("live.monitoredChannels")} value={formatNumber(channels.length)} />
                        <MetricCard label={translate("live.title")} value={formatNumber(liveCount)} />
                        <MetricCard label={translate("live.recording")} value={formatNumber(recordingCount)} />
                    </div>
                )}
                metaPlacement="below"
                actions={<AddChannelForm channels={channels} platformStatus={platformStatus} onAdded={fetchChannels} />}
                actionsPlacement="below"
                variant="plain"
            />

            {connectionError && !initialLoading && (
                <div className="flex items-center gap-3 px-4 py-3 bg-danger/10 border border-danger/20 rounded-[var(--radius-card)] text-danger text-sm">
                    <WifiOff className="w-5 h-5 shrink-0" />
                    <span>{t("live.serverConnectionLostReconnecting")}</span>
                </div>
            )}

            <div className="flex flex-col gap-3">
                <DashboardFilters
                    filter={filter}
                    onFilterChange={setFilter}
                    sortMode={sortMode}
                    onSortModeChange={setSortMode}
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
                    offlineCount={offlineCount}
                    onScanNow={handleScanNow}
                    onStopAll={handleStopAll}
                ><LiveDownloadCondition /></DashboardFilters>
            </div>

            {initialLoading ? <div className="space-y-2" aria-label={t("live.loadingChannelInformation")} aria-busy="true">{[1,2,3].map(item => <div key={item} className="flex items-center gap-3 border-b border-line py-3"><div className="skeleton size-8 rounded-full" /><div className="flex-1 space-y-2"><div className="skeleton h-3 w-1/3" /><div className="skeleton h-3 w-1/2" /></div></div>)}</div>
            : filteredChannels.length === 0 ? <EmptyState icon={Radio} title={channels.length === 0 ? translate("live.noChannelsAddedYet") : translate("live.noChannelsMatchTheseFilters")} description={channels.length === 0 ? translate("live.addAChannelToMonitorItsLiveStatusAndRecordAutomatically") : translate("live.changeTheStatusOrTagFilters")} action={channels.length > 0 ? <Button onClick={() => { setFilter("all"); setSelectedFilterTags([]); }}>{translate("live.resetFilters")}</Button> : undefined} />
            : <div ref={gridRef} className={viewMode === 'grid' ? 'dashboard-channel-grid' : 'dashboard-channel-list'}>{visibleChannelElements}</div>}
            <RecordingJobsPanel visibleIds={filteredChannels.flatMap(channel=>channel.postprocess?[channel.postprocess.id]:[])}/>
            {editingChannel && <ChannelDownloadModal
                platform={editingChannel.platform || "chzzk"}
                name={editingChannel.channel_name || editingChannel.channel_id}
                channel={editingChannel}
                onClose={() => setEditingChannel(null)}
                onSave={async (options) => {
                    await api.updateChannelDownloadOptions(editingChannel, options);
                    toast.success(translate("live.channelDownloadSettingsSaved"));
                    fetchChannels();
                }}
            />}
        </div>
    );
}
