import React, { useState, useEffect } from "react";
import { X, Play, Download, Bookmark, Star, Calendar, Tv, Sparkles, ExternalLink } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { AnimeItem } from "./AnimeCard";

interface AnimeDetailModalProps {
    animeId: number | null;
    initialData?: AnimeItem | null;
    onClose: () => void;
    onPlayEpisode: (anime: AnimeItem, episode: number) => void;
    isBookmarked?: boolean;
    onToggleBookmark?: (anime: AnimeItem) => void;
}

export const AnimeDetailModal: React.FC<AnimeDetailModalProps> = ({
    animeId,
    initialData,
    onClose,
    onPlayEpisode,
    isBookmarked = false,
    onToggleBookmark,
}) => {
    const navigate = useNavigate();
    const [detail, setDetail] = useState<AnimeItem | null>(initialData || null);
    const [loading, setLoading] = useState<boolean>(!initialData);
    const [activeTab, setActiveTab] = useState<"episodes" | "trailer">("episodes");

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
                <div className="w-10 h-10 border-4 border-lilac-primary border-t-transparent rounded-full animate-spin" />
            </div>
        );
    }

    if (!anime) return null;

    const poster =
        anime.images?.webp?.large_image_url ||
        anime.images?.jpg?.large_image_url ||
        anime.images?.webp?.image_url ||
        "";

    const displayTitle = anime.title_english || anime.title;
    const episodesCount = anime.episodes || 12;

    const handleSendToPhrolova = () => {
        // Navigate to Phrolova VOD tab with anime title prefilled
        navigate(`/vod?q=${encodeURIComponent(displayTitle)}`);
        onClose();
    };

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 backdrop-blur-md p-3 sm:p-6 overflow-y-auto"
            onClick={onClose}
        >
            <div
                className="relative w-full max-w-4xl max-h-[90vh] bg-[#121216] border border-lilac-border rounded-2xl shadow-2xl overflow-hidden flex flex-col my-auto"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Backdrop Header */}
                <div className="relative h-48 sm:h-64 w-full bg-black/60 overflow-hidden shrink-0">
                    {poster && (
                        <div
                            className="absolute inset-0 bg-cover bg-center filter blur-md opacity-40 transform scale-110"
                            style={{ backgroundImage: `url(${poster})` }}
                        />
                    )}
                    <div className="absolute inset-0 bg-gradient-to-t from-[#121216] via-[#121216]/60 to-transparent" />

                    <button
                        type="button"
                        onClick={onClose}
                        className="absolute top-4 right-4 p-2 rounded-full bg-black/60 text-white/80 hover:text-white hover:bg-black/90 transition-all z-10"
                        aria-label="Close"
                    >
                        <X className="size-5" />
                    </button>

                    {/* Header Poster & Meta Overlay */}
                    <div className="absolute bottom-4 left-6 right-6 flex items-end gap-5 z-10">
                        <div className="w-24 sm:w-32 aspect-[2/3] rounded-xl overflow-hidden shadow-2xl border border-white/20 shrink-0 bg-black/80 hidden xs:block">
                            <img src={poster} alt={displayTitle} className="w-full h-full object-cover" />
                        </div>

                        <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                                <span className="lilac-badge">
                                    <Sparkles className="size-3" />
                                    <span>{anime.type || "TV"}</span>
                                </span>
                                {typeof anime.score === "number" && anime.score > 0 && (
                                    <span className="inline-flex items-center gap-1 text-xs font-bold text-amber-300 bg-black/60 px-2 py-0.5 rounded-full border border-amber-400/30">
                                        <Star className="size-3 fill-amber-400 text-amber-400" />
                                        {anime.score.toFixed(1)}
                                    </span>
                                )}
                                {anime.status && (
                                    <span className="text-[11px] text-ink-muted">
                                        {anime.status === "Currently Airing" ? "Airing" : "Complete"}
                                    </span>
                                )}
                            </div>

                            <h2 className="text-lg sm:text-2xl font-extrabold text-white truncate drop-shadow-md">
                                {displayTitle}
                            </h2>
                            {anime.title_japanese && (
                                <p className="text-xs text-gray-300 truncate">
                                    {anime.title_japanese}
                                </p>
                            )}
                        </div>
                    </div>
                </div>

                {/* Content Body */}
                <div className="p-6 overflow-y-auto space-y-6 flex-1">
                    {/* Action Bar */}
                    <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-white/5">
                        <div className="flex items-center gap-3">
                            <button
                                type="button"
                                onClick={() => onPlayEpisode(anime, 1)}
                                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl font-bold text-xs bg-lilac-primary text-gray-950 hover:bg-lilac-hover shadow-md transition-all"
                            >
                                <Play className="size-4 fill-current" />
                                <span>Play Episode 1</span>
                            </button>

                            <button
                                type="button"
                                onClick={handleSendToPhrolova}
                                className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl font-semibold text-xs bg-white/10 hover:bg-white/15 text-white border border-white/10 transition-all"
                                title="Download via Phrolova VOD queue"
                            >
                                <Download className="size-4 text-lilac-primary" />
                                <span>Download in Phrolova</span>
                            </button>
                        </div>

                        {onToggleBookmark && (
                            <button
                                type="button"
                                onClick={() => onToggleBookmark(anime)}
                                className={`inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold border transition-all ${
                                    isBookmarked
                                        ? "bg-lilac-primary text-gray-950 border-lilac-primary"
                                        : "bg-black/40 text-ink-muted hover:text-ink border-white/10"
                                }`}
                            >
                                <Bookmark className={`size-4 ${isBookmarked ? "fill-gray-950" : ""}`} />
                                <span>{isBookmarked ? "Bookmarked" : "Add to Library"}</span>
                            </button>
                        )}
                    </div>

                    {/* Synopsis & Tags */}
                    <div>
                        <h4 className="text-xs font-bold text-ink-muted uppercase tracking-wider mb-2">
                            Synopsis
                        </h4>
                        <p className="text-xs sm:text-sm text-ink-muted leading-relaxed whitespace-pre-line">
                            {anime.synopsis || "No synopsis available."}
                        </p>

                        <div className="flex flex-wrap gap-1.5 mt-3">
                            {anime.genres?.map((g) => (
                                <span
                                    key={g.mal_id}
                                    className="text-[11px] px-2.5 py-1 rounded-lg bg-lilac-faint text-lilac-hover border border-lilac-border font-medium"
                                >
                                    {g.name}
                                </span>
                            ))}
                        </div>
                    </div>

                    {/* Tab Selection: Episodes vs Trailer */}
                    <div>
                        <div className="flex items-center gap-4 border-b border-white/10 mb-4 text-xs font-bold">
                            <button
                                type="button"
                                onClick={() => setActiveTab("episodes")}
                                className={`pb-2 border-b-2 transition-all ${
                                    activeTab === "episodes"
                                        ? "border-lilac-primary text-lilac-primary"
                                        : "border-transparent text-ink-faint hover:text-ink"
                                }`}
                            >
                                Episodes ({episodesCount})
                            </button>

                            {anime.trailer?.embed_url && (
                                <button
                                    type="button"
                                    onClick={() => setActiveTab("trailer")}
                                    className={`pb-2 border-b-2 transition-all ${
                                        activeTab === "trailer"
                                            ? "border-lilac-primary text-lilac-primary"
                                            : "border-transparent text-ink-faint hover:text-ink"
                                    }`}
                                >
                                    Trailer (PV)
                                </button>
                            )}
                        </div>

                        {activeTab === "episodes" && (
                            <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-6 gap-2">
                                {Array.from({ length: Math.min(100, episodesCount) }).map((_, i) => {
                                    const epNum = i + 1;
                                    return (
                                        <button
                                            key={epNum}
                                            type="button"
                                            onClick={() => onPlayEpisode(anime, epNum)}
                                            className="p-3 rounded-xl bg-black/40 border border-white/5 hover:border-lilac-border hover:bg-lilac-faint text-left transition-all group flex items-center justify-between"
                                        >
                                            <span className="text-xs font-bold text-ink group-hover:text-lilac-hover">
                                                Episode {epNum}
                                            </span>
                                            <Play className="size-3 text-ink-faint group-hover:text-lilac-primary" />
                                        </button>
                                    );
                                })}
                            </div>
                        )}

                        {activeTab === "trailer" && anime.trailer?.embed_url && (
                            <div className="relative aspect-video w-full rounded-xl overflow-hidden bg-black/80 border border-white/10">
                                <iframe
                                    src={anime.trailer.embed_url}
                                    title="Trailer"
                                    className="w-full h-full"
                                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                                    allowFullScreen
                                />
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};
