import React, { useRef } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useLanguage } from "../../contexts/LanguageContext";
import { AnimeCard, AnimeItem } from "./AnimeCard";

interface AnimeRailProps {
    title: string;
    subtitle?: string;
    items: AnimeItem[];
    loading?: boolean;
    onSelect: (anime: AnimeItem) => void;
    bookmarks?: number[];
    onToggleBookmark?: (anime: AnimeItem) => void;
    onSeeAll?: () => void;
}

export const AnimeRail: React.FC<AnimeRailProps> = ({
    title,
    subtitle,
    items,
    loading = false,
    onSelect,
    bookmarks = [],
    onToggleBookmark,
    onSeeAll,
}) => {
    const { t } = useLanguage();
    const railRef = useRef<HTMLDivElement>(null);

    const scroll = (direction: "left" | "right") => {
        if (!railRef.current) return;
        const offset = direction === "left" ? -480 : 480;
        railRef.current.scrollBy({ left: offset, behavior: "smooth" });
    };

    return (
        <section className="mb-10">
            <div className="flex items-center justify-between mb-4">
                <div>
                    <h2 className="text-lg sm:text-xl font-bold text-ink tracking-tight flex items-center gap-2">
                        <span>{title}</span>
                    </h2>
                    {subtitle && <p className="text-xs text-ink-faint mt-0.5">{subtitle}</p>}
                </div>

                <div className="flex items-center gap-2">
                    {onSeeAll && (
                        <button
                            type="button"
                            onClick={onSeeAll}
                            className="text-xs font-semibold text-lilac-primary hover:text-lilac-hover mr-2 transition-colors"
                        >
                            {t("anime.viewAll")}
                        </button>
                    )}
                    <button
                        type="button"
                        onClick={() => scroll("left")}
                        className="p-1.5 rounded-lg border border-white/10 hover:border-lilac-border bg-black/40 text-ink-muted hover:text-ink transition-all"
                        aria-label="Previous"
                    >
                        <ChevronLeft className="size-4" />
                    </button>
                    <button
                        type="button"
                        onClick={() => scroll("right")}
                        className="p-1.5 rounded-lg border border-white/10 hover:border-lilac-border bg-black/40 text-ink-muted hover:text-ink transition-all"
                        aria-label="Next"
                    >
                        <ChevronRight className="size-4" />
                    </button>
                </div>
            </div>

            <div ref={railRef} className="lilac-rail">
                {loading
                    ? Array.from({ length: 6 }).map((_, idx) => (
                          <div
                              key={idx}
                              className="w-[160px] shrink-0 aspect-[2/3] rounded-xl bg-white/5 animate-pulse"
                          />
                      ))
                    : items.map((anime) => (
                          <AnimeCard
                              key={anime.mal_id}
                              anime={anime}
                              compact
                              onSelect={onSelect}
                              isBookmarked={bookmarks.includes(anime.mal_id)}
                              onToggleBookmark={onToggleBookmark}
                          />
                      ))}
            </div>
        </section>
    );
};
