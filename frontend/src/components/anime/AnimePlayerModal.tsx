import React, { useState, useEffect, useRef } from "react";
import {
    X,
    Play,
    Pause,
    Volume2,
    VolumeX,
    Maximize,
    FastForward,
    SkipForward,
    SkipBack,
    Settings,
    Sliders,
    Type,
    Tv,
} from "lucide-react";
import Hls from "hls.js";
import { AnimeItem } from "./AnimeCard";
import { WatchHistoryItem } from "./AnimeHistoryRail";

interface SkipInterval {
    type: string;
    startTime: number;
    endTime: number;
}

interface AnimePlayerModalProps {
    anime: AnimeItem;
    episodeNumber: number;
    streamUrl?: string;
    onClose: () => void;
    onSaveHistory?: (item: WatchHistoryItem) => void;
    onSelectEpisode?: (anime: AnimeItem, ep: number) => void;
}

export const AnimePlayerModal: React.FC<AnimePlayerModalProps> = ({
    anime,
    episodeNumber,
    streamUrl,
    onClose,
    onSaveHistory,
    onSelectEpisode,
}) => {
    const videoRef = useRef<HTMLVideoElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const [isPlaying, setIsPlaying] = useState<boolean>(false);
    const [currentTime, setCurrentTime] = useState<number>(0);
    const [duration, setDuration] = useState<number>(0);
    const [volume, setVolume] = useState<number>(1);
    const [isMuted, setIsMuted] = useState<boolean>(false);
    const [playbackRate, setPlaybackRate] = useState<number>(1);
    const [aspectRatio, setAspectRatio] = useState<"contain" | "cover" | "fill">("contain");
    const [seekStep, setSeekStep] = useState<number>(10);
    const [autoSkip, setAutoSkip] = useState<boolean>(false);

    // Subtitle Customization
    const [subtitleSize, setSubtitleSize] = useState<number>(100); // 50% ~ 200%
    const [subtitleSync, setSubtitleSync] = useState<number>(0); // -5s ~ +5s

    // Settings Panel Toggle
    const [showSettings, setShowSettings] = useState<boolean>(false);
    const [settingsTab, setSettingsTab] = useState<"play" | "subtitle" | "aspect">("play");

    // AniSkip
    const [skipIntervals, setSkipIntervals] = useState<SkipInterval[]>([]);
    const [activeSkip, setActiveSkip] = useState<SkipInterval | null>(null);

    // Fetch AniSkip intervals
    useEffect(() => {
        fetch(`/api/lilac/skip-times/${anime.mal_id}/${episodeNumber}`)
            .then((res) => res.json())
            .then((data) => {
                if (data.found && data.results) {
                    setSkipIntervals(data.results);
                }
            })
            .catch(() => {});
    }, [anime.mal_id, episodeNumber]);

    // Setup Video / HLS
    useEffect(() => {
        const video = videoRef.current;
        if (!video) return;

        let hls: Hls | null = null;
        const mediaSource =
            streamUrl ||
            "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8";

        if (mediaSource.includes(".m3u8")) {
            if (Hls.isSupported()) {
                hls = new Hls({ enableWorker: true });
                hls.loadSource(mediaSource);
                hls.attachMedia(video);
            } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
                video.src = mediaSource;
            }
        } else {
            video.src = mediaSource;
        }

        const handleTimeUpdate = () => {
            const cur = video.currentTime;
            setCurrentTime(cur);
            setDuration(video.duration || 0);

            // Check for AniSkip trigger
            const matched = skipIntervals.find(
                (int) => cur >= int.startTime && cur < int.endTime
            );
            setActiveSkip(matched || null);

            // Auto-skip if enabled
            if (matched && autoSkip) {
                video.currentTime = matched.endTime + 0.1;
            }

            // Save history periodically
            if (onSaveHistory && video.duration > 0) {
                onSaveHistory({
                    malId: anime.mal_id,
                    title: anime.title_english || anime.title,
                    poster:
                        anime.images?.webp?.large_image_url ||
                        anime.images?.jpg?.large_image_url ||
                        "",
                    episodeNumber,
                    currentTime: cur,
                    duration: video.duration,
                    updatedAt: Date.now(),
                });
            }
        };

        const handlePlay = () => setIsPlaying(true);
        const handlePause = () => setIsPlaying(false);

        video.addEventListener("timeupdate", handleTimeUpdate);
        video.addEventListener("play", handlePlay);
        video.addEventListener("pause", handlePause);

        return () => {
            video.removeEventListener("timeupdate", handleTimeUpdate);
            video.removeEventListener("play", handlePlay);
            video.removeEventListener("pause", handlePause);
            if (hls) hls.destroy();
        };
    }, [streamUrl, skipIntervals, anime, episodeNumber, autoSkip]);

    // Keyboard shortcuts
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            const video = videoRef.current;
            if (!video) return;

            if (e.key === "Escape") {
                if (showSettings) {
                    setShowSettings(false);
                } else {
                    onClose();
                }
            } else if (e.key === " " || e.key === "k") {
                e.preventDefault();
                if (video.paused) video.play();
                else video.pause();
            } else if (e.key === "ArrowLeft") {
                e.preventDefault();
                video.currentTime = Math.max(0, video.currentTime - seekStep);
            } else if (e.key === "ArrowRight") {
                e.preventDefault();
                video.currentTime = Math.min(video.duration || 0, video.currentTime + seekStep);
            } else if (e.key === "m") {
                video.muted = !video.muted;
                setIsMuted(video.muted);
            } else if (e.key === "f") {
                if (containerRef.current) {
                    if (!document.fullscreenElement) {
                        containerRef.current.requestFullscreen().catch(() => {});
                    } else {
                        document.exitFullscreen().catch(() => {});
                    }
                }
            }
        };

        window.addEventListener("keydown", handleKeyDown);
        return () => window.removeEventListener("keydown", handleKeyDown);
    }, [onClose, seekStep, showSettings]);

    const handleSkip = () => {
        if (!activeSkip || !videoRef.current) return;
        videoRef.current.currentTime = activeSkip.endTime + 0.1;
    };

    const togglePlay = () => {
        const v = videoRef.current;
        if (!v) return;
        if (v.paused) v.play();
        else v.pause();
    };

    const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
        const v = videoRef.current;
        if (!v) return;
        const target = parseFloat(e.target.value);
        v.currentTime = target;
        setCurrentTime(target);
    };

    const handleRateChange = (rate: number) => {
        const v = videoRef.current;
        if (!v) return;
        v.playbackRate = rate;
        setPlaybackRate(rate);
    };

    const formatTime = (secs: number) => {
        const m = Math.floor(secs / 60);
        const s = Math.floor(secs % 60);
        return `${m}:${s < 10 ? "0" : ""}${s}`;
    };

    const totalEps = anime.episodes || 12;

    return (
        <div
            ref={containerRef}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/95 select-none"
        >
            <video
                ref={videoRef}
                className={`w-full h-full max-h-screen ${
                    aspectRatio === "contain"
                        ? "object-contain"
                        : aspectRatio === "cover"
                        ? "object-cover"
                        : "object-fill"
                }`}
                onClick={togglePlay}
                autoPlay
            />

            {/* Top Bar Overlay */}
            <div className="absolute top-0 inset-x-0 p-5 bg-gradient-to-b from-black/80 to-transparent flex items-center justify-between text-white z-40">
                <div className="flex items-center gap-3">
                    <span className="lilac-badge">Lilac Player</span>
                    <h2 className="text-sm sm:text-base font-bold truncate max-w-md">
                        {anime.title_english || anime.title} — EP {episodeNumber}
                    </h2>
                </div>

                <div className="flex items-center gap-2">
                    <button
                        type="button"
                        onClick={() => setShowSettings(!showSettings)}
                        className={`p-2 rounded-full transition-all ${
                            showSettings
                                ? "bg-lilac-primary text-gray-950"
                                : "bg-black/60 text-white/80 hover:text-white hover:bg-black/80"
                        }`}
                        title="Player Settings"
                        aria-label="Settings"
                    >
                        <Settings className="size-5" />
                    </button>

                    <button
                        type="button"
                        onClick={onClose}
                        className="p-2 rounded-full bg-black/60 text-white/80 hover:text-white hover:bg-black/80 transition-all"
                        aria-label="Close"
                    >
                        <X className="size-5" />
                    </button>
                </div>
            </div>

            {/* In-Player Settings Drawer */}
            {showSettings && (
                <div className="absolute right-4 top-20 bottom-24 w-80 bg-[#141418]/95 backdrop-blur-md border border-lilac-border rounded-2xl shadow-2xl p-4 flex flex-col z-50 text-white animate-fadeIn">
                    <div className="flex items-center justify-between pb-3 border-b border-white/10 mb-3">
                        <h3 className="text-xs font-bold text-ink uppercase tracking-wider flex items-center gap-1.5">
                            <Sliders className="size-3.5 text-lilac-primary" />
                            <span>Player Settings</span>
                        </h3>
                        <button
                            type="button"
                            onClick={() => setShowSettings(false)}
                            className="text-gray-400 hover:text-white p-1"
                        >
                            <X className="size-4" />
                        </button>
                    </div>

                    {/* Tab Navigation */}
                    <div className="flex items-center gap-1 p-1 bg-black/40 rounded-xl mb-4 text-xs font-semibold">
                        <button
                            type="button"
                            onClick={() => setSettingsTab("play")}
                            className={`flex-1 py-1.5 rounded-lg transition-all ${
                                settingsTab === "play"
                                    ? "bg-lilac-primary text-gray-950 font-bold"
                                    : "text-gray-400 hover:text-white"
                            }`}
                        >
                            Playback
                        </button>
                        <button
                            type="button"
                            onClick={() => setSettingsTab("subtitle")}
                            className={`flex-1 py-1.5 rounded-lg transition-all ${
                                settingsTab === "subtitle"
                                    ? "bg-lilac-primary text-gray-950 font-bold"
                                    : "text-gray-400 hover:text-white"
                            }`}
                        >
                            Subtitles
                        </button>
                        <button
                            type="button"
                            onClick={() => setSettingsTab("aspect")}
                            className={`flex-1 py-1.5 rounded-lg transition-all ${
                                settingsTab === "aspect"
                                    ? "bg-lilac-primary text-gray-950 font-bold"
                                    : "text-gray-400 hover:text-white"
                            }`}
                        >
                            Aspect
                        </button>
                    </div>

                    <div className="flex-1 overflow-y-auto space-y-4 text-xs">
                        {settingsTab === "play" && (
                            <>
                                <div>
                                    <label className="text-gray-300 font-semibold block mb-2">
                                        Playback Speed
                                    </label>
                                    <div className="grid grid-cols-4 gap-1.5">
                                        {[0.75, 1, 1.25, 1.5, 2].map((r) => (
                                            <button
                                                key={r}
                                                type="button"
                                                onClick={() => handleRateChange(r)}
                                                className={`py-1.5 rounded-lg border text-center font-bold ${
                                                    playbackRate === r
                                                        ? "border-lilac-primary bg-lilac-faint text-lilac-hover"
                                                        : "border-white/10 hover:border-white/20 text-gray-300"
                                                }`}
                                            >
                                                {r}x
                                            </button>
                                        ))}
                                    </div>
                                </div>

                                <div>
                                    <label className="text-gray-300 font-semibold block mb-2">
                                        Seek Step
                                    </label>
                                    <div className="grid grid-cols-4 gap-1.5">
                                        {[5, 10, 15, 30].map((s) => (
                                            <button
                                                key={s}
                                                type="button"
                                                onClick={() => setSeekStep(s)}
                                                className={`py-1.5 rounded-lg border text-center font-bold ${
                                                    seekStep === s
                                                        ? "border-lilac-primary bg-lilac-faint text-lilac-hover"
                                                        : "border-white/10 hover:border-white/20 text-gray-300"
                                                }`}
                                            >
                                                {s}s
                                            </button>
                                        ))}
                                    </div>
                                </div>

                                <div className="pt-2 border-t border-white/10 flex items-center justify-between">
                                    <div>
                                        <span className="font-semibold block text-white">
                                            AniSkip Auto-Skip
                                        </span>
                                        <span className="text-[11px] text-gray-400">
                                            Automatically skip intro and outro intervals
                                        </span>
                                    </div>
                                    <input
                                        type="checkbox"
                                        checked={autoSkip}
                                        onChange={(e) => setAutoSkip(e.target.checked)}
                                        className="size-4 rounded accent-lilac-primary cursor-pointer"
                                    />
                                </div>
                            </>
                        )}

                        {settingsTab === "subtitle" && (
                            <>
                                <div>
                                    <div className="flex justify-between items-center mb-1">
                                        <label className="text-gray-300 font-semibold">
                                            Subtitle Size
                                        </label>
                                        <span className="text-lilac-primary font-bold">
                                            {subtitleSize}%
                                        </span>
                                    </div>
                                    <input
                                        type="range"
                                        min={50}
                                        max={200}
                                        step={5}
                                        value={subtitleSize}
                                        onChange={(e) => setSubtitleSize(Number(e.target.value))}
                                        className="w-full accent-lilac-primary"
                                    />
                                </div>

                                <div>
                                    <div className="flex justify-between items-center mb-1">
                                        <label className="text-gray-300 font-semibold">
                                            Subtitle Sync Offset
                                        </label>
                                        <span className="text-lilac-primary font-bold">
                                            {subtitleSync > 0 ? `+${subtitleSync}` : subtitleSync}s
                                        </span>
                                    </div>
                                    <input
                                        type="range"
                                        min={-5}
                                        max={5}
                                        step={0.5}
                                        value={subtitleSync}
                                        onChange={(e) => setSubtitleSync(Number(e.target.value))}
                                        className="w-full accent-lilac-primary"
                                    />
                                </div>
                            </>
                        )}

                        {settingsTab === "aspect" && (
                            <div className="space-y-2">
                                {[
                                    { id: "contain", label: "Fit Screen (Contain)" },
                                    { id: "cover", label: "Crop to Fill (Cover)" },
                                    { id: "fill", label: "Stretch (Fill)" },
                                ].map((asp) => (
                                    <button
                                        key={asp.id}
                                        type="button"
                                        onClick={() => setAspectRatio(asp.id as any)}
                                        className={`w-full p-2.5 rounded-xl border text-left font-semibold flex items-center justify-between ${
                                            aspectRatio === asp.id
                                                ? "border-lilac-primary bg-lilac-faint text-lilac-hover"
                                                : "border-white/10 hover:border-white/20 text-gray-300"
                                        }`}
                                    >
                                        <span>{asp.label}</span>
                                        {aspectRatio === asp.id && (
                                            <Tv className="size-4 text-lilac-primary" />
                                        )}
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* AniSkip Banner Notification */}
            {activeSkip && !autoSkip && (
                <div className="lilac-aniskip-banner">
                    <div className="flex items-center gap-2">
                        <FastForward className="size-4 text-lilac-primary animate-pulse" />
                        <span className="text-xs font-bold">
                            {activeSkip.type.includes("op") ? "Opening Detected" : "Ending Detected"}
                        </span>
                    </div>
                    <button
                        type="button"
                        onClick={handleSkip}
                        className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-lilac-primary text-gray-950 text-xs font-extrabold hover:bg-lilac-hover shadow-md transition-all"
                    >
                        <span>Skip</span>
                        <SkipForward className="size-3.5 fill-current" />
                    </button>
                </div>
            )}

            {/* Bottom Controls Overlay */}
            <div className="absolute bottom-0 inset-x-0 p-4 sm:p-6 bg-gradient-to-t from-black/90 via-black/50 to-transparent flex flex-col gap-3 text-white z-40">
                {/* Progress Slider */}
                <div className="flex items-center gap-3">
                    <span className="text-xs font-medium text-gray-300 w-12 text-right">
                        {formatTime(currentTime)}
                    </span>
                    <input
                        type="range"
                        min={0}
                        max={duration || 100}
                        value={currentTime}
                        onChange={handleSeek}
                        className="flex-1 h-1.5 rounded-lg appearance-none bg-white/20 accent-lilac-primary cursor-pointer hover:h-2 transition-all"
                    />
                    <span className="text-xs font-medium text-gray-300 w-12">
                        {formatTime(duration)}
                    </span>
                </div>

                {/* Buttons Row */}
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4">
                        {/* Prev Episode */}
                        {onSelectEpisode && episodeNumber > 1 && (
                            <button
                                type="button"
                                onClick={() => onSelectEpisode(anime, episodeNumber - 1)}
                                className="p-2 rounded-full hover:bg-white/10 text-gray-300 hover:text-white transition-colors"
                                title="Previous Episode"
                                aria-label="Previous Episode"
                            >
                                <SkipBack className="size-4 fill-current" />
                            </button>
                        )}

                        <button
                            type="button"
                            onClick={togglePlay}
                            className="p-2.5 rounded-full bg-lilac-primary text-gray-950 hover:bg-lilac-hover transition-colors shadow-lg"
                        >
                            {isPlaying ? (
                                <Pause className="size-5 fill-current" />
                            ) : (
                                <Play className="size-5 fill-current ml-0.5" />
                            )}
                        </button>

                        {/* Next Episode */}
                        {onSelectEpisode && episodeNumber < totalEps && (
                            <button
                                type="button"
                                onClick={() => onSelectEpisode(anime, episodeNumber + 1)}
                                className="p-2 rounded-full hover:bg-white/10 text-gray-300 hover:text-white transition-colors"
                                title="Next Episode"
                                aria-label="Next Episode"
                            >
                                <SkipForward className="size-4 fill-current" />
                            </button>
                        )}

                        <button
                            type="button"
                            onClick={() => {
                                const v = videoRef.current;
                                if (!v) return;
                                v.muted = !v.muted;
                                setIsMuted(v.muted);
                            }}
                            className="p-2 rounded-full hover:bg-white/10 transition-colors"
                        >
                            {isMuted ? (
                                <VolumeX className="size-5 text-rose-400" />
                            ) : (
                                <Volume2 className="size-5" />
                            )}
                        </button>
                    </div>

                    <div className="flex items-center gap-3">
                        <button
                            type="button"
                            onClick={() => {
                                if (containerRef.current) {
                                    if (!document.fullscreenElement) {
                                        containerRef.current.requestFullscreen().catch(() => {});
                                    } else {
                                        document.exitFullscreen().catch(() => {});
                                    }
                                }
                            }}
                            className="p-2 rounded-full hover:bg-white/10 transition-colors"
                            aria-label="Fullscreen"
                        >
                            <Maximize className="size-5" />
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};
