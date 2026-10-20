import React from "react";
import { Sparkles, Info, Bookmark, Star, Play } from "lucide-react";
import { useLanguage } from "../../contexts/LanguageContext";
import { AnimeItem } from "./AnimeCard";

interface AnimeHeroProps {
    anime: AnimeItem | null;
    onSelect: (anime: AnimeItem) => void;
    isBookmarked?: boolean;
    onToggleBookmark?: (anime: AnimeItem) => void;
}

export const AnimeHero: React.FC<AnimeHeroProps> = ({
    anime,
    onSelect,
    isBookmarked = false,
    onToggleBookmark,
}) => {
    const { t } = useLanguage();
    if (!anime) return null;

    const bannerImg =
        anime.images?.webp?.large_image_url ||
        anime.images?.jpg?.large_image_url ||
        anime.images?.webp?.image_url ||
        "";

    const displayTitle = anime.title_korean || anime.title || anime.title_english || "";

    return (
        <section className="lilac-hero mb-8">
            {bannerImg && (
                <div
                    className="lilac-hero-backdrop"
                    style={{ backgroundImage: `url(${bannerImg})` }}
                />
            )}

            <div className="lilac-hero-content">
                <div className="flex items-center gap-2 mb-3">
                    <span className="lilac-badge">
                        <Sparkles className="size-3.5" />
                        <span>{t("anime.featured")}</span>
                    </span>
                    {typeof anime.score === "number" && anime.score > 0 && (
                        <span className="inline-flex items-center gap-1 text-xs font-bold text-amber-300 bg-black/50 px-2.5 py-1 rounded-full border border-amber-400/20">
                            <Star className="size-3 fill-amber-400 text-amber-400" />
                            {anime.score.toFixed(1)}
                        </span>
                    )}
                </div>

                <h1 className="text-2xl sm:text-3xl lg:text-4xl font-extrabold text-white tracking-tight leading-tight mb-2 drop-shadow-md">
                    {displayTitle}
                </h1>

                {anime.title_japanese && (
                    <p className="text-sm text-gray-300 font-medium mb-3">
                        {anime.title_japanese}
                    </p>
                )}

                <div className="flex flex-wrap items-center gap-1.5 mb-4">
                    {anime.type && (
                        <span className="text-xs px-2 py-0.5 rounded bg-white/10 text-white font-medium">
                            {anime.type}
                        </span>
                    )}
                    {anime.year && (
                        <span className="text-xs px-2 py-0.5 rounded bg-white/10 text-gray-300">
                            {anime.year}
                        </span>
                    )}
                    {anime.genres?.slice(0, 4).map((g) => (
                        <span
                            key={g.mal_id}
                            className="text-xs px-2 py-0.5 rounded bg-lilac-faint text-lilac-hover border border-lilac-border"
                        >
                            {g.name}
                        </span>
                    ))}
                </div>

                <p className="text-xs sm:text-sm text-gray-200 line-clamp-3 mb-6 max-w-xl leading-relaxed drop-shadow">
                    {anime.synopsis || "Explore the storyline, characters and episode streams."}
                </p>

                <div className="flex items-center gap-3">
                    <button
                        type="button"
                        className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl font-bold text-sm bg-lilac-primary text-gray-950 hover:bg-lilac-hover transition-all shadow-lg hover:shadow-lilac-primary/30"
                        onClick={() => onSelect(anime)}
                    >
                        <Play className="size-4 fill-current" />
                        <span>{t("anime.watchNow")}</span>
                    </button>

                    <button
                        type="button"
                        className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl font-semibold text-sm bg-black/60 text-white hover:bg-black/80 border border-white/15 transition-all"
                        onClick={() => onSelect(anime)}
                    >
                        <Info className="size-4" />
                        <span>{t("anime.details")}</span>
                    </button>

                    {onToggleBookmark && (
                        <button
                            type="button"
                            className={`p-2.5 rounded-xl border transition-all ${
                                isBookmarked
                                    ? "bg-lilac-primary text-gray-950 border-lilac-primary"
                                    : "bg-black/60 text-white/80 hover:text-white border-white/15"
                            }`}
                            onClick={() => onToggleBookmark(anime)}
                            title={isBookmarked ? "Remove Bookmark" : "Add to Library"}
                            aria-label="Toggle Bookmark"
                        >
                            <Bookmark className={`size-5 ${isBookmarked ? "fill-gray-950" : ""}`} />
                        </button>
                    )}
                </div>
            </div>
        </section>
    );
};
