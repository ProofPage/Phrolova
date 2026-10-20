import React, { useState, useEffect } from "react";
import {
    X,
    Play,
    Download,
    Heart,
    ExternalLink,
    ArrowUpDown,
    DownloadCloud,
} from "lucide-react";
import { useLanguage } from "../../contexts/LanguageContext";
import { AnimeItem } from "./AnimeCard";

interface AnimeDetailModalProps {
    animeId: number | null;
    initialData?: AnimeItem | null;
    onClose: () => void;
    onPlayEpisode: (anime: AnimeItem, episode: number) => void;
    isBookmarked?: boolean;
    onToggleBookmark?: (anime: AnimeItem) => void;
    onDownloadEpisode?: (anime: AnimeItem, episode: number) => void;
    onDownloadAll?: (anime: AnimeItem, totalEps: number) => void;
}

const TXT = {
    close: "닫기",
    noSynopsis: "작품의 줄거리 정보가 등록되어 있지 않습니다.",
    playEp1: "1화 재생",
    myList: "내 목록",
    info: "작품 정보",
    episodes: "회차",
    relations: "관련 작품",
    epCount: (n: number) => `회차 ${n}화`,
    sortAsc: "오래된화순",
    sortDesc: "최신화순",
    downloadAll: "전체 저장",
    epTitle: (n: number) => `${n}화`,
    download: "다운로드",
    relationsPending: "연관 시리즈 및 극장판 정보가 준비 중입니다.",
};

export const AnimeDetailModal: React.FC<AnimeDetailModalProps> = ({
    animeId,
    initialData,
    onClose,
    onPlayEpisode,
    isBookmarked = false,
    onToggleBookmark,
    onDownloadEpisode,
    onDownloadAll,
}) => {
    const { t } = useLanguage();
    const [detail, setDetail] = useState<AnimeItem | null>(initialData || null);
    const [loading, setLoading] = useState<boolean>(!initialData);
    const [activeTab, setActiveTab] = useState<"episodes" | "relations">("episodes");
    const [sortAsc, setSortAsc] = useState<boolean>(true);

    useEffect(() => {
        if (!animeId) return;
        setLoading(true);
        fetch(`/api/lilac/anime/${animeId}`)
            .then((res) => res.json())
            .then((data) => {
                if (data.anime) setDetail(data.anime);
            })
            .catch(() => {})
            .finally(() => setLoading(false));
    }, [animeId]);

    useEffect(() => {
        const onKeyDown = (e: KeyboardEvent) => {
            if (e.key === "Escape") onClose();
        };
        window.addEventListener("keydown", onKeyDown);
        return () => window.removeEventListener("keydown", onKeyDown);
    }, [onClose]);

    if (!animeId) return null;

    const anime = detail || initialData;
    if (!anime && loading) {
        return (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
                <div className="w-10 h-10 border-4 border-[#C8A2C8] border-t-transparent rounded-full animate-spin" />
            </div>
        );
    }

    if (!anime) return null;

    const poster =
        anime.images?.webp?.large_image_url ||
        anime.images?.jpg?.large_image_url ||
        anime.images?.webp?.image_url ||
        "";

    const backdrop = (anime as any).banner_image || poster;
    const displayTitle = anime.title;
    const subTitle = anime.title_japanese || anime.title_english || "";
    const totalEpisodes = anime.episodes || 12;

    const episodesList = Array.from({ length: totalEpisodes }, (_, i) => i + 1);
    const sortedEpisodes = sortAsc ? episodesList : [...episodesList].reverse();

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-3 sm:p-6 overflow-y-auto"
            onClick={onClose}
        >
            <div
                className="relative w-full max-w-4xl max-h-[92vh] bg-[#141418] border border-white/10 rounded-2xl shadow-2xl overflow-hidden flex flex-col my-auto text-white select-none"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Close Button */}
                <button
                    type="button"
                    onClick={onClose}
                    className="absolute top-4 right-4 size-9 rounded-full bg-black/60 hover:bg-black/80 text-white/80 hover:text-white flex items-center justify-center transition-all z-20"
                    aria-label={TXT.close}
                >
                    <X className="size-5" />
                </button>

                {/* Top Backdrop Area */}
                <div className="relative w-full min-h-[320px] bg-black/70 overflow-hidden flex items-end p-6 sm:p-8 shrink-0">
                    {backdrop && (
                        <div
                            className="absolute inset-0 bg-cover bg-center filter brightness-[0.45] blur-[2px] transform scale-105"
                            style={{ backgroundImage: `url(${backdrop})` }}
                        />
                    )}
                    <div className="absolute inset-0 bg-gradient-to-t from-[#141418] via-[#141418]/60 to-transparent" />

                    <div className="relative z-10 flex flex-col sm:flex-row items-center sm:items-end gap-6 w-full">
                        {/* Poster */}
                        <div className="w-32 sm:w-40 aspect-[2/3] rounded-xl overflow-hidden shadow-2xl border border-white/15 shrink-0 bg-black/90">
                            <img src={poster} alt={displayTitle} className="w-full h-full object-cover" />
                        </div>

                        {/* Title and Metadata */}
                        <div className="flex-1 min-w-0 text-center sm:text-left">
                            <h1 className="text-xl sm:text-3xl font-extrabold text-white tracking-tight leading-tight mb-1.5 drop-shadow">
                                {displayTitle}
                            </h1>

                            {subTitle && (
                                <p className="text-xs sm:text-sm text-gray-300 font-medium mb-2.5">
                                    {subTitle}
                                </p>
                            )}

                            {/* Meta Badges */}
                            <p className="text-[11px] text-gray-300 mb-3 flex flex-wrap items-center justify-center sm:justify-start gap-2">
                                <span>{anime.type || "TV"}</span>
                                <span>·</span>
                                <span>{anime.year || "2026"}</span>
                                <span>·</span>
                                <span>{anime.status || "Releasing"}</span>
                            </p>

                            {/* Genre Chips */}
                            <div className="flex flex-wrap items-center justify-center sm:justify-start gap-1.5 mb-5">
                                {anime.genres?.map((g) => (
                                    <span
                                        key={g.mal_id}
                                        className="text-[11px] px-2.5 py-0.5 rounded-full bg-white/10 text-gray-200 border border-white/5 font-medium"
                                    >
                                        {g.name}
                                    </span>
                                ))}
                            </div>

                            {/* Synopsis */}
                            <p className="text-xs text-gray-300 line-clamp-3 leading-relaxed mb-6 max-w-2xl drop-shadow">
                                {anime.synopsis || TXT.noSynopsis}
                            </p>

                            {/* Primary Action Buttons */}
                            <div className="flex flex-wrap items-center justify-center sm:justify-start gap-3">
                                <button
                                    type="button"
                                    onClick={() => onPlayEpisode(anime, 1)}
                                    className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl font-extrabold text-xs bg-white text-gray-950 hover:bg-gray-100 shadow-md transition-all"
                                >
                                    <Play className="size-4 fill-current ml-0.5" />
                                    <span>{TXT.playEp1}</span>
                                </button>

                                {onToggleBookmark && (
                                    <button
                                        type="button"
                                        onClick={() => onToggleBookmark(anime)}
                                        className={`inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-semibold border transition-all ${
                                            isBookmarked
                                                ? "bg-[#C8A2C8] text-gray-950 border-[#C8A2C8]"
                                                : "bg-black/50 text-white/90 hover:text-white hover:bg-black/70 border-white/15"
                                        }`}
                                    >
                                        <Heart className={`size-4 ${isBookmarked ? "fill-gray-950" : ""}`} />
                                        <span>{TXT.myList}</span>
                                    </button>
                                )}

                                <a
                                    href={`https://anilist.co/anime/${(anime as any).anilist_id || anime.mal_id}`}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-semibold bg-black/50 text-white/90 hover:text-white hover:bg-black/70 border border-white/15 transition-all"
                                >
                                    <ExternalLink className="size-4" />
                                    <span>{TXT.info}</span>
                                </a>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Episode List Area */}
                <div className="p-6 bg-[#141418] border-t border-white/5 flex-1 overflow-y-auto">
                    {/* Sub Tab Strip */}
                    <div className="flex items-center justify-between border-b border-white/10 pb-3 mb-4">
                        <div className="flex items-center gap-4 text-xs font-bold">
                            <button
                                type="button"
                                onClick={() => setActiveTab("episodes")}
                                className={`pb-2 transition-all border-b-2 ${
                                    activeTab === "episodes"
                                        ? "border-[#C8A2C8] text-[#C8A2C8]"
                                        : "border-transparent text-gray-400 hover:text-white"
                                }`}
                            >
                                {TXT.episodes}
                            </button>
                            <button
                                type="button"
                                onClick={() => setActiveTab("relations")}
                                className={`pb-2 transition-all border-b-2 ${
                                    activeTab === "relations"
                                        ? "border-[#C8A2C8] text-[#C8A2C8]"
                                        : "border-transparent text-gray-400 hover:text-white"
                                }`}
                            >
                                {TXT.relations}
                            </button>
                        </div>

                        {activeTab === "episodes" && (
                            <div className="flex items-center gap-2">
                                <span className="text-xs text-gray-400 font-medium mr-2">
                                    {TXT.epCount(totalEpisodes)}
                                </span>
                                <button
                                    type="button"
                                    onClick={() => setSortAsc(!sortAsc)}
                                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-white/10 hover:border-white/20 bg-black/40 text-xs text-gray-300 transition-all"
                                >
                                    <ArrowUpDown className="size-3.5" />
                                    <span>{sortAsc ? TXT.sortAsc : TXT.sortDesc}</span>
                                </button>
                                {onDownloadAll && (
                                    <button
                                        type="button"
                                        onClick={() => onDownloadAll(anime, totalEpisodes)}
                                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-white/10 hover:border-[#C8A2C8] bg-black/40 text-xs text-[#C8A2C8] font-semibold transition-all"
                                    >
                                        <DownloadCloud className="size-3.5" />
                                        <span>{TXT.downloadAll}</span>
                                    </button>
                                )}
                            </div>
                        )}
                    </div>

                    {/* Episodes Rows */}
                    {activeTab === "episodes" && (
                        <div className="space-y-2">
                            {sortedEpisodes.map((epNum) => (
                                <div
                                    key={epNum}
                                    className="flex items-center justify-between p-3.5 rounded-xl bg-black/30 hover:bg-black/60 border border-white/5 hover:border-white/15 transition-all group cursor-pointer"
                                    onClick={() => onPlayEpisode(anime, epNum)}
                                >
                                    <div className="flex items-center gap-4">
                                        <div className="size-8 rounded-lg bg-white/5 border border-white/10 flex items-center justify-center text-xs font-bold text-gray-400 group-hover:text-white group-hover:border-[#C8A2C8] transition-all">
                                            {epNum}
                                        </div>
                                        <div>
                                            <h4 className="text-xs font-bold text-white group-hover:text-[#C8A2C8] transition-colors">
                                                {TXT.epTitle(epNum)}
                                            </h4>
                                            <p className="text-[11px] text-gray-400 mt-0.5">
                                                {anime.year || "2026"}
                                            </p>
                                        </div>
                                    </div>

                                    <div className="flex items-center gap-2">
                                        {onDownloadEpisode && (
                                            <button
                                                type="button"
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    onDownloadEpisode(anime, epNum);
                                                }}
                                                className="p-2 rounded-lg hover:bg-white/10 text-gray-400 hover:text-[#C8A2C8] transition-all"
                                                title={`${epNum}화 다운로드`}
                                                aria-label={TXT.download}
                                            >
                                                <Download className="size-4" />
                                            </button>
                                        )}
                                        <div className="size-8 rounded-lg bg-white/5 group-hover:bg-[#C8A2C8] text-gray-400 group-hover:text-gray-950 flex items-center justify-center transition-all">
                                            <Play className="size-3.5 fill-current ml-0.5" />
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}

                    {activeTab === "relations" && (
                        <div className="p-8 text-center text-xs text-gray-400">
                            {TXT.relationsPending}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};
