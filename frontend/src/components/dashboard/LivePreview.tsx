import { translate } from "../../i18n";
import { useEffect, useRef, useState } from "react";
import Hls from "hls.js";
import mpegts from "../../vendor/mpegts.js";
import { CircleAlert, VideoOff } from "lucide-react";
import { api } from "../../api/client";
import { Button } from "../ui/primitives";
import { useLanguage } from "../../contexts/LanguageContext";
import { preferredNativePreviewUrl, preferredPreviewLevel } from "../../utils/livePreviewQuality";

type PreviewProps = { channelKey: string; isLive: boolean; name: string; poster?: string; broadcastState?: string };

export function LivePreview(props: PreviewProps) {
    useLanguage();
    if (props.channelKey.startsWith("tiktok:")) return <MpegtsLivePreview {...props} />;
    return <HlsLivePreview {...props} />;
}

function MpegtsLivePreview({ channelKey, isLive, name, poster, broadcastState }: PreviewProps) {
    const { t } = useLanguage();
    const videoRef = useRef<HTMLVideoElement>(null);
    const [attempt, setAttempt] = useState(0);
    const [state, setState] = useState<"loading" | "ready" | "error">("loading");
    const [message, setMessage] = useState("");

    const getMpegts = () => {
        const direct = (mpegts as any)?.default || mpegts;
        if (direct && typeof direct.createPlayer === "function") return direct;
        const win = typeof window !== "undefined" ? (window as any).mpegts : null;
        const winDirect = win?.default || win;
        if (winDirect && typeof winDirect.createPlayer === "function") return winDirect;
        return null;
    };

    useEffect(() => {
        const video = videoRef.current;
        if (!video || !isLive) return;
        const abort = new AbortController();
        let player: any = null;
        let refreshTimer: ReturnType<typeof setTimeout> | undefined;
        let stopped = false;
        let startupTimer: ReturnType<typeof setTimeout> | undefined;
        let loadingTimer: ReturnType<typeof setTimeout> | undefined;
        let recovering = false;
        let failed = false;

        const detach = () => {
            if (player) {
                try {
                    player.pause();
                    player.unload();
                    player.detachMediaElement();
                    player.destroy();
                } catch {
                    // Ignore disposal errors
                }
                player = null;
            }
        };

        const ready = () => {
            if (stopped || failed) return;
            clearTimeout(loadingTimer);
            recovering = false;
            setState("ready");
            setMessage("");
        };

        const syncLiveEdge = () => {
            if (!video || stopped) return;
            try {
                if (video.buffered && video.buffered.length > 0) {
                    const start = video.buffered.start(0);
                    const end = video.buffered.end(video.buffered.length - 1);
                    if (video.currentTime < start || video.currentTime > end + 1) {
                        video.currentTime = Math.max(start, end - 1.5);
                    }
                    if (video.paused) {
                        video.play().catch(() => {});
                    }
                }
            } catch {
                // Ignore sync errors
            }
        };

        const fail = (reason?: string) => {
            if (stopped) return;
            failed = true;
            clearTimeout(loadingTimer);
            clearTimeout(refreshTimer);
            detach();
            setState("error");
            setMessage(reason || "live.previewUnavailable");
        };

        const recover = () => {
            if (stopped || failed || recovering) return;
            recovering = true;
            clearTimeout(loadingTimer);
            detach();
            setState("loading");
            refreshTimer = setTimeout(() => { void load(); }, 3000);
        };

        const load = async () => {
            recovering = false;
            clearTimeout(loadingTimer);
            loadingTimer = setTimeout(() => {
                if (!stopped) { abort.abort(); fail(); }
            }, 35000);
            try {
                const lib = getMpegts();
                if (!lib || !lib.isSupported()) {
                    fail("live.thisBrowserCannotPlayTheLivePreview");
                    return;
                }
                const { url } = await api.getLivePreview(channelKey, abort.signal);
                if (stopped) return;
                player = lib.createPlayer({
                    type: "flv",
                    isLive: true,
                    url,
                }, {
                    isLive: true,
                    lazyLoad: false,
                    enableWorker: false,
                    enableStashBuffer: false,
                    liveSync: true,
                    liveBufferLatencyChasing: true,
                    liveBufferLatencyMaxLatency: 3.0,
                    liveBufferLatencyMinRemain: 0.5,
                    autoCleanupSourceBuffer: true,
                });
                player.on(lib.Events.ERROR, (type: any, detail: any) => {
                    console.warn("[Phrolova] 틱톡 실시간 플레이어 이벤트:", type, detail);
                    recover();
                });
                player.on(lib.Events.MEDIA_INFO, () => {
                    syncLiveEdge();
                });
                player.attachMediaElement(video);
                player.load();
                video.play().catch(() => {});
            } catch (error) {
                if (stopped || abort.signal.aborted) return;
                const response = (error as { response?: { status?: number; data?: { detail?: string } } }).response;
                if (!response || response.status === 429 || (response.status || 0) >= 500) {
                    recover();
                    return;
                }
                fail(response?.status === 409 ? response?.data?.detail : undefined);
            }
        };

        const onProgress = () => {
            syncLiveEdge();
        };

        const onTimeUpdate = () => {
            if (video.currentTime > 0) ready();
        };

        video.addEventListener("canplay", ready);
        video.addEventListener("playing", ready);
        video.addEventListener("loadeddata", ready);
        video.addEventListener("progress", onProgress);
        video.addEventListener("timeupdate", onTimeUpdate);
        video.addEventListener("error", recover);
        setState("loading");
        setMessage("");
        startupTimer = setTimeout(() => { void load(); }, 0);
        return () => {
            stopped = true;
            abort.abort();
            clearTimeout(startupTimer);
            clearTimeout(refreshTimer);
            clearTimeout(loadingTimer);
            video.removeEventListener("canplay", ready);
            video.removeEventListener("playing", ready);
            video.removeEventListener("loadeddata", ready);
            video.removeEventListener("progress", onProgress);
            video.removeEventListener("timeupdate", onTimeUpdate);
            video.removeEventListener("error", recover);
            detach();
        };
    }, [channelKey, isLive, attempt]);

    return (
        <div className={`channel-live-preview${!isLive ? " is-offline" : ""}`} aria-label={`${name} ${t("live.livePreview")}`}>
            <div className="channel-preview-stage relative size-full overflow-hidden">
                {isLive && (
                    <div className="channel-preview-player absolute inset-0 size-full" style={{ opacity: state === "ready" ? 1 : 0, pointerEvents: state === "ready" ? "auto" : "none" }}>
                        <video ref={videoRef} controls autoPlay muted playsInline poster={poster} className="size-full object-contain" aria-label={`${name} LIVE`} />
                    </div>
                )}
                {(!isLive || state !== "ready") && (
                    <div className="channel-preview-status" role="status" aria-busy={isLive && state === "loading"}>
                        {isLive && state === "loading" ? <span className="size-5 shrink-0 animate-spin rounded-full border-2 border-line-strong border-t-info" aria-hidden="true" /> : isLive ? <CircleAlert className="size-5 text-ink-faint" aria-hidden="true" /> : <VideoOff className="size-5 text-ink-faint" aria-hidden="true" />}
                        <span className="channel-preview-message">{t(!isLive ? broadcastState === "checking" ? translate("live.checkingLiveStatus") : broadcastState === "error" ? translate("live.couldNotCheckLiveStatus") : translate("live.thisChannelIsCurrentlyOffline") : state === "loading" ? translate("live.loadingPreview") : message)}</span>
                        {isLive && state === "error" && <Button type="button" aria-label={t("live.tryAgain")} onClick={() => { setState("loading"); setAttempt(v => v + 1); }}>{t("live.tryAgain")}</Button>}
                    </div>
                )}
            </div>
        </div>
    );
}

function HlsLivePreview({ channelKey, isLive, name, poster, broadcastState }: PreviewProps) {
    const { t } = useLanguage();
    const videoRef = useRef<HTMLVideoElement>(null);
    const [attempt, setAttempt] = useState(0);
    const [state, setState] = useState<"loading" | "ready" | "error">("loading");
    const [message, setMessage] = useState("");

    useEffect(() => {
        const video = videoRef.current;
        if (!video || !isLive) return;
        const abort = new AbortController();
        let hls: Hls | null = null;
        let refreshTimer: ReturnType<typeof setTimeout> | undefined;
        let refreshed = false;
        let stopped = false;
        let startupTimer: ReturnType<typeof setTimeout> | undefined;
        let loadingTimer: ReturnType<typeof setTimeout> | undefined;
        let nativeStarted = false;
        let recovering = false;
        let failed = false;
        let measured = '';

        const measure = () => {
            if (stopped || failed || video.videoWidth <= 0 || video.videoHeight <= 0) return;
            const key = `${video.videoWidth}x${video.videoHeight}`;
            if (key === measured) return;
            measured = key;
            console.info('[Phrolova] 미리보기 실제 해상도', { channel: channelKey, width: video.videoWidth, height: video.videoHeight });
        };

        const detach = () => {
            measured = '';
            hls?.destroy();
            hls = null;
            video.pause();
            video.removeAttribute("src");
            video.load();
        };
        const fail = (text = "live.previewUnavailable") => {
            failed = true;
            clearTimeout(loadingTimer);
            clearTimeout(refreshTimer);
            detach();
            setMessage(text);
            setState("error");
        };
        const play = () => {
            // Rejection is expected when autoplay is blocked; native controls remain usable.
            void video.play().catch(() => {});
        };
        const loaded = () => {
            measure();
            if (!hls && video.seekable.length) {
                video.currentTime = Math.max(video.seekable.start(0), video.seekable.end(video.seekable.length - 1) - 3);
            }
            play();
        };
        const ready = () => {
            if (stopped || failed) return;
            clearTimeout(loadingTimer);
            if (!hls && !nativeStarted && video.seekable.length) {
                nativeStarted = true;
                loaded();
            }
            setState("ready");
            measure();
        };
        const recover = () => {
            if (stopped || failed || recovering) return;
            recovering = true;
            clearTimeout(loadingTimer);
            detach();
            if (!refreshed) {
                refreshed = true;
                setState("loading");
                refreshTimer = setTimeout(() => { void load(); }, 5000);
            } else fail();
        };
        const load = async () => {
            recovering = false;
            loadingTimer = setTimeout(() => {
                if (!stopped) { abort.abort(); fail(); }
            }, 45000);
            try {
                const { url } = await api.getLivePreview(channelKey, abort.signal);
                if (stopped) return;
                if (Hls.isSupported()) {
                    hls = new Hls({
                        autoStartLoad: false,
                        capLevelToPlayerSize: false,
                        lowLatencyMode: true,
                        liveSyncDuration: 6,
                        liveMaxLatencyDuration: 15,
                        maxLiveSyncPlaybackRate: 1.05,
                        backBufferLength: 10,
                        maxBufferLength: 15,
                        maxMaxBufferLength: 30,
                        maxBufferSize: 12 * 1024 * 1024,
                    });
                    hls.on(Hls.Events.MANIFEST_PARSED, () => {
                        if (stopped || failed || !hls) return;
                        const level = preferredPreviewLevel(hls.levels);
                        if (level >= 0) {
                            hls.startLevel = level;
                            hls.autoLevelCapping = level;
                            console.info('[Phrolova] 미리보기 스트림 선택', { channel: channelKey, width: hls.levels[level].width, height: hls.levels[level].height });
                        }
                        hls.startLoad();
                        play();
                    });
                    hls.on(Hls.Events.ERROR, (_, data) => {
                        if (data.fatal) recover();
                    });
                    hls.loadSource(url);
                    hls.attachMedia(video);
                } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
                    const selected = await preferredNativePreviewUrl(url, abort.signal);
                    if (!stopped && !abort.signal.aborted) video.src = selected;
                } else fail("live.thisBrowserCannotPlayTheLivePreview");
            } catch (error) {
                if (stopped || abort.signal.aborted) return;
                const response = (error as { response?: { status?: number; data?: { detail?: string } } }).response;
                // Never display resolver exceptions or signed URLs from upstream errors.
                const detail = response?.data?.detail;
                if (!response || response.status === 429 || (response.status || 0) >= 500) {
                    recover();
                    return;
                }
                fail(response?.status === 409 && (detail === "오프라인" || detail === "이 채널은 영상 미리보기를 지원하지 않습니다.") ? detail : undefined);
            }
        };
        video.addEventListener("loadedmetadata", loaded);
        video.addEventListener("resize", measure);
        video.addEventListener("canplay", ready);
        video.addEventListener("playing", ready);
        video.addEventListener("error", recover);
        setState("loading");
        setMessage("");
        // StrictMode's setup/cleanup probe cancels this before making a resolver request.
        startupTimer = setTimeout(() => { void load(); }, 0);
        return () => {
            stopped = true;
            abort.abort();
            clearTimeout(startupTimer);
            clearTimeout(refreshTimer);
            clearTimeout(loadingTimer);
            video.removeEventListener("loadedmetadata", loaded);
            video.removeEventListener("resize", measure);
            video.removeEventListener("canplay", ready);
            video.removeEventListener("playing", ready);
            video.removeEventListener("error", recover);
            detach();
        };
    }, [channelKey, isLive, attempt]);

    return <div className={`channel-live-preview${!isLive ? " is-offline" : ""}`} aria-label={`${name} ${t("live.livePreview")}`}>
        <div className="channel-preview-stage">
        {isLive && <div className="channel-preview-player" hidden={state !== "ready"}>
            <video ref={videoRef} controls autoPlay muted playsInline poster={poster} className="size-full object-contain" aria-label={`${name} LIVE`} />
        </div>}
        {(!isLive || state !== "ready") && <div className="channel-preview-status" role="status" aria-busy={isLive && state === "loading"}>
            {isLive && state === "loading" ? <span className="size-5 shrink-0 animate-spin rounded-full border-2 border-line-strong border-t-info" aria-hidden="true" /> : isLive ? <CircleAlert className="size-5 text-ink-faint" aria-hidden="true" /> : <VideoOff className="size-5 text-ink-faint" aria-hidden="true" />}
            <span className="channel-preview-message">{t(!isLive ? broadcastState === "checking" ? translate("live.checkingLiveStatus") : broadcastState === "error" ? translate("live.couldNotCheckLiveStatus") : translate("live.thisChannelIsCurrentlyOffline") : state === "loading" ? translate("live.loadingPreview") : message)}</span>
            {isLive && state === "error" && <Button type="button" aria-label={t("live.tryAgain")} onClick={() => { setState("loading"); setAttempt(value => value + 1); }}>{t("live.tryAgain")}</Button>}
        </div>}
        </div>
    </div>;
}
