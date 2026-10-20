import React from "react";
import { Star, Bookmark, Play } from "lucide-react";
import { useLanguage } from "../../contexts/LanguageContext";

export interface AnimeItem {
    mal_id: number;
    title: string;
    title_korean?: string | null;
    title_english?: string | null;
    title_japanese?: string | null;
    images?: {
        jpg?: {
            image_url?: string;
            large_image_url?: string;
        };
        webp?: {
            image_url?: string;
            large_image_url?: string;
        };
    };
    score?: number | null;
    episodes?: number | null;
    type?: string | null;
    status?: string | null;
    synopsis?: string | null;
    trailer?: {
        youtube_id?: string | null;
        embed_url?: string | null;
    };
    genres?: Array<{ mal_id: number; name: string }>;
    year?: number | null;
    season?: string | null;
}

interface AnimeCardProps {
    anime: AnimeItem;
    onSelect: (anime: AnimeItem) => void;
    isBookmarked?: boolean;
    onToggleBookmark?: (anime: AnimeItem) => void;
    compact?: boolean;
}

export const AnimeCard: React.FC<AnimeCardProps> = ({
    anime,
    onSelect,
    isBookmarked = false,
    onToggleBookmark,
    compact = false,
}) => {
    const { t } = useLanguage();
    const poster =
        anime.images?.webp?.large_image_url ||
        anime.images?.jpg?.large_image_url ||
        anime.images?.webp?.image_url ||
        anime.images?.jpg?.image_url ||
        "";

    const displayTitle = anime.title_korean || anime.title || anime.title_english || "";

    return (
        <div
            className={`lilac-card group ${compact ? "w-[160px] shrink-0" : "w-full"}`}
            onClick={() => onSelect(anime)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect(anime);
                }
            }}
        >
            <div className="lilac-poster-wrap">
                {poster ? (
                    <img
                        src={poster}
                        alt={anime.title}
                        className="lilac-poster-img"
                        loading="lazy"
                    />
                ) : (
                    <div className="w-full h-full flex items-center justify-center text-xs text-ink-faint">
                        No Image
                    </div>
                )}

                {/* Score Pill */}
                {typeof anime.score === "number" && anime.score > 0 && (
                    <div className="lilac-score-pill">
                        <Star className="size-3 fill-amber-400 text-amber-400" />
                        <span>{anime.score.toFixed(1)}</span>
                    </div>
                )}

                {/* Quick Bookmark Button */}
                {onToggleBookmark && (
                    <button
                        type="button"
                        className={`absolute top-2 left-2 size-8 rounded-lg flex items-center justify-center transition-all ${
                            isBookmarked
                                ? "bg-lilac-primary text-gray-900 shadow-md"
                                : "bg-black/60 text-white/80 hover:text-white hover:bg-black/80"
                        }`}
                        onClick={(e) => {
                            e.stopPropagation();
                            onToggleBookmark(anime);
                        }}
                        title={isBookmarked ? "Remove Bookmark" : "Add to Library"}
                        aria-label="Toggle Bookmark"
                    >
                        <Bookmark className={`size-4 ${isBookmarked ? "fill-gray-900" : ""}`} />
                    </button>
                )}

                {/* Hover Play Glow Overlay */}
                <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center pointer-events-none">
                    <div className="size-11 rounded-full bg-lilac-primary text-gray-950 flex items-center justify-center shadow-lg transform scale-75 group-hover:scale-100 transition-transform">
                        <Play className="size-5 fill-current ml-0.5" />
                    </div>
                </div>
            </div>

            <div className="p-3 flex flex-col flex-1 justify-between">
                <div>
                    <h3
                        className="text-xs font-semibold text-ink line-clamp-2 leading-snug group-hover:text-lilac-hover transition-colors"
                        title={displayTitle}
                    >
                        {displayTitle}
                    </h3>
                    {anime.title_japanese && anime.title_japanese !== displayTitle && (
                        <p className="text-[11px] text-ink-faint line-clamp-1 mt-0.5">
                            {anime.title_japanese}
                        </p>
                    )}
                </div>

                <div className="mt-2 pt-2 border-t border-white/5 flex items-center justify-between text-[11px] text-ink-faint">
                    <span className="font-medium text-lilac-primary">
                        {anime.type || "Anime"}
                    </span>
                    <span>
                        {anime.episodes ? t("anime.episodeFormat", { num: anime.episodes }) : anime.status === "Currently Airing" ? t("anime.airing") : t("anime.completed")}
                    </span>
                </div>
            </div>
        </div>
    );
};
