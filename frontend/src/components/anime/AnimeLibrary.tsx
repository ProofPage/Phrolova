import React from "react";
import { Bookmark, FolderHeart } from "lucide-react";
import { AnimeCard, AnimeItem } from "./AnimeCard";

interface AnimeLibraryProps {
    bookmarkedItems: AnimeItem[];
    onSelect: (anime: AnimeItem) => void;
    onToggleBookmark: (anime: AnimeItem) => void;
    onExplore: () => void;
}

export const AnimeLibrary: React.FC<AnimeLibraryProps> = ({
    bookmarkedItems,
    onSelect,
    onToggleBookmark,
    onExplore,
}) => {
    return (
        <section className="mb-12">
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h2 className="text-lg sm:text-xl font-bold text-ink tracking-tight flex items-center gap-2">
                        <FolderHeart className="size-5 text-lilac-primary" />
                        <span>Saved Library</span>
                    </h2>
                    <p className="text-xs text-ink-faint mt-0.5">
                        Your bookmarked anime ({bookmarkedItems.length})
                    </p>
                </div>
            </div>

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
                    <div className="size-16 rounded-full bg-lilac-faint border border-lilac-border flex items-center justify-center text-lilac-primary mb-4">
                        <Bookmark className="size-8" />
                    </div>
                    <h3 className="text-base font-bold text-ink mb-1">Your library is empty</h3>
                    <p className="text-xs text-ink-faint max-w-sm mb-6">
                        Bookmark your favorite anime from the home or catalog view to access them quickly here.
                    </p>
                    <button
                        type="button"
                        onClick={onExplore}
                        className="px-5 py-2.5 rounded-xl bg-lilac-primary text-gray-950 font-bold text-xs hover:bg-lilac-hover transition-all shadow-md"
                    >
                        Browse Anime
                    </button>
                </div>
            )}
        </section>
    );
};
