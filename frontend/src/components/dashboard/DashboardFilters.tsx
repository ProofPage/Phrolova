import { LayoutGrid, List, RefreshCw, Square } from "lucide-react";
import { TagManager } from "../ui/TagManager";
import { Button } from "../ui/primitives";

export type StatusFilter = "all" | "recording" | "live" | "offline";
export type ViewMode = "grid" | "list";

const FILTERS: { value: StatusFilter; label: string; selectedClass: string }[] = [
    { value: "all", label: "전체", selectedClass: "text-ink" },
    { value: "recording", label: "녹화 중", selectedClass: "text-ok" },
    { value: "live", label: "라이브", selectedClass: "text-live" },
    { value: "offline", label: "오프라인", selectedClass: "text-ink-muted" },
];

interface Props {
    filter: StatusFilter;
    onFilterChange: (filter: StatusFilter) => void;
    globalTags: string[];
    selectedTags: string[];
    onSelectedTagsChange: (tags: string[]) => void;
    onCreateTag: (tag: string) => void;
    onDeleteTag: (tag: string) => void;
    viewMode: ViewMode;
    onViewModeChange: (mode: ViewMode) => void;
    recordingCount: number;
    onScanNow: () => void;
    onStopAll: () => void;
}

export function DashboardFilters({
    filter,
    onFilterChange,
    globalTags,
    selectedTags,
    onSelectedTagsChange,
    onCreateTag,
    onDeleteTag,
    viewMode,
    onViewModeChange,
    recordingCount,
    onScanNow,
    onStopAll,
}: Props) {
    return (
        <div className="flex flex-col gap-3 p-3 sm:p-4 bg-surface-2 border border-line rounded-[var(--radius-card)] surface-raise">
            <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
                <div className="flex gap-1 p-1 bg-surface-3 rounded-[var(--radius-control)] overflow-x-auto">
                    {FILTERS.map((option) => (
                        <button
                            key={option.value}
                            onClick={() => onFilterChange(option.value)}
                            className={`px-3 py-1.5 rounded-md text-[13px] font-medium transition-all whitespace-nowrap ${filter === option.value ? `bg-surface-1 shadow-sm ${option.selectedClass}` : "text-ink-faint hover:text-ink-muted"}`}
                        >
                            {option.label}
                        </button>
                    ))}
                </div>

                <div className="flex items-center gap-2 shrink-0 overflow-x-auto">
                    <Button icon={RefreshCw} onClick={onScanNow} className="px-3 py-2">즉시 스캔</Button>
                    <Button variant="danger" icon={Square} onClick={onStopAll} disabled={recordingCount === 0} className="px-3 py-2">전체 중지</Button>
                    <div className="flex bg-surface-3 border border-line rounded-[var(--radius-control)] p-1 ml-auto">
                        <button
                            type="button"
                            onClick={() => onViewModeChange("grid")}
                            className={`p-1.5 rounded-md transition-colors ${viewMode === "grid" ? "bg-surface-4 text-ink" : "text-ink-faint hover:text-ink"}`}
                            title="그리드 뷰"
                        >
                            <LayoutGrid className="w-4 h-4" />
                        </button>
                        <button
                            type="button"
                            onClick={() => onViewModeChange("list")}
                            className={`p-1.5 rounded-md transition-colors ${viewMode === "list" ? "bg-surface-4 text-ink" : "text-ink-faint hover:text-ink"}`}
                            title="리스트 뷰"
                        >
                            <List className="w-4 h-4" />
                        </button>
                    </div>
                </div>
            </div>

            <div className="flex flex-wrap items-center gap-y-2 pt-3 border-t border-line/80">
                <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-ink-faint mr-3 shrink-0">Tag filter</span>
                <TagManager
                    availableTags={globalTags}
                    selectedTags={selectedTags}
                    onAddTag={(tag) => onSelectedTagsChange([...selectedTags, tag])}
                    onRemoveTag={(tag) => onSelectedTagsChange(selectedTags.filter((item) => item !== tag))}
                    onCreateTag={onCreateTag}
                    onDeleteTag={onDeleteTag}
                />
            </div>
        </div>
    );
}
