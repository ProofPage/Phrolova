import React, { useState, useEffect } from "react";
import { Search, Filter, RotateCcw, ChevronLeft, ChevronRight } from "lucide-react";
import { AnimeCard, AnimeItem } from "./AnimeCard";

const GENRES = [
    { id: "1", name: "Action" },
    { id: "2", name: "Adventure" },
    { id: "4", name: "Comedy" },
    { id: "8", name: "Drama" },
    { id: "10", name: "Fantasy" },
    { id: "14", name: "Horror" },
    { id: "7", name: "Mystery" },
    { id: "22", name: "Romance" },
    { id: "24", name: "Sci-Fi" },
    { id: "36", name: "Slice of Life" },
    { id: "30", name: "Sports" },
    { id: "37", name: "Supernatural" },
];

const TYPES = [
    { id: "", name: "All Types" },
    { id: "tv", name: "TV Series" },
    { id: "movie", name: "Movie" },
    { id: "ova", name: "OVA" },
    { id: "ona", name: "ONA" },
    { id: "special", name: "Special" },
];

const STATUSES = [
    { id: "", name: "All Statuses" },
    { id: "airing", name: "Airing" },
    { id: "complete", name: "Completed" },
    { id: "upcoming", name: "Upcoming" },
];

interface AnimeSearchCatalogProps {
    onSelect: (anime: AnimeItem) => void;
    bookmarks?: number[];
    onToggleBookmark?: (anime: AnimeItem) => void;
    initialQuery?: string;
}

export const AnimeSearchCatalog: React.FC<AnimeSearchCatalogProps> = ({
    onSelect,
    bookmarks = [],
    onToggleBookmark,
    initialQuery = "",
}) => {
    const [query, setQuery] = useState(initialQuery);
    const [selectedGenre, setSelectedGenre] = useState<string>("");
    const [selectedType, setSelectedType] = useState<string>("");
    const [selectedStatus, setSelectedStatus] = useState<string>("");
    const [orderBy, setOrderBy] = useState<string>("popularity");
    const [page, setPage] = useState<number>(1);
    const [results, setResults] = useState<AnimeItem[]>([]);
    const [hasNextPage, setHasNextPage] = useState<boolean>(false);
    const [loading, setLoading] = useState<boolean>(false);

    const performSearch = async () => {
        setLoading(true);
        try {
            const params = new URLSearchParams({
                q: query.trim(),
                order_by: orderBy,
                page: String(page),
                limit: "24",
            });
            if (selectedGenre) params.append("genre", selectedGenre);
            if (selectedType) params.append("type", selectedType);
            if (selectedStatus) params.append("status", selectedStatus);

            const res = await fetch(`/api/lilac/search?${params.toString()}`);
            if (res.ok) {
                const data = await res.json();
                setResults(data.results || []);
                setHasNextPage(Boolean(data.pagination?.has_next_page));
            }
        } catch {
            // ignore
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        performSearch();
    }, [page, selectedGenre, selectedType, selectedStatus, orderBy]);

    const handleSearchSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        setPage(1);
        performSearch();
    };

    const handleReset = () => {
        setQuery("");
        setSelectedGenre("");
        setSelectedType("");
        setSelectedStatus("");
        setOrderBy("popularity");
        setPage(1);
    };

    return (
        <section className="mb-12">
            {/* Search Input Bar */}
            <form onSubmit={handleSearchSubmit} className="mb-6">
                <div className="relative flex items-center">
                    <Search className="absolute left-4 size-5 text-ink-muted pointer-events-none" />
                    <input
                        type="text"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="Search anime title or keywords..."
                        className="w-full pl-12 pr-28 py-3.5 rounded-2xl bg-black/40 border border-white/10 focus:border-lilac-border focus:ring-2 focus:ring-lilac-primary/20 text-ink placeholder:text-ink-faint text-sm transition-all"
                    />
                    <button
                        type="submit"
                        className="absolute right-2 px-5 py-2 rounded-xl bg-lilac-primary text-gray-950 font-bold text-xs hover:bg-lilac-hover transition-all"
                    >
                        Search
                    </button>
                </div>
            </form>

            {/* Filter Bar */}
            <div className="p-4 rounded-2xl bg-black/30 border border-white/5 mb-6 flex flex-wrap items-center justify-between gap-3 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                    <span className="flex items-center gap-1.5 font-semibold text-ink-muted mr-1">
                        <Filter className="size-3.5" />
                        <span>Filter</span>
                    </span>

                    {/* Genre */}
                    <select
                        value={selectedGenre}
                        onChange={(e) => {
                            setSelectedGenre(e.target.value);
                            setPage(1);
                        }}
                        className="px-3 py-1.5 rounded-lg bg-black/50 border border-white/10 text-ink focus:border-lilac-border"
                    >
                        <option value="">All Genres</option>
                        {GENRES.map((g) => (
                            <option key={g.id} value={g.id}>
                                {g.name}
                            </option>
                        ))}
                    </select>

                    {/* Type */}
                    <select
                        value={selectedType}
                        onChange={(e) => {
                            setSelectedType(e.target.value);
                            setPage(1);
                        }}
                        className="px-3 py-1.5 rounded-lg bg-black/50 border border-white/10 text-ink focus:border-lilac-border"
                    >
                        {TYPES.map((t) => (
                            <option key={t.id} value={t.id}>
                                {t.name}
                            </option>
                        ))}
                    </select>

                    {/* Status */}
                    <select
                        value={selectedStatus}
                        onChange={(e) => {
                            setSelectedStatus(e.target.value);
                            setPage(1);
                        }}
                        className="px-3 py-1.5 rounded-lg bg-black/50 border border-white/10 text-ink focus:border-lilac-border"
                    >
                        {STATUSES.map((s) => (
                            <option key={s.id} value={s.id}>
                                {s.name}
                            </option>
                        ))}
                    </select>

                    {/* Order By */}
                    <select
                        value={orderBy}
                        onChange={(e) => {
                            setOrderBy(e.target.value);
                            setPage(1);
                        }}
                        className="px-3 py-1.5 rounded-lg bg-black/50 border border-white/10 text-ink focus:border-lilac-border"
                    >
                        <option value="popularity">Popularity</option>
                        <option value="score">Score</option>
                        <option value="title">Title</option>
                    </select>
                </div>

                <button
                    type="button"
                    onClick={handleReset}
                    className="flex items-center gap-1 text-ink-muted hover:text-ink transition-colors px-2 py-1 rounded"
                >
                    <RotateCcw className="size-3.5" />
                    <span>Reset</span>
                </button>
            </div>

            {/* Results Grid */}
            {loading ? (
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
                    {Array.from({ length: 12 }).map((_, i) => (
                        <div key={i} className="aspect-[2/3] rounded-xl bg-white/5 animate-pulse" />
                    ))}
                </div>
            ) : results.length > 0 ? (
                <>
                    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4 mb-8">
                        {results.map((anime) => (
                            <AnimeCard
                                key={anime.mal_id}
                                anime={anime}
                                onSelect={onSelect}
                                isBookmarked={bookmarks.includes(anime.mal_id)}
                                onToggleBookmark={onToggleBookmark}
                            />
                        ))}
                    </div>

                    {/* Pagination */}
                    <div className="flex items-center justify-center gap-3">
                        <button
                            type="button"
                            disabled={page <= 1}
                            onClick={() => setPage((p) => Math.max(1, p - 1))}
                            className="flex items-center gap-1 px-4 py-2 rounded-xl border border-white/10 bg-black/40 text-xs font-semibold disabled:opacity-40 disabled:cursor-not-allowed hover:border-lilac-border transition-all"
                        >
                            <ChevronLeft className="size-4" />
                            <span>Previous</span>
                        </button>
                        <span className="text-xs font-medium text-ink-muted px-2">
                            Page {page}
                        </span>
                        <button
                            type="button"
                            disabled={!hasNextPage}
                            onClick={() => setPage((p) => p + 1)}
                            className="flex items-center gap-1 px-4 py-2 rounded-xl border border-white/10 bg-black/40 text-xs font-semibold disabled:opacity-40 disabled:cursor-not-allowed hover:border-lilac-border transition-all"
                        >
                            <span>Next</span>
                            <ChevronRight className="size-4" />
                        </button>
                    </div>
                </>
            ) : (
                <div className="p-16 text-center rounded-2xl border border-white/5 bg-black/20 text-ink-faint">
                    <p className="text-sm">No anime found matching your filter criteria.</p>
                </div>
            )}
        </section>
    );
};
