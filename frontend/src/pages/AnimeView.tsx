import React, { useState, useEffect } from "react";
import {
    Sparkles,
    Calendar,
    Search,
    Clock,
    FolderHeart,
    RefreshCw,
} from "lucide-react";
import { AnimeHero } from "../components/anime/AnimeHero";
import { AnimeRail } from "../components/anime/AnimeRail";
import { WeeklySchedule } from "../components/anime/WeeklySchedule";
import { AnimeSearchCatalog } from "../components/anime/AnimeSearchCatalog";
import { AnimeHistoryRail, WatchHistoryItem } from "../components/anime/AnimeHistoryRail";
import { AnimeLibrary } from "../components/anime/AnimeLibrary";
import { AnimeDetailModal } from "../components/anime/AnimeDetailModal";
import { AnimePlayerModal } from "../components/anime/AnimePlayerModal";
import { AnimeItem } from "../components/anime/AnimeCard";
import "../components/anime/lilac.css";

const STORAGE_BOOKMARKS_KEY = "phrolova_lilac_bookmarks";
const STORAGE_HISTORY_KEY = "phrolova_lilac_history";

export default function AnimeView() {
    const [activeTab, setActiveTab] = useState<"home" | "schedule" | "catalog" | "library">("home");

    // Home data
    const [seasonList, setSeasonList] = useState<AnimeItem[]>([]);
    const [topList, setTopList] = useState<AnimeItem[]>([]);
    const [loadingHome, setLoadingHome] = useState<boolean>(true);

    // Bookmarks state
    const [bookmarks, setBookmarks] = useState<AnimeItem[]>(() => {
        try {
            const raw = localStorage.getItem(STORAGE_BOOKMARKS_KEY);
            return raw ? JSON.parse(raw) : [];
        } catch {
            return [];
        }
    });

    // History state
    const [history, setHistory] = useState<WatchHistoryItem[]>(() => {
        try {
            const raw = localStorage.getItem(STORAGE_HISTORY_KEY);
            return raw ? JSON.parse(raw) : [];
        } catch {
            return [];
        }
    });

    // Selected modal states
    const [selectedAnime, setSelectedAnime] = useState<AnimeItem | null>(null);
    const [playingEpisode, setPlayingEpisode] = useState<{
        anime: AnimeItem;
        episodeNumber: number;
    } | null>(null);

    const loadHomeData = async () => {
        setLoadingHome(true);
        try {
            const res = await fetch("/api/lilac/home");
            if (res.ok) {
                const data = await res.json();
                setSeasonList(data.season || []);
                setTopList(data.top || []);
            }
        } catch {
            // ignore
        } finally {
            setLoadingHome(false);
        }
    };

    useEffect(() => {
        loadHomeData();
    }, []);

    // Save bookmarks to localStorage
    const handleToggleBookmark = (anime: AnimeItem) => {
        setBookmarks((prev) => {
            const exists = prev.some((b) => b.mal_id === anime.mal_id);
            const next = exists
                ? prev.filter((b) => b.mal_id !== anime.mal_id)
                : [anime, ...prev];
            try {
                localStorage.setItem(STORAGE_BOOKMARKS_KEY, JSON.stringify(next));
            } catch {}
            return next;
        });
    };

    // Save watch history
    const handleSaveHistory = (item: WatchHistoryItem) => {
        setHistory((prev) => {
            const filtered = prev.filter((h) => h.malId !== item.malId);
            const next = [item, ...filtered].slice(0, 30);
            try {
                localStorage.setItem(STORAGE_HISTORY_KEY, JSON.stringify(next));
            } catch {}
            return next;
        });
    };

    const handleClearHistory = () => {
        setHistory([]);
        try {
            localStorage.removeItem(STORAGE_HISTORY_KEY);
        } catch {}
    };

    const handleRemoveHistoryItem = (malId: number) => {
        setHistory((prev) => {
            const next = prev.filter((h) => h.malId !== malId);
            try {
                localStorage.setItem(STORAGE_HISTORY_KEY, JSON.stringify(next));
            } catch {}
            return next;
        });
    };

    const handlePlayHistory = (item: WatchHistoryItem) => {
        const dummyAnime: AnimeItem = {
            mal_id: item.malId,
            title: item.title,
            images: {
                jpg: { large_image_url: item.poster },
                webp: { large_image_url: item.poster },
            },
        };
        setPlayingEpisode({ anime: dummyAnime, episodeNumber: item.episodeNumber });
    };

    const bookmarkIds = bookmarks.map((b) => b.mal_id);
    const heroAnime = seasonList[0] || null;

    return (
        <div className="w-full min-h-screen px-4 sm:px-6 lg:px-8 py-6 max-w-7xl mx-auto lilac-theme">
            {/* Top Navigation Bar for Anime Hub */}
            <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 mb-8 pb-5 border-b border-white/5">
                <div className="flex items-center gap-3.5">
                    <div className="size-11 rounded-2xl bg-lilac-faint border border-lilac-border flex items-center justify-center text-lilac-primary shadow-sm shrink-0">
                        <Sparkles className="size-5" />
                    </div>
                    <div>
                        <div className="flex items-center gap-2">
                            <h1 className="text-xl sm:text-2xl font-black text-ink tracking-tight">
                                Anime Hub
                            </h1>
                            <span className="lilac-badge">Phrolova Engine</span>
                        </div>
                        <p className="text-xs text-ink-faint mt-0.5">
                            Seasonal catalog, weekly broadcast schedules, and high-speed VOD archiving
                        </p>
                    </div>
                </div>

                <div className="flex flex-wrap items-center gap-2.5">
                    {/* Content / Video Source Selector (from Lilac specification) */}
                    <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-black/40 border border-white/10 text-xs">
                        <span className="text-ink-faint font-semibold">Source:</span>
                        <select
                            defaultValue="reanime"
                            className="bg-transparent text-lilac-primary font-bold focus:outline-none cursor-pointer"
                            onChange={(e) => {
                                // Navigate to VOD or update source filter
                            }}
                        >
                            <option value="reanime" className="bg-[#141418] text-white">Re:Anime</option>
                            <option value="ohli24" className="bg-[#141418] text-white">Ohli24</option>
                            <option value="moeni" className="bg-[#141418] text-white">Moeni</option>
                            <option value="anilife" className="bg-[#141418] text-white">Anilife</option>
                            <option value="animaru" className="bg-[#141418] text-white">Animaru</option>
                            <option value="linkani" className="bg-[#141418] text-white">Linkani</option>
                            <option value="tvwiki" className="bg-[#141418] text-white">TVWiki</option>
                        </select>
                    </div>

                    {/* Sub Tab Navigation */}
                    <div className="flex items-center gap-1 p-1 bg-black/40 border border-white/5 rounded-2xl overflow-x-auto text-xs font-semibold">
                        <button
                            type="button"
                            onClick={() => setActiveTab("home")}
                            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl transition-all ${
                                activeTab === "home"
                                    ? "bg-lilac-primary text-gray-950 font-bold shadow-md"
                                    : "text-ink-muted hover:text-ink"
                            }`}
                        >
                            <Sparkles className="size-3.5" />
                            <span>Home</span>
                        </button>

                        <button
                            type="button"
                            onClick={() => setActiveTab("schedule")}
                            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl transition-all ${
                                activeTab === "schedule"
                                    ? "bg-lilac-primary text-gray-950 font-bold shadow-md"
                                    : "text-ink-muted hover:text-ink"
                            }`}
                        >
                            <Calendar className="size-3.5" />
                            <span>Schedule</span>
                        </button>

                        <button
                            type="button"
                            onClick={() => setActiveTab("catalog")}
                            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl transition-all ${
                                activeTab === "catalog"
                                    ? "bg-lilac-primary text-gray-950 font-bold shadow-md"
                                    : "text-ink-muted hover:text-ink"
                            }`}
                        >
                            <Search className="size-3.5" />
                            <span>Catalog</span>
                        </button>

                        <button
                            type="button"
                            onClick={() => setActiveTab("library")}
                            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl transition-all ${
                                activeTab === "library"
                                    ? "bg-lilac-primary text-gray-950 font-bold shadow-md"
                                    : "text-ink-muted hover:text-ink"
                            }`}
                        >
                            <FolderHeart className="size-3.5" />
                            <span>Library ({bookmarks.length})</span>
                        </button>
                    </div>
                </div>
            </div>

            {/* TAB CONTENTS */}
            {activeTab === "home" && (
                <div>
                    {/* Hero Recommendation */}
                    <AnimeHero
                        anime={heroAnime}
                        onSelect={setSelectedAnime}
                        isBookmarked={heroAnime ? bookmarkIds.includes(heroAnime.mal_id) : false}
                        onToggleBookmark={handleToggleBookmark}
                    />

                    {/* Continue Watching Rail */}
                    <AnimeHistoryRail
                        history={history}
                        onPlayHistory={handlePlayHistory}
                        onClearHistory={handleClearHistory}
                        onRemoveItem={handleRemoveHistoryItem}
                    />

                    {/* Current Season Releases */}
                    <AnimeRail
                        title="Current Season"
                        subtitle="Hot new anime currently airing this season"
                        items={seasonList}
                        loading={loadingHome}
                        onSelect={setSelectedAnime}
                        bookmarks={bookmarkIds}
                        onToggleBookmark={handleToggleBookmark}
                        onSeeAll={() => setActiveTab("catalog")}
                    />

                    {/* Top Popular Anime */}
                    <AnimeRail
                        title="Top Popular"
                        subtitle="Highest rated and most watched classics worldwide"
                        items={topList}
                        loading={loadingHome}
                        onSelect={setSelectedAnime}
                        bookmarks={bookmarkIds}
                        onToggleBookmark={handleToggleBookmark}
                        onSeeAll={() => setActiveTab("catalog")}
                    />

                    {/* Weekly Schedule Preview */}
                    <WeeklySchedule
                        onSelect={setSelectedAnime}
                        bookmarks={bookmarkIds}
                        onToggleBookmark={handleToggleBookmark}
                    />
                </div>
            )}

            {activeTab === "schedule" && (
                <WeeklySchedule
                    onSelect={setSelectedAnime}
                    bookmarks={bookmarkIds}
                    onToggleBookmark={handleToggleBookmark}
                />
            )}

            {activeTab === "catalog" && (
                <AnimeSearchCatalog
                    onSelect={setSelectedAnime}
                    bookmarks={bookmarkIds}
                    onToggleBookmark={handleToggleBookmark}
                />
            )}

            {activeTab === "library" && (
                <AnimeLibrary
                    bookmarkedItems={bookmarks}
                    onSelect={setSelectedAnime}
                    onToggleBookmark={handleToggleBookmark}
                    onExplore={() => setActiveTab("home")}
                />
            )}

            {/* Anime Detail Modal */}
            {selectedAnime && (
                <AnimeDetailModal
                    animeId={selectedAnime.mal_id}
                    initialData={selectedAnime}
                    onClose={() => setSelectedAnime(null)}
                    onPlayEpisode={(anime, ep) => {
                        setSelectedAnime(null);
                        setPlayingEpisode({ anime, episodeNumber: ep });
                    }}
                    isBookmarked={bookmarkIds.includes(selectedAnime.mal_id)}
                    onToggleBookmark={handleToggleBookmark}
                />
            )}

            {/* Lilac Player Modal */}
            {playingEpisode && (
                <AnimePlayerModal
                    anime={playingEpisode.anime}
                    episodeNumber={playingEpisode.episodeNumber}
                    onClose={() => setPlayingEpisode(null)}
                    onSaveHistory={handleSaveHistory}
                    onSelectEpisode={(anime, ep) =>
                        setPlayingEpisode({ anime, episodeNumber: ep })
                    }
                />
            )}
        </div>
    );
}
