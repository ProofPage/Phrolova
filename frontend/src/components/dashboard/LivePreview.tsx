import { useEffect, useRef, useState } from "react";
import Hls from "hls.js";
import { CircleAlert, VideoOff } from "lucide-react";
import { api } from "../../api/client";
import { Button } from "../ui/primitives";
import { useLanguage } from "../../contexts/LanguageContext";
import { preferredNativePreviewUrl, preferredPreviewLevel } from "../../utils/livePreviewQuality";
import { LiveFramePreview } from './LiveFramePreview';

type PreviewProps = { channelKey: string; isLive: boolean; name: string; poster?: string };
export function LivePreview(props: PreviewProps) {
    return /^(soop|cime):/.test(props.channelKey) ? <LiveFramePreview {...props} /> : <HlsLivePreview {...props} />;
}
function HlsLivePreview({ channelKey, isLive, name, poster }: PreviewProps) {
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
                video.muted = true;
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
                            hls.loadLevel = level;
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

    return <div className="channel-live-preview" aria-label={`${name} ${t("방송 미리보기")}`}>
        <div className="channel-preview-stage">
        {isLive && <div className="channel-preview-player" hidden={state !== "ready"}>
            <video ref={videoRef} controls autoPlay muted playsInline poster={poster} className="size-full object-contain" aria-label={`${name} LIVE`} />
        </div>}
        {(!isLive || state !== "ready") && <div className="channel-preview-status" role="status" aria-busy={isLive && state === "loading"}>
            {isLive && state === "loading" ? <span className="size-5 shrink-0 animate-spin rounded-full border-2 border-line-strong border-t-info" aria-hidden="true" /> : isLive ? <CircleAlert className="size-5 text-ink-faint" aria-hidden="true" /> : <VideoOff className="size-5 text-ink-faint" aria-hidden="true" />}
            <span className="channel-preview-message">{t(!isLive ? "현재 방송 중이 아닙니다." : state === "loading" ? "미리보기를 불러오는 중" : message)}</span>
            {isLive && state === "error" && <Button type="button" aria-label={t("다시 시도")} onClick={() => { setState("loading"); setAttempt(value => value + 1); }}>{t("다시 시도")}</Button>}
        </div>}
        </div>
    </div>;
}
