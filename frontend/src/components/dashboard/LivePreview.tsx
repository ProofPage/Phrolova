import { useEffect, useRef, useState } from "react";
import Hls from "hls.js";
import { api } from "../../api/client";
import { Button } from "../ui/primitives";
import { useLanguage } from "../../contexts/LanguageContext";

export function LivePreview({ channelKey, isLive, name }: { channelKey: string; isLive: boolean; name: string }) {
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

        const detach = () => {
            hls?.destroy();
            hls = null;
            video.pause();
            video.removeAttribute("src");
            video.load();
        };
        const fail = (text = "미리보기를 불러올 수 없습니다.") => {
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
                video.muted = true;
                if (Hls.isSupported()) {
                    hls = new Hls({
                        lowLatencyMode: true,
                        liveSyncDuration: 6,
                        liveMaxLatencyDuration: 15,
                        maxLiveSyncPlaybackRate: 1.05,
                        backBufferLength: 10,
                        maxBufferLength: 15,
                    });
                    hls.on(Hls.Events.MANIFEST_PARSED, play);
                    hls.on(Hls.Events.ERROR, (_, data) => {
                        if (data.fatal) recover();
                    });
                    hls.loadSource(url);
                    hls.attachMedia(video);
                } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
                    video.src = url;
                } else fail("이 브라우저에서는 라이브 미리보기를 재생할 수 없습니다.");
            } catch (error) {
                if (stopped || abort.signal.aborted) return;
                const response = (error as { response?: { status?: number; data?: { detail?: string } } }).response;
                // Never display resolver exceptions or signed URLs from upstream errors.
                const detail = response?.data?.detail;
                fail(response?.status === 409 && (detail === "오프라인" || detail === "이 채널은 영상 미리보기를 지원하지 않습니다.") ? detail : undefined);
            }
        };
        video.addEventListener("loadedmetadata", loaded);
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
            video.removeEventListener("canplay", ready);
            video.removeEventListener("playing", ready);
            video.removeEventListener("error", recover);
            detach();
        };
    }, [channelKey, isLive, attempt]);

    return <div className="relative mx-auto aspect-video w-full min-w-0 overflow-hidden bg-surface-0" aria-label={`${name} ${t("방송 미리보기")}`}>
        {isLive && <video ref={videoRef} controls autoPlay muted playsInline className="size-full object-contain" aria-label={`${name} LIVE`} />}
        {(!isLive || state !== "ready") && <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 px-4 text-center text-xs text-ink-muted" role="status">
            {isLive && state === "loading" && <span className="size-6 animate-spin rounded-full border-2 border-line-strong border-t-info" aria-hidden="true" />}
            <span>{t(!isLive ? "오프라인" : state === "loading" ? "미리보기를 불러오는 중" : message)}</span>
            {isLive && state === "error" && <Button onClick={() => setAttempt(value => value + 1)}>{t("다시 시도")}</Button>}
        </div>}
    </div>;
}
