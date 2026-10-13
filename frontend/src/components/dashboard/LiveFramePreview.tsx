import { useLanguage } from "../../contexts/LanguageContext";
import { localizedStatus } from "../../utils/error";
import { translate } from "../../i18n";
import { useEffect, useState } from 'react';
import { CircleAlert, VideoOff } from 'lucide-react';
import { api } from '../../api/client';
import { Button } from '../ui/primitives';

type Failure = { message?: string; error_code?: string; retryable?: boolean; retry_after?: number };
export function LiveFramePreview({ channelKey, isLive, name }: {channelKey: string; isLive: boolean; name: string}) {
    useLanguage();
    const [attempt, setAttempt] = useState(0);
    const [frame, setFrame] = useState('');
    const [state, setState] = useState<'loading'|'ready'|'error'|'reconnecting'>('loading');
    const [message, setMessage] = useState('');
    const [retryable, setRetryable] = useState(true);
    useEffect(() => {
        if (!isLive) { setFrame(''); return; }
        const controller = new AbortController();
        let stopped = false;
        let current = '';
        let failures = 0;
        let timer: ReturnType<typeof setTimeout>;
        setFrame(''); setState('loading'); setMessage('');
        const refresh = async () => {
            let next = '';
            try {
                const data = await api.getLivePreviewFrame(channelKey, controller.signal, attempt > 0 && failures === 0 && !current);
                if (stopped) return;
                next = URL.createObjectURL(data);
                const image = new Image(); image.src = next;
                await image.decode();
                if (stopped) { URL.revokeObjectURL(next); return; }
                const old = current; current = next; failures = 0;
                setFrame(next); setState('ready'); setMessage('');
                if (old) URL.revokeObjectURL(old);
                timer = setTimeout(() => { void refresh(); }, 5000);
            } catch (error) {
                if (next && next !== current) URL.revokeObjectURL(next);
                if (stopped) return;
                const response = (error as { response?: { status?: number; data?: Blob } }).response;
                let detail: Failure = {};
                if (response?.data instanceof Blob) {
                    try { detail = JSON.parse(await response.data.text()).detail || {}; } catch { /* Safe fallback. */ }
                }
                if (stopped) return;
                failures++;
                const ended = response?.status === 409 || response?.status === 404;
                const canRetry = !ended && detail.retryable !== false;
                setRetryable(canRetry);
                setMessage(ended ? "live.theStreamEndedOrTheChannelWasRemoved" : detail.message || "live.couldNotConnectToThePreviewReconnecting");
                setState(canRetry ? 'reconnecting' : 'error');
                if (canRetry) timer = setTimeout(() => { void refresh(); }, Math.min(60, Math.max(detail.retry_after || 5, 5 * 2 ** Math.min(failures - 1, 3))) * 1000);
            }
        };
        timer = setTimeout(() => { void refresh(); }, 0);
        return () => { stopped = true; controller.abort(); clearTimeout(timer); if (current) URL.revokeObjectURL(current); };
    }, [channelKey, isLive, attempt]);
    return <div className="channel-live-preview" aria-label={translate("live.previewLabel", {name})}>
        <div className="channel-preview-stage">
            {isLive && frame && <div className="channel-preview-player"><img src={frame} alt={translate("live.previewLabel", {name})} /></div>}
            {(!isLive || state !== 'ready') && <div className={`channel-preview-status ${frame ? 'channel-preview-stale' : ''}`} role="status" aria-busy={isLive && state === 'loading'}>
                {!isLive ? <VideoOff className="size-5 text-ink-faint" aria-hidden="true" /> : state === 'loading' ? <span className="size-5 shrink-0 animate-spin rounded-full border-2 border-line-strong border-t-info" aria-hidden="true" /> : <CircleAlert className="size-5 text-ink-faint" aria-hidden="true" />}
                <span className="channel-preview-message">{!isLive ? translate("live.thisChannelIsCurrentlyOffline") : state === 'loading' ? translate("live.loadingPreview") : `${frame ? translate("live.lastAvailableFrame") : ''}${localizedStatus(message, 'errors.preview')}`}</span>
                {isLive && (state === 'error' || state === 'reconnecting') && retryable && <Button onClick={() => setAttempt(v => v + 1)}>{translate("live.tryAgain")}</Button>}
            </div>}
        </div>
    </div>;
}
