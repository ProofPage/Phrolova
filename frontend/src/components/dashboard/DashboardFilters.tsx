import { ChevronDown, LayoutGrid, List, RefreshCw, SlidersHorizontal, Square } from "lucide-react";
import type { ReactNode } from "react";
import { TagManager } from "../ui/TagManager";
import { Button } from "../ui/primitives";
import { useLanguage } from "../../contexts/LanguageContext";

export type StatusFilter = "all" | "recording" | "live" | "offline";
export type ViewMode = "grid" | "list";

const FILTERS: { value: StatusFilter; label: string; selectedClass: string }[] = [
    { value: "all", label: "전체", selectedClass: "text-ink" },
    { value: "recording", label: "녹화 중", selectedClass: "text-ok" },
    { value: "live", label: "라이브", selectedClass: "text-live" },
    { value: "offline", label: "오프라인", selectedClass: "text-ink-muted" },
];

interface Props {
    children?: ReactNode;
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
    children,
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
    const { t } = useLanguage();
    return (
        <div className="flex flex-col gap-3 p-3 sm:p-4 bg-surface-2 border border-line rounded-[var(--radius-card)] surface-raise">
            <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
                <div role="group" aria-label={t("채널 상태 필터")} className="flex flex-wrap gap-1 p-1 bg-surface-3 rounded-[var(--radius-control)]">
                    {FILTERS.map((option) => (
                        <button
                            key={option.value}
                            type="button"
                            aria-pressed={filter === option.value}
                            onClick={() => onFilterChange(option.value)}
                            className={`px-3 py-1.5 rounded-md text-[13px] font-medium transition-all whitespace-nowrap ${filter === option.value ? `bg-surface-1 shadow-sm ${option.selectedClass}` : "text-ink-faint hover:text-ink-muted"}`}
                        >
                            {t(option.label)}
                        </button>
                    ))}
                </div>

                <div className="flex flex-wrap items-center gap-2 shrink-0">
                    <Button icon={RefreshCw} onClick={onScanNow} className="px-3 py-2 whitespace-nowrap shrink-0">{t("즉시 스캔")}</Button>
                    <Button variant="danger" icon={Square} onClick={onStopAll} disabled={recordingCount === 0} className="px-3 py-2 whitespace-nowrap shrink-0">{t("전체 중지")}</Button>
                    <div role="group" aria-label={t("채널 보기 방식")} className="flex bg-surface-3 border border-line rounded-[var(--radius-control)] p-1 ml-auto">
                        <button
                            type="button"
                            onClick={() => onViewModeChange("grid")}
                            className={`p-1.5 rounded-md transition-colors ${viewMode === "grid" ? "bg-surface-4 text-ink" : "text-ink-faint hover:text-ink"}`}
                            title={t("카드로 보기")}
                            aria-label={t("카드로 보기")}
                            aria-pressed={viewMode === "grid"}
                        >
                            <LayoutGrid className="w-4 h-4" />
                        </button>
                        <button
                            type="button"
                            onClick={() => onViewModeChange("list")}
                            className={`p-1.5 rounded-md transition-colors ${viewMode === "list" ? "bg-surface-4 text-ink" : "text-ink-faint hover:text-ink"}`}
                            title={t("목록으로 보기")}
                            aria-label={t("목록으로 보기")}
                            aria-pressed={viewMode === "list"}
                        >
                            <List className="w-4 h-4" />
                        </button>
                    </div>
                </div>
            </div>

            <details className="dashboard-options border-t border-line/80 pt-2">
                <summary className="flex cursor-pointer list-none items-center gap-2 rounded-lg px-2 py-1.5 text-[12px] font-medium text-ink-muted hover:bg-surface-3 hover:text-ink">
                    <SlidersHorizontal className="size-4 text-ink-faint" />{t("채널 태그")} · {t("기본 녹화 조건")}
                    {selectedTags.length > 0 && <span className="rounded-full bg-[var(--primary-dim)] px-1.5 text-[10px] text-[var(--primary)]">{selectedTags.length}</span>}
                    <ChevronDown className="ml-auto size-4 text-ink-faint transition-transform" />
                </summary>
                <div className="space-y-3 px-2 pt-3">
                    <div className="flex flex-wrap items-center gap-y-2">
                        <span className="text-[10px] font-bold tracking-[0.14em] text-ink-faint mr-3 shrink-0">{t("채널 태그")}</span>
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
