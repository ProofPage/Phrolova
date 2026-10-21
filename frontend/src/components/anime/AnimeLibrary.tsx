import React, { useState, useEffect } from "react";
import {
    Bookmark,
    FolderHeart,
    FolderOpen,
    Trash2,
    X,
    ChevronDown,
    ChevronUp,
    Download,
} from "lucide-react";
import { AnimeCard, AnimeItem } from "./AnimeCard";

export interface DownloadTask {
    animeId: number;
    title: string;
    poster: string;
    episodes: Array<{
        episodeNumber: number;
        progress: number;
        status: "downloading" | "completed" | "paused" | "waiting";
    }>;
}

interface AnimeLibraryProps {
    bookmarkedItems: AnimeItem[];
    onSelect: (anime: AnimeItem) => void;
    onToggleBookmark: (anime: AnimeItem) => void;
    onExplore: () => void;
    downloadTasks?: DownloadTask[];
}

const EMPTY_DOWNLOAD_TASKS: DownloadTask[] = [];

const LIB_TXT = {
    title: "내 목록",
    desc: "저장한 작품과 오프라인 회차를 관리하세요.",
    openFolder: "다운로드 폴더 열기",
    myList: "내 목록",
    downloadComplete: "다운로드 완료",
    saveFolder: "저장 폴더: ",
    defaultPath: "C:\\Users\\Downloads\\Phrolova\\Anime",
    changeFolder: "저장 폴더 바꾸기",
    clearList: "목록 비우기",
    epCount: (n: number) => `${n}개 회차`,
    downloadingInfo: (total: number, active: number) => `1~${total}화 · ${active}개 받는 중`,
    epTitle: (n: number) => `${n}화`,
    downloading: (p: number) => `${p}% 다운로드 중`,
    waiting: "대기 중",
    pause: "중지",
    delete: "삭제",
    emptyTitle: "보관함이 비어 있습니다",
    emptyDesc: "홈이나 검색 화면에서 애니메이션을 북마크하여 보관함에 담아보세요.",
    explore: "애니메이션 둘러보기",
};

export const AnimeLibrary: React.FC<AnimeLibraryProps> = ({
    bookmarkedItems,
    onSelect,
    onToggleBookmark,
    onExplore,
    downloadTasks = EMPTY_DOWNLOAD_TASKS,
}) => {
    const [libTab, setLibTab] = useState<"bookmarks" | "downloads">("bookmarks");
    const [tasks, setTasks] = useState<DownloadTask[]>(downloadTasks);
    const [expandedAnimes, setExpandedAnimes] = useState<Record<number, boolean>>({});
    const [currentPath, setCurrentPath] = useState<string>(LIB_TXT.defaultPath);

    useEffect(() => {
        setTasks(downloadTasks);
    }, [downloadTasks]);

    useEffect(() => {
        fetch("/api/settings")
            .then((res) => (res.ok ? res.json() : null))
            .then((data) => {
                if (data?.vod_download_dir) {
                    setCurrentPath(data.vod_download_dir);
                } else if (data?.download_dir) {
                    setCurrentPath(data.download_dir);
                }
            })
            .catch(() => {});
    }, []);

    const toggleExpand = (id: number) => {
        setExpandedAnimes((prev) => ({ ...prev, [id]: !prev[id] }));
    };

    return (
        <section className="mb-12 text-white">
            {/* Header */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
                <div>
                    <h1 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight mb-1">
                        {LIB_TXT.title}
                    </h1>
                    <p className="text-xs text-gray-400">
                        {LIB_TXT.desc}
                    </p>
                </div>

                <button
                    type="button"
                    onClick={async () => {
                        try {
                            await fetch("/api/setup/open-folder?path=vod");
                        } catch {
                            // ignore
                        }
                    }}
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-white/10 hover:bg-white/15 text-xs font-semibold text-white border border-white/10 transition-all self-start sm:self-auto"
                >
                    <FolderOpen className="size-4 text-[#C8A2C8]" />
                    <span>{LIB_TXT.openFolder}</span>
                </button>
            </div>

            {/* Sub Tabs */}
            <div className="flex items-center gap-6 border-b border-white/10 pb-3 mb-4 text-xs font-bold">
                <button
                    type="button"
                    onClick={() => setLibTab("bookmarks")}
                    className={`transition-all ${
                        libTab === "bookmarks"
                            ? "text-[#C8A2C8] border-b-2 border-[#C8A2C8] pb-3 -mb-3"
                            : "text-gray-400 hover:text-white"
                    }`}
                >
                    {LIB_TXT.myList} ({bookmarkedItems.length})
                </button>

                <button
                    type="button"
                    onClick={() => setLibTab("downloads")}
                    className={`flex items-center gap-1.5 transition-all ${
                        libTab === "downloads"
                            ? "text-[#C8A2C8] border-b-2 border-[#C8A2C8] pb-3 -mb-3"
                            : "text-gray-400 hover:text-white"
                    }`}
                >
                    <span>{LIB_TXT.downloadComplete}</span>
                    <span className="px-1.5 py-0.2 rounded-full bg-white/10 text-[10px] text-gray-300">
                        {tasks.length}
                    </span>
                </button>
            </div>

            {libTab === "downloads" && (
                <div>
                    {/* Path & Actions Bar */}
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs text-gray-400 mb-4 pb-2 border-b border-white/5">
                        <span className="truncate">
                            {LIB_TXT.saveFolder}<span className="text-gray-300 font-mono text-[11px]">{currentPath}</span>
                        </span>
                        <div className="flex items-center gap-3 shrink-0">
                            <button
                                type="button"
                                onClick={async () => {
                                    try {
                                        await fetch("/api/setup/open-folder?path=vod");
                                    } catch {
                                        // ignore
                                    }
                                }}
                                className="hover:text-white transition-colors"
                            >
                                {LIB_TXT.openFolder}
                            </button>
                            {tasks.length > 0 && (
                                <>
                                    <span>·</span>
                                    <button
                                        type="button"
                                        onClick={() => setTasks([])}
                                        className="hover:text-rose-400 transition-colors"
                                    >
                                        {LIB_TXT.clearList}
                                    </button>
                                </>
                            )}
                        </div>
                    </div>

                    {/* Download Tasks List */}
                    {tasks.length > 0 ? (
                        <div className="space-y-4">
                            {tasks.map((task) => {
                                const isExpanded = expandedAnimes[task.animeId] ?? true;
                                const downloadingCount = task.episodes.filter(
                                    (e) => e.status === "downloading"
                                ).length;

                                return (
                                    <div
                                        key={task.animeId}
                                        className="rounded-2xl bg-[#16161c] border border-white/10 overflow-hidden"
                                    >
                                        {/* Task Header */}
                                        <div
                                            className="p-4 flex items-center justify-between cursor-pointer hover:bg-white/5 transition-all select-none"
                                            onClick={() => toggleExpand(task.animeId)}
                                        >
                                            <div className="flex items-center gap-3.5">
                                                <div className="w-12 h-14 rounded-lg overflow-hidden bg-black/60 shrink-0 border border-white/10">
                                                    <img
                                                        src={task.poster}
                                                        alt={task.title}
                                                        className="w-full h-full object-cover"
                                                    />
                                                </div>
                                                <div>
                                                    <h3 className="text-sm font-bold text-white flex items-center gap-2">
                                                        <span>{task.title}</span>
                                                        <span className="text-xs font-normal text-gray-400">
                                                            {LIB_TXT.epCount(task.episodes.length)}
                                                        </span>
                                                    </h3>
                                                    <p className="text-xs text-[#C8A2C8] mt-1 font-medium">
                                                        {LIB_TXT.downloadingInfo(task.episodes.length, downloadingCount)}
                                                    </p>
                                                </div>
                                            </div>

                                            <button
                                                type="button"
                                                className="p-1.5 rounded-lg text-gray-400 hover:text-white"
                                            >
                                                {isExpanded ? (
                                                    <ChevronUp className="size-4" />
                                                ) : (
                                                    <ChevronDown className="size-4" />
                                                )}
                                            </button>
                                        </div>

                                        {/* Sub Episodes */}
                                        {isExpanded && (
                                            <div className="px-4 pb-4 space-y-2 border-t border-white/5 pt-3">
                                                {task.episodes.map((ep) => (
                                                    <div
                                                        key={ep.episodeNumber}
                                                        className="p-3.5 rounded-xl bg-black/40 border border-white/5 flex flex-col gap-2"
                                                    >
                                                        <div className="flex items-center justify-between text-xs">
                                                            <div>
                                                                <span className="font-bold text-white mr-2">
                                                                    {LIB_TXT.epTitle(ep.episodeNumber)}
                                                                </span>
                                                                <span className="text-[11px] text-gray-400">
                                                                    {ep.status === "downloading"
                                                                        ? LIB_TXT.downloading(ep.progress)
                                                                        : LIB_TXT.waiting}
                                                                </span>
                                                            </div>

                                                            <div className="flex items-center gap-2 text-xs">
                                                                <button
                                                                    type="button"
                                                                    className="px-2.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-gray-300 transition-all flex items-center gap-1"
                                                                >
                                                                    <X className="size-3" />
                                                                    <span>{LIB_TXT.pause}</span>
                                                                </button>
                                                                <button
                                                                    type="button"
                                                                    onClick={() => {
                                                                        setTasks((prev) =>
                                                                            prev
                                                                                .map((t) =>
                                                                                    t.animeId === task.animeId
                                                                                        ? {
                                                                                              ...t,
                                                                                              episodes: t.episodes.filter(
                                                                                                  (e) => e.episodeNumber !== ep.episodeNumber
                                                                                              ),
                                                                                          }
                                                                                        : t
                                                                                )
                                                                                .filter((t) => t.episodes.length > 0)
                                                                        );
                                                                    }}
                                                                    className="px-2.5 py-1 rounded-lg bg-white/5 hover:bg-rose-500/20 text-rose-400 transition-all flex items-center gap-1"
                                                                >
                                                                    <Trash2 className="size-3" />
                                                                    <span>{LIB_TXT.delete}</span>
                                                                </button>
                                                            </div>
                                                        </div>

                                                        {/* Progress bar */}
                                                        <div className="w-full h-1.5 rounded-full bg-white/10 overflow-hidden">
                                                            <div
                                                                className="h-full bg-[#C8A2C8] transition-all duration-300"
                                                                style={{ width: `${ep.progress}%` }}
                                                            />
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    ) : (
                        <div className="py-20 text-center rounded-2xl border border-white/5 bg-black/20 flex flex-col items-center justify-center">
                            <div className="size-16 rounded-full bg-lilac-faint border border-lilac-border flex items-center justify-center text-[#C8A2C8] mb-4">
                                <FolderOpen className="size-8" />
                            </div>
                            <h3 className="text-base font-bold text-white mb-1">
                                {LIB_TXT.emptyTitle}
                            </h3>
                            <p className="text-xs text-gray-400 max-w-sm mb-6">
                                {LIB_TXT.emptyDesc}
                            </p>
                            <button
                                type="button"
                                onClick={onExplore}
                                className="px-5 py-2.5 rounded-xl bg-[#C8A2C8] text-gray-950 font-bold text-xs hover:bg-[#D8B4D8] transition-all shadow-md"
                            >
                                {LIB_TXT.explore}
                            </button>
                        </div>
                    )}
                </div>
            )}

            {libTab === "bookmarks" && (
                <div>
                    {bookmarkedItems.length > 0 ? (
                        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
                            {bookmarkedItems.map((anime) => (
                                <AnimeCard
                                    key={anime.mal_id}
                                    anime={anime}
                                    onSelect={onSelect}
                                    isBookmarked={true}
                                    onToggleBookmark={onToggleBookmark}
                                />
                            ))}
                        </div>
                    ) : (
                        <div className="py-20 text-center rounded-2xl border border-white/5 bg-black/20 flex flex-col items-center justify-center">
                            <div className="size-16 rounded-full bg-lilac-faint border border-lilac-border flex items-center justify-center text-[#C8A2C8] mb-4">
                                <Bookmark className="size-8" />
                            </div>
                            <h3 className="text-base font-bold text-white mb-1">
                                {LIB_TXT.emptyTitle}
                            </h3>
                            <p className="text-xs text-gray-400 max-w-sm mb-6">
                                {LIB_TXT.emptyDesc}
                            </p>
                            <button
                                type="button"
                                onClick={onExplore}
                                className="px-5 py-2.5 rounded-xl bg-[#C8A2C8] text-gray-950 font-bold text-xs hover:bg-[#D8B4D8] transition-all shadow-md"
                            >
                                {LIB_TXT.explore}
                            </button>
                        </div>
                    )}
                </div>
            )}
        </section>
    );
};

