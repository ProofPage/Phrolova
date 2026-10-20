import React from "react";
import { Play, Trash2, Clock } from "lucide-react";
import { AnimeItem } from "./AnimeCard";

export interface WatchHistoryItem {
    malId: number;
    title: string;
    poster: string;
    episodeNumber: number;
    currentTime: number;
    duration: number;
    updatedAt: number;
}

interface AnimeHistoryRailProps {
    history: WatchHistoryItem[];
    onPlayHistory: (item: WatchHistoryItem) => void;
    onClearHistory?: () => void;
    onRemoveItem?: (malId: number) => void;
}

export const AnimeHistoryRail: React.FC<AnimeHistoryRailProps> = ({
    history,
    onPlayHistory,
    onClearHistory,
    onRemoveItem,
}) => {
    if (!history || history.length === 0) return null;

    const formatTime = (secs: number) => {
        const m = Math.floor(secs / 60);
        const s = Math.floor(secs % 60);
        return `${m}:${s < 10 ? "0" : ""}${s}`;
    };

    return (
        <section className="mb-10">
            <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                    <Clock className="size-5 text-lilac-primary" />
                    <h2 className="text-lg sm:text-xl font-bold text-ink tracking-tight">
                        Continue Watching
                    </h2>
                </div>

                {onClearHistory && (
                    <button
                        type="button"
                        onClick={onClearHistory}
                        className="text-xs text-ink-faint hover:text-rose-400 flex items-center gap-1 transition-colors"
                        title="Clear History"
                    >
                        <Trash2 className="size-3.5" />
                        <span>Clear All</span>
                    </button>
                )}
            </div>

            <div className="lilac-rail">
                {history.map((item) => {
                    const percent =
                        item.duration > 0
                            ? Math.min(100, Math.round((item.currentTime / item.duration) * 100))
                            : 0;

                    return (
                        <div
                            key={item.malId}
                            className="w-[220px] shrink-0 rounded-xl overflow-hidden bg-black/40 border border-white/5 hover:border-lilac-border group cursor-pointer transition-all flex flex-col"
                            onClick={() => onPlayHistory(item)}
                        >
                            <div className="relative aspect-video w-full bg-black/60 overflow-hidden">
                                {item.poster ? (
                                    <img
                                        src={item.poster}
                                        alt={item.title}
                                        className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                                    />
                                ) : (
                                    <div className="w-full h-full flex items-center justify-center text-xs text-ink-faint">
                                        No Image
                                    </div>
                                )}

                                <div className="absolute inset-0 bg-black/30 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                                    <div className="size-10 rounded-full bg-lilac-primary text-gray-950 flex items-center justify-center shadow-lg">
                                        <Play className="size-5 fill-current ml-0.5" />
                                    </div>
                                </div>

                                {/* Progress Bar */}
                                <div className="absolute bottom-0 inset-x-0 h-1 bg-white/20">
                                    <div
                                        className="h-full bg-lilac-primary"
                                        style={{ width: `${percent}%` }}
                                    />
                                </div>
                            </div>

                            <div className="p-3 flex flex-col justify-between flex-1">
                                <div>
                                    <h3
                                        className="text-xs font-bold text-ink line-clamp-1 group-hover:text-lilac-hover transition-colors"
                                        title={item.title}
                                    >
                                        {item.title}
                                    </h3>
                                    <p className="text-[11px] font-semibold text-lilac-primary mt-1">
                                        EP {item.episodeNumber}
                                    </p>
                                </div>

                                <div className="mt-2 flex items-center justify-between text-[10px] text-ink-faint">
                                    <span>
                                        {formatTime(item.currentTime)} / {formatTime(item.duration)}
                                    </span>
                                    {onRemoveItem && (
                                        <button
                                            type="button"
                                            className="opacity-0 group-hover:opacity-100 hover:text-rose-400 p-1 transition-opacity"
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                onRemoveItem(item.malId);
                                            }}
                                            title="Delete"
                                        >
                                            <Trash2 className="size-3" />
                                        </button>
                                    )}
                                </div>
                            </div>
                        </div>
                    );
                })}
            </div>
        </section>
    );
};
