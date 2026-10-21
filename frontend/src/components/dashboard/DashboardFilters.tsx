import { ChevronDown, LayoutGrid, List, RefreshCw, SlidersHorizontal, Square } from "lucide-react";
import type { ReactNode } from "react";
import { TagManager } from "../ui/TagManager";
import { Button, Select } from "../ui/primitives";
import { useLanguage } from "../../contexts/LanguageContext";
import type { ChannelSortMode } from "../../utils/channelSort";

export type StatusFilter = "all" | "recording" | "live" | "offline";
export type ViewMode = "grid" | "list";

const FILTERS: { value: StatusFilter; label: string; selectedClass: string; countKey: "totalCount" | "recordingCount" | "liveCount" | "offlineCount" }[] = [
    { value: "all", label: "live.all", selectedClass: "text-ink", countKey: "totalCount" },
    { value: "recording", label: "live.recording", selectedClass: "text-ok", countKey: "recordingCount" },
    { value: "live", label: "live.title", selectedClass: "text-live", countKey: "liveCount" },
    { value: "offline", label: "live.offline", selectedClass: "text-ink-muted", countKey: "offlineCount" },
];

interface Props {
    children?: ReactNode;
    filter: StatusFilter;
    onFilterChange: (filter: StatusFilter) => void;
    sortMode: ChannelSortMode;
    onSortModeChange: (mode: ChannelSortMode) => void;
    globalTags: string[];
    selectedTags: string[];
    onSelectedTagsChange: (tags: string[]) => void;
    onCreateTag: (tag: string) => void;
    onDeleteTag: (tag: string) => void;
    viewMode: ViewMode;
    onViewModeChange: (mode: ViewMode) => void;
    recordingCount: number;
    totalCount: number;
    liveCount: number;
    offlineCount: number;
    onScanNow: () => void;
    onStopAll: () => void;
}

export function DashboardFilters({
    children,
    filter,
    onFilterChange,
    sortMode,
    onSortModeChange,
    globalTags,
    selectedTags,
    onSelectedTagsChange,
    onCreateTag,
    onDeleteTag,
    viewMode,
    onViewModeChange,
    recordingCount,
    totalCount,
    liveCount,
    offlineCount,
    onScanNow,
    onStopAll,
}: Props) {
    const { t } = useLanguage();
    return (
        <div className="dashboard-toolbar flex flex-col gap-2 py-2">
            <div className="dashboard-toolbar-main">
                <div className="dashboard-status-filters min-w-0 max-w-full overflow-x-auto">
                <div role="group" aria-label={t("live.channelStatusFilter")} className="flex w-max min-w-full gap-1">
                    {FILTERS.map((option) => {
                        const count = { totalCount, recordingCount, liveCount, offlineCount }[option.countKey];
                        return (
                        <button
                            key={option.value}
                            type="button"
                            aria-pressed={filter === option.value}
                            onClick={() => onFilterChange(option.value)}
                            className={`dashboard-filter min-h-11 sm:min-h-8 px-2.5 py-1.5 rounded-[5px] text-[12px] font-medium transition-all whitespace-nowrap ${filter === option.value ? `is-selected ${option.selectedClass}` : "text-ink-faint hover:text-ink-muted"}`}
                        >
                            {t(option.label)} <span className="ml-1 tabular-nums opacity-75">{count}</span>
                        </button>
                        );
                    })}
                </div>
                </div>

                <div className="dashboard-toolbar-actions">
                    <Button icon={RefreshCw} onClick={onScanNow} title={t("live.checkTheLiveStatusOfRegisteredChannelsAgain")} aria-label={t("live.checkLiveStatus")} className="dashboard-scan px-3 py-2 whitespace-nowrap shrink-0"><span>{t("live.checkLiveStatus")}</span></Button>
                    <Button variant="danger" icon={Square} onClick={onStopAll} disabled={recordingCount === 0} aria-label={t("live.stopAllRecordings")} className="px-3 py-2 whitespace-nowrap shrink-0"><span className="hidden sm:inline">{t("live.stopAllRecordings")}</span><span className="sm:hidden">{t("live.stopAll")}</span></Button>
                    <Select
                        aria-label={t("live.sortOrder")}
                        value={sortMode}
                        onChange={(e) => onSortModeChange(e.target.value as ChannelSortMode)}
                        options={[
                            { value: "live-first-name", label: t("live.liveFirstAndNameOrder") },
                            { value: "name", label: t("live.nameOrder") },
                            { value: "manual", label: t("live.manualOrder") },
                        ]}
                        className="dashboard-sort-select min-w-[130px] text-[12px] h-9 sm:h-8"
                    />
                    <div role="group" aria-label={t("live.channelView")} className="dashboard-view-toggle flex bg-surface-3/80 rounded-[var(--radius-control)] p-1">
                        <button
                            type="button"
                            onClick={() => onViewModeChange("grid")}
                            className={`touch-control grid size-11 sm:size-8 place-items-center rounded-md transition-colors ${viewMode === "grid" ? "bg-surface-1 text-ink shadow-sm" : "text-ink-faint hover:text-ink"}`}
                            title={t("live.gridView")}
                            aria-label={t("live.gridView")}
                            aria-pressed={viewMode === "grid"}
                        >
                            <LayoutGrid className="w-4 h-4" />
                        </button>
                        <button
                            type="button"
                            onClick={() => onViewModeChange("list")}
                            className={`touch-control grid size-11 sm:size-8 place-items-center rounded-md transition-colors ${viewMode === "list" ? "bg-surface-1 text-ink shadow-sm" : "text-ink-faint hover:text-ink"}`}
                            title={t("live.listView")}
                            aria-label={t("live.listView")}
                            aria-pressed={viewMode === "list"}
                        >
                            <List className="w-4 h-4" />
                        </button>
                    </div>
                </div>
            </div>

            <details className="dashboard-options border-t border-line/80 pt-2">
                <summary className="flex cursor-pointer list-none items-center gap-2 rounded-lg px-2 py-1.5 text-[12px] font-medium text-ink-muted hover:bg-surface-3 hover:text-ink">
                    <SlidersHorizontal className="size-4 text-ink-faint" />{t("live.channelTags")} · {t("live.defaultRecordingCondition")}
                    {selectedTags.length > 0 && <span className="rounded-full bg-[var(--primary-dim)] px-1.5 text-[10px] text-[var(--primary)]">{selectedTags.length}</span>}
                    <ChevronDown className="ml-auto size-4 text-ink-faint transition-transform" />
                </summary>
                <div className="space-y-3 px-2 pt-3">
                    <div className="flex flex-wrap items-center gap-y-2">
                        <span className="text-[10px] font-bold tracking-[0.14em] text-ink-faint mr-3 shrink-0">{t("live.channelTags")}</span>
                        <TagManager
                            availableTags={globalTags}
                            selectedTags={selectedTags}
                            onAddTag={(tag) => onSelectedTagsChange([...selectedTags, tag])}
                            onRemoveTag={(tag) => onSelectedTagsChange(selectedTags.filter((item) => item !== tag))}
                            onCreateTag={onCreateTag}
                            onDeleteTag={onDeleteTag}
                        />
                    </div>
                    {children}
                </div>
            </details>
        </div>
    );
}
