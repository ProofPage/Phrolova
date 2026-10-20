import React, { useState, useEffect } from "react";
import { Calendar, RotateCw } from "lucide-react";
import { AnimeCard, AnimeItem } from "./AnimeCard";

const DAYS = [
    { key: "monday", label: "Mon" },
    { key: "tuesday", label: "Tue" },
    { key: "wednesday", label: "Wed" },
    { key: "thursday", label: "Thu" },
    { key: "friday", label: "Fri" },
    { key: "saturday", label: "Sat" },
    { key: "sunday", label: "Sun" },
];

function getTodayKey(): string {
    const day = new Date().getDay();
    // 0 = Sunday, 1 = Monday, ...
    const mapping = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
    return mapping[day];
}

interface WeeklyScheduleProps {
    onSelect: (anime: AnimeItem) => void;
    bookmarks?: number[];
    onToggleBookmark?: (anime: AnimeItem) => void;
}

export const WeeklySchedule: React.FC<WeeklyScheduleProps> = ({
    onSelect,
    bookmarks = [],
    onToggleBookmark,
}) => {
    const [selectedDay, setSelectedDay] = useState<string>(getTodayKey());
    const [scheduleMap, setScheduleMap] = useState<Record<string, AnimeItem[]>>({});
    const [loading, setLoading] = useState<boolean>(false);

    const loadDaySchedule = async (day: string) => {
        if (scheduleMap[day]?.length) return;
        setLoading(true);
        try {
            const res = await fetch(`/api/lilac/schedule?day=${day}`);
            if (res.ok) {
                const data = await res.json();
                setScheduleMap((prev) => ({ ...prev, [day]: data.schedule || [] }));
            }
        } catch {
            // ignore network errors
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadDaySchedule(selectedDay);
    }, [selectedDay]);

    const activeList = scheduleMap[selectedDay] || [];

    return (
        <section className="mb-12">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-5">
                <div>
                    <h2 className="text-lg sm:text-xl font-bold text-ink tracking-tight flex items-center gap-2">
                        <Calendar className="size-5 text-lilac-primary" />
                        <span>Weekly Broadcast Schedule</span>
                    </h2>
                    <p className="text-xs text-ink-faint mt-0.5">
                        Daily television and streaming broadcasts
                    </p>
                </div>

                <div className="flex items-center gap-2">
                    <button
                        type="button"
                        onClick={() => setSelectedDay(getTodayKey())}
                        className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-lilac-border bg-lilac-faint text-lilac-primary hover:bg-lilac-primary hover:text-gray-950 transition-all"
                    >
                        Today ({DAYS.find((d) => d.key === getTodayKey())?.label})
                    </button>
                    <button
                        type="button"
                        onClick={() => {
                            setScheduleMap((prev) => {
                                const next = { ...prev };
                                delete next[selectedDay];
                                return next;
                            });
                            loadDaySchedule(selectedDay);
                        }}
                        className="p-1.5 rounded-lg border border-white/10 hover:border-lilac-border bg-black/40 text-ink-muted hover:text-ink transition-all"
                        title="Refresh"
                        aria-label="Refresh Schedule"
                    >
                        <RotateCw className={`size-4 ${loading ? "animate-spin" : ""}`} />
                    </button>
                </div>
            </div>

            {/* Day Selector Tabs */}
            <div className="flex items-center gap-1.5 overflow-x-auto pb-3 mb-6 scrollbar-none">
                {DAYS.map((d) => {
                    const isToday = d.key === getTodayKey();
                    const isActive = d.key === selectedDay;
                    return (
                        <button
                            key={d.key}
                            type="button"
                            onClick={() => setSelectedDay(d.key)}
                            className={`lilac-day-tab relative shrink-0 ${isActive ? "active" : ""}`}
                        >
                            <span>{d.label}</span>
                            {isToday && (
                                <span className="absolute -top-1 -right-1 size-2 rounded-full bg-lilac-primary ring-2 ring-background" />
                            )}
                        </button>
                    );
                })}
            </div>

            {/* Grid of anime items for selected day */}
            {loading ? (
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
                    {Array.from({ length: 6 }).map((_, i) => (
                        <div key={i} className="aspect-[2/3] rounded-xl bg-white/5 animate-pulse" />
                    ))}
                </div>
            ) : activeList.length > 0 ? (
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
                    {activeList.map((anime) => (
                        <AnimeCard
                            key={anime.mal_id}
                            anime={anime}
                            onSelect={onSelect}
                            isBookmarked={bookmarks.includes(anime.mal_id)}
                            onToggleBookmark={onToggleBookmark}
                        />
                    ))}
                </div>
            ) : (
                <div className="p-12 text-center rounded-2xl border border-white/5 bg-black/20 text-ink-faint">
                    <p className="text-sm">No scheduled anime found for this day.</p>
                </div>
            )}
        </section>
    );
};
