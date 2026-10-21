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

const P_TXT = {
    playerSettings: "플레이어 설정",
    playerSettingsDesc: "재생 · 화질 · 자막",
    playTab: "재생",
    subtitleTab: "자막",
    aspectTab: "자막 모양",
    speed: "재생 속도",
    seekStep: "탐색 간격",
    seconds: "초",
    autoSkip: "AniSkip 자동 스킵",
    autoSkipDesc: "오프닝/엔딩 구간을 자동으로 건너뜁니다",
};

interface SkipInterval {
    type: string;
    startTime: number;
    endTime: number;
}

interface AnimePlayerModalProps {
    anime: AnimeItem;
    source?: string;
    episodeNumber: number;
    streamUrl?: string;
    onClose: () => void;
    onSaveHistory?: (item: WatchHistoryItem) => void;
    onSelectEpisode?: (anime: AnimeItem, ep: number) => void;
}

const SUB_TXT = {
    hide: "자막 숨기기",
    applied: "자막 파일을 선택하세요. 외부 플레이어의 자막은 해당 플레이어에서 설정하세요.",
    sources: "자막 소스",
    chooseSource: "원하는 자막 소스 선택",
    fileCount: (n: number) => `${n}개 파일`,
    refetch: "자막 다시 불러오기",
    openFile: "자막 파일 열기",
    supported: "지원 형식: WebVTT (.vtt)",
};

export const AnimePlayerModal: React.FC<AnimePlayerModalProps> = ({
    anime,
    source = "reanime",
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
    const [selectedSubSource, setSelectedSubSource] = useState<string>("reanime");
    const [selectedSubFile, setSelectedSubFile] = useState<string | null>(null);
    const [subtitleUrl, setSubtitleUrl] = useState<string | null>(null);
    const [subtitleError, setSubtitleError] = useState("");
    const subtitleInputRef = useRef<HTMLInputElement>(null);
    const [hideSubtitles, setHideSubtitles] = useState<boolean>(false);

    // Settings Panel Toggle
    const [showSettings, setShowSettings] = useState<boolean>(false);
    const [settingsTab, setSettingsTab] = useState<"play" | "subtitle" | "aspect">("play");

    // AniSkip
    const [skipIntervals, setSkipIntervals] = useState<SkipInterval[]>([]);
    const [activeSkip, setActiveSkip] = useState<SkipInterval | null>(null);

    // Stream resolution
    const [resolvedUrl, setResolvedUrl] = useState<string | null>(streamUrl || null);
    const [isEmbed, setIsEmbed] = useState<boolean>(false);
    const [resolvingStream, setResolvingStream] = useState<boolean>(!streamUrl);
    const [streamError, setStreamError] = useState<string | null>(null);

    useEffect(() => {
        return () => { if (subtitleUrl) URL.revokeObjectURL(subtitleUrl); };
    }, [subtitleUrl]);

    useEffect(() => {
        setSubtitleUrl(null);
        setSelectedSubFile(null);
        setSubtitleError("");
    }, [anime.mal_id, episodeNumber]);

    useEffect(() => {
        const video = videoRef.current;
        if (!video) return;
        const apply = () => {
            for (const track of Array.from(video.textTracks)) {
                track.mode = hideSubtitles ? "disabled" : "showing";
            }
        };
        apply();
        video.textTracks.addEventListener("addtrack", apply);
        return () => video.textTracks.removeEventListener("addtrack", apply);
    }, [hideSubtitles, subtitleUrl, resolvedUrl, isEmbed, resolvingStream]);

    const openSubtitle = async (file: File | undefined) => {
        if (!file) return;
        try {
            const text = (await file.text()).replace(/^\uFEFF/, "");
            if (!/^WEBVTT(?:[ \t]|\r?\n|$)/.test(text)) {
                throw new Error("올바른 WebVTT 자막 파일을 선택하세요.");
            }
            setSubtitleUrl(URL.createObjectURL(new Blob([text], { type: "text/vtt" })));
            setSelectedSubFile(file.name);
            setHideSubtitles(false);
            setSubtitleError("");
        } catch (error) {
            setSubtitleError(error instanceof Error ? error.message : "자막 파일을 읽지 못했습니다.");
        }
    };

    // Fetch actual stream URL
    useEffect(() => {
        const controller = new AbortController();
        setStreamError(null);
        setResolvedUrl(null);
        if (streamUrl) {
            setResolvedUrl(streamUrl);
            setIsEmbed(streamUrl.includes("flixcloud.cc/e/"));
            setResolvingStream(false);
            return () => controller.abort();
        }

        setResolvingStream(true);
        setStreamError(null);

        const params = new URLSearchParams({
            title: anime.title_english || anime.title,
            episode: String(episodeNumber),
            source,
        });
        if ((anime as any).anilist_id) {
            params.append("anilist_id", String((anime as any).anilist_id));
        }
        if (anime.mal_id) {
            params.append("mal_id", String(anime.mal_id));
        }

        fetch(`/api/lilac/stream?${params.toString()}`, { signal: controller.signal })
            .then((r) => {
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                return r.json();
            })
            .then((data) => {
                if (controller.signal.aborted) return;
                if (data.success && data.stream_url) {
                    setResolvedUrl(data.stream_url);
                    setIsEmbed(Boolean(data.is_embed));
                } else {
                    setStreamError(data.message || "해당 회차의 스트림을 불러오지 못했습니다.");
                }
            })
            .catch((err) => {
                if (controller.signal.aborted) return;
                setStreamError("스트림 서버 연결에 실패했습니다.");
            })
            .finally(() => {
                if (!controller.signal.aborted) setResolvingStream(false);
            });
        return () => controller.abort();
    }, [anime, episodeNumber, streamUrl, source]);

    // Fetch AniSkip intervals
    useEffect(() => {
        const controller = new AbortController();
        setSkipIntervals([]);
        setActiveSkip(null);
        fetch(`/api/lilac/skip-times/${anime.mal_id}/${episodeNumber}`, { signal: controller.signal })
            .then((res) => {
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                return res.json();
            })
            .then((data) => {
                if (controller.signal.aborted) return;
                if (data.found && data.results) {
                    setSkipIntervals(data.results);
                }
            })
            .catch(() => {});
        return () => controller.abort();
    }, [anime.mal_id, episodeNumber]);

    // Setup Video / HLS
    useEffect(() => {
        const video = videoRef.current;
        if (!video || !resolvedUrl) return;

        let hls: Hls | null = null;
        const mediaSource = resolvedUrl;

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

        return () => {
            if (hls) hls.destroy();
            video.pause();
            video.removeAttribute("src");
            video.load();
        };
    }, [resolvedUrl, isEmbed, resolvingStream]);

    useEffect(() => {
        const video = videoRef.current;
        if (!video) return;

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
                    title: anime.title_korean || anime.title || anime.title_english || "",
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
        };
    }, [resolvedUrl, isEmbed, resolvingStream, skipIntervals, anime, episodeNumber, autoSkip, onSaveHistory]);

    // Keyboard shortcuts
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            if (e.key === "Escape") {
                if (showSettings) {
                    setShowSettings(false);
                } else {
                    onClose();
                }
                return;
            }
            const video = videoRef.current;
            if (!video) return;
            if (e.key === " " || e.key === "k") {
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
            className="fixed inset-0 z-50 flex items-center justify-center bg-black select-none overflow-hidden"
        >
            {resolvingStream ? (
                <div className="flex flex-col items-center justify-center text-center p-8 z-30">
                    <div className="size-12 border-4 border-[#C8A2C8] border-t-transparent rounded-full animate-spin mb-4" />
                    <p className="text-sm font-bold text-white mb-1">
                        Connecting Video Stream...
                    </p>
                    <p className="text-xs text-gray-400">
                        {anime.title_english || anime.title} — Episode {episodeNumber}
                    </p>
                </div>
            ) : streamError ? (
                <div className="flex flex-col items-center justify-center text-center p-8 max-w-md z-30 bg-[#16161c] border border-white/10 rounded-2xl shadow-2xl">
                    <div className="size-12 rounded-full bg-rose-500/10 border border-rose-500/20 flex items-center justify-center text-rose-400 mb-3">
                        <Tv className="size-6" />
                    </div>
                    <h3 className="text-base font-bold text-white mb-2">
                        Stream Unavailable
                    </h3>
                    <p className="text-xs text-gray-300 mb-6 leading-relaxed">
                        {streamError}
                    </p>
                    <div className="flex items-center gap-3">
                        <button
                            type="button"
                            onClick={onClose}
                            className="px-4 py-2 rounded-xl bg-white/10 text-white text-xs font-semibold hover:bg-white/20 transition-all"
                        >
                            Close
                        </button>
                    </div>
                </div>
            ) : isEmbed && resolvedUrl ? (
                /* Perfectly Aspect-Ratio Constrained 16:9 Iframe Wrapper */
                <div className="w-full h-full flex items-center justify-center bg-black p-2 sm:p-4">
                    <div className="w-full max-w-[94vw] aspect-video max-h-[88vh] bg-black rounded-xl overflow-hidden shadow-2xl relative flex items-center justify-center">
                        <iframe
                            src={resolvedUrl}
                            title="Anime Player"
                            className="w-full h-full border-none"
                            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; fullscreen"
                            allowFullScreen
                        />
                    </div>
                </div>
            ) : (
                /* Responsive 16:9 Video Element with aspect preservation */
                <div className="w-full h-full flex items-center justify-center bg-black p-2 sm:p-4">
                    <div className="w-full max-w-[94vw] aspect-video max-h-[88vh] bg-black rounded-xl overflow-hidden shadow-2xl relative flex items-center justify-center">
                        <video
                            ref={videoRef}
                            className={`w-full h-full object-contain aspect-video ${
                                aspectRatio === "contain"
                                    ? "object-contain"
                                    : aspectRatio === "cover"
                                    ? "object-cover"
                                    : "object-fill"
                            }`}
                            onClick={togglePlay}
                            autoPlay
                        >
                            {subtitleUrl && (
                                <track key={subtitleUrl} kind="subtitles" src={subtitleUrl}
                                    label={selectedSubFile || "Subtitle"} default
                                    onLoad={(e) => {
                                        e.currentTarget.track.mode = hideSubtitles ? "disabled" : "showing";
                                    }}
                                    onError={() => setSubtitleError("자막을 불러오지 못했습니다. 파일 형식을 확인하세요.")}
                                />
                            )}
                        </video>
                    </div>
                </div>
            )}

            {/* Top Bar Overlay */}
            <div className="absolute top-0 inset-x-0 p-4 sm:p-5 bg-gradient-to-b from-black/90 via-black/40 to-transparent flex items-center justify-between text-white z-40 pointer-events-auto">
                <div className="flex items-center gap-3">
                    <span className="lilac-badge">Player</span>
                    <h2 className="text-sm sm:text-base font-bold truncate max-w-md drop-shadow">
                        {anime.title_english || anime.title} — EP {episodeNumber}
                    </h2>
                </div>

                <div className="flex items-center gap-2">
                    <button
                        type="button"
                        onClick={() => setShowSettings(!showSettings)}
                        className={`p-2 rounded-full transition-all ${
                            showSettings
                                ? "bg-[#C8A2C8] text-gray-950"
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

            {/* In-Player Settings Drawer (100% Lilac Parity) */}
            {showSettings && (
                <div className="absolute right-4 top-16 bottom-20 w-88 bg-[#18181c]/95 backdrop-blur-xl border border-white/10 rounded-2xl shadow-2xl p-5 flex flex-col z-50 text-white animate-fadeIn overflow-hidden">
                    {/* Drawer Header */}
                    <div className="flex items-center justify-between pb-3.5 border-b border-white/10 mb-3">
                        <div className="flex items-center gap-2">
                            <span className="p-1.5 rounded-lg bg-white/5 text-[#C8A2C8]">
                                <Settings className="size-4" />
                            </span>
                            <div>
                                <h3 className="text-xs font-bold text-white leading-tight">
                                    {P_TXT.playerSettings}
                                </h3>
                                <p className="text-[10px] text-gray-400">{P_TXT.playerSettingsDesc}</p>
                            </div>
                        </div>
                        <button
                            type="button"
                            onClick={() => setShowSettings(false)}
                            className="text-gray-400 hover:text-white p-1 rounded-lg hover:bg-white/10 transition-all"
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
                                    ? "bg-white text-gray-950 font-bold"
                                    : "text-gray-400 hover:text-white"
                            }`}
                        >
                            {P_TXT.playTab}
                        </button>
                        <button
                            type="button"
                            onClick={() => setSettingsTab("subtitle")}
                            className={`flex-1 py-1.5 rounded-lg transition-all ${
                                settingsTab === "subtitle"
                                    ? "bg-white text-gray-950 font-bold"
                                    : "text-gray-400 hover:text-white"
                            }`}
                        >
                            {P_TXT.subtitleTab}
                        </button>
                        <button
                            type="button"
                            onClick={() => setSettingsTab("aspect")}
                            className={`flex-1 py-1.5 rounded-lg transition-all ${
                                settingsTab === "aspect"
                                    ? "bg-white text-gray-950 font-bold"
                                    : "text-gray-400 hover:text-white"
                            }`}
                        >
                            {P_TXT.aspectTab}
                        </button>
                    </div>

                    {/* Tab Body */}
                    <div className="flex-1 overflow-y-auto space-y-4 text-xs pr-1">
                        {settingsTab === "play" && (
                            <>
                                <div>
                                    <label className="text-gray-300 font-semibold block mb-2">
                                        {P_TXT.speed}
                                    </label>
                                    <div className="grid grid-cols-4 gap-1.5">
                                        {[0.75, 1, 1.25, 1.5, 2].map((r) => (
                                            <button
                                                key={r}
                                                type="button"
                                                onClick={() => handleRateChange(r)}
                                                className={`py-1.5 rounded-lg border text-center font-bold transition-all ${
                                                    playbackRate === r
                                                        ? "border-[#C8A2C8] bg-lilac-faint text-[#C8A2C8]"
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
                                        {P_TXT.seekStep}
                                    </label>
                                    <div className="grid grid-cols-4 gap-1.5">
                                        {[5, 10, 15, 30].map((s) => (
                                            <button
                                                key={s}
                                                type="button"
                                                onClick={() => setSeekStep(s)}
                                                className={`py-1.5 rounded-lg border text-center font-bold transition-all ${
                                                    seekStep === s
                                                        ? "border-[#C8A2C8] bg-lilac-faint text-[#C8A2C8]"
                                                        : "border-white/10 hover:border-white/20 text-gray-300"
                                                }`}
                                            >
                                                {s}{P_TXT.seconds}
                                            </button>
                                        ))}
                                    </div>
                                </div>

                                <div className="pt-2 border-t border-white/10 flex items-center justify-between">
                                    <div>
                                        <span className="font-semibold block text-white">
                                            {P_TXT.autoSkip}
                                        </span>
                                        <span className="text-[11px] text-gray-400">
                                            {P_TXT.autoSkipDesc}
                                        </span>
                                    </div>
                                    <input
                                        type="checkbox"
                                        checked={autoSkip}
                                        onChange={(e) => setAutoSkip(e.target.checked)}
                                        className="size-4 rounded accent-[#C8A2C8] cursor-pointer"
                                    />
                                </div>
                            </>
                        )}

                        {settingsTab === "subtitle" && (
                            <div className="space-y-4">
                                {/* Subtitle Hide Switch */}
                                <div className="p-3 rounded-xl bg-black/40 border border-white/5 flex items-center justify-between">
                                    <span className="text-xs font-semibold text-gray-200">
                                        {SUB_TXT.hide}
                                    </span>
                                    <input
                                        type="checkbox"
                                        checked={hideSubtitles}
                                        onChange={(e) => setHideSubtitles(e.target.checked)}
                                        className="size-4 rounded accent-[#C8A2C8] cursor-pointer"
                                    />
                                </div>

                                <p className="text-[11px] text-[#C8A2C8] font-medium">
                                    {subtitleError || selectedSubFile || SUB_TXT.applied}
                                </p>

                                {/* Subtitle Sources Grid */}
                                <div>
                                    <label className="text-gray-300 font-bold block mb-1">
                                        {SUB_TXT.sources}
                                    </label>
                                    <p className="text-[10px] text-gray-400 mb-2">
                                        {SUB_TXT.chooseSource}
                                    </p>
                                    <div className="grid grid-cols-3 gap-1.5">
                                        {[
                                            { id: "reanime", name: "Re:Anime", sub: "Site Track" },
                                            { id: "kairan", name: "Kairan", sub: "Korean" },
                                            { id: "csora", name: "Csora", sub: "Korean" },
                                            { id: "anissia", name: "Anissia", sub: "Korean" },
                                            { id: "jimaku", name: "Jimaku", sub: "Japanese" },
                                            { id: "ai", name: "AI Translate", sub: "Korean" },
                                        ].map((src) => {
                                            const isSelected = selectedSubSource === src.id;
                                            return (
                                                <button
                                                    key={src.id}
                                                    type="button"
                                                    disabled
                                                    onClick={() => setSelectedSubSource(src.id)}
                                                    className={`p-2 rounded-xl border text-left transition-all cursor-pointer ${
                                                        isSelected
                                                            ? "border-[#C8A2C8] bg-lilac-faint text-white shadow-sm ring-1 ring-[#C8A2C8]"
                                                            : "border-white/10 hover:border-white/20 text-gray-300 bg-white/[0.02]"
                                                    }`}
                                                >
                                                    <span className="block text-[11px] font-bold">{src.name}</span>
                                                    <span className="block text-[9px] text-gray-400 mt-0.5">{src.sub}</span>
                                                </button>
                                            );
                                        })}
                                    </div>
                                </div>

                                {/* Jimaku Japanese Subtitles Sample List */}
                                <div>
                                    <div className="flex items-center justify-between mb-2">
                                        <span className="text-xs font-bold text-gray-200">
                                            {SUB_TXT.openFile}
                                        </span>
                                        <span className="text-[10px] text-gray-400">{SUB_TXT.fileCount(selectedSubFile ? 1 : 0)}</span>
                                    </div>
                                    <div className="space-y-1.5 max-h-36 overflow-y-auto pr-1">
                                        {(selectedSubFile ? [{ name: selectedSubFile, format: "VTT" }] : []).map((f, idx) => {
                                            const isSelected = selectedSubFile === f.name;
                                            return (
                                                <button
                                                    key={idx}
                                                    type="button"
                                                    onClick={() => setHideSubtitles(false)}
                                                    className={`w-full p-2 rounded-lg border text-left flex items-center justify-between transition-all cursor-pointer ${
                                                        isSelected
                                                            ? "bg-lilac-faint border-[#C8A2C8] text-white shadow-sm"
                                                            : "bg-black/40 hover:bg-white/5 border-white/5 text-gray-300"
                                                    }`}
                                                >
                                                    <span className="text-[11px] truncate max-w-[190px]">
                                                        {f.name}
                                                    </span>
                                                    <span className="text-[9px] text-gray-400 shrink-0 ml-1">
                                                        {f.format}
                                                    </span>
                                                </button>
                                            );
                                        })}
                                    </div>
                                </div>

                                {/* When Subtitle Missing */}
                                <div className="pt-2 border-t border-white/10">
                                    <span className="text-xs font-bold text-gray-200 block mb-2">
                                        {SUB_TXT.sources}
                                    </span>
                                    <div className="grid grid-cols-2 gap-2 mb-2">
                                        <button
                                            type="button"
                                            onClick={() => {
                                                setHideSubtitles(false);
                                            }}
                                            disabled={isEmbed || !subtitleUrl}
                                            className="p-2 rounded-xl bg-white/10 hover:bg-white/15 text-xs font-semibold text-white transition-all text-center cursor-pointer"
                                        >
                                            {SUB_TXT.refetch}
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => {
                                                subtitleInputRef.current?.click();
                                            }}
                                            disabled={isEmbed}
                                            className="p-2 rounded-xl bg-white/10 hover:bg-white/15 text-xs font-semibold text-white transition-all text-center cursor-pointer"
                                        >
                                            {SUB_TXT.openFile}
                                        </button>
                                    </div>
                                    <input ref={subtitleInputRef} type="file" accept=".vtt" hidden
                                        onChange={(e) => {
                                            void openSubtitle(e.target.files?.[0]);
                                            e.target.value = "";
                                        }}
                                    />
                                    <p className="text-[10px] text-gray-400 text-center">
                                        {SUB_TXT.supported}
                                    </p>
                                </div>
                            </div>
                        )}

                        {settingsTab === "aspect" && (
                            <div className="space-y-4">
                                <div>
                                    <div className="flex justify-between items-center mb-1">
                                        <label className="text-gray-300 font-semibold">
                                            Subtitle Size
                                        </label>
                                        <span className="text-[#C8A2C8] font-bold">
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
                                        className="w-full accent-[#C8A2C8]"
                                    />
                                </div>

                                <div>
                                    <div className="flex justify-between items-center mb-1">
                                        <label className="text-gray-300 font-semibold">
                                            Subtitle Sync
                                        </label>
                                        <span className="text-[#C8A2C8] font-bold">
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
                                        className="w-full accent-[#C8A2C8]"
                                    />
                                </div>

                                <div>
                                    <label className="text-gray-300 font-semibold block mb-2">
                                        Aspect Ratio
                                    </label>
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
                                                        ? "border-[#C8A2C8] bg-lilac-faint text-[#C8A2C8]"
                                                        : "border-white/10 hover:border-white/20 text-gray-300"
                                                }`}
                                            >
                                                <span>{asp.label}</span>
                                                {aspectRatio === asp.id && (
                                                    <Tv className="size-4 text-[#C8A2C8]" />
                                                )}
                                            </button>
                                        ))}
                                    </div>
                                </div>
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

            {/* Bottom Controls Overlay (Only for native video playback to avoid overlapping embed player controls) */}
            {!isEmbed && (
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
                            className="flex-1 h-1.5 rounded-lg appearance-none bg-white/20 accent-[#C8A2C8] cursor-pointer hover:h-2 transition-all"
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
                                className="p-2.5 rounded-full bg-[#C8A2C8] text-gray-950 hover:bg-[#D8B4D8] transition-colors shadow-lg"
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
            )}
        </div>
    );
};
