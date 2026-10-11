import { useEffect, useState } from 'react';
import { CircleAlert, VideoOff } from 'lucide-react';
import { api } from '../../api/client';
import { Button } from '../ui/primitives';

type Failure = { message?: string; error_code?: string; retryable?: boolean; retry_after?: number };
export function LiveFramePreview({ channelKey, isLive, name }: {channelKey: string; isLive: boolean; name: string}) {
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
                setMessage(ended ? '방송이 종료되었거나 채널이 제거되었습니다.' : detail.message || '미리보기 연결에 실패했습니다. 다시 연결합니다.');
                setState(canRetry ? 'reconnecting' : 'error');
                if (canRetry) timer = setTimeout(() => { void refresh(); }, Math.min(60, Math.max(detail.retry_after || 5, 5 * 2 ** Math.min(failures - 1, 3))) * 1000);
            }
        };
        timer = setTimeout(() => { void refresh(); }, 0);
        return () => { stopped = true; controller.abort(); clearTimeout(timer); if (current) URL.revokeObjectURL(current); };
    }, [channelKey, isLive, attempt]);
    return <div className="channel-live-preview" aria-label={`${name} 방송 미리보기`}>
        <div className="channel-preview-stage">
            {isLive && frame && <div className="channel-preview-player"><img src={frame} alt={`${name} 방송 미리보기`} /></div>}
            {(!isLive || state !== 'ready') && <div className={`channel-preview-status ${frame ? 'channel-preview-stale' : ''}`} role="status" aria-busy={isLive && state === 'loading'}>
                {!isLive ? <VideoOff className="size-5 text-ink-faint" aria-hidden="true" /> : state === 'loading' ? <span className="size-5 shrink-0 animate-spin rounded-full border-2 border-line-strong border-t-info" aria-hidden="true" /> : <CircleAlert className="size-5 text-ink-faint" aria-hidden="true" />}
                <span className="channel-preview-message">{!isLive ? '현재 방송 중이 아닙니다.' : state === 'loading' ? '미리보기를 불러오는 중' : `${frame ? '마지막 정상 화면 · ' : ''}${message}`}</span>
                {isLive && (state === 'error' || state === 'reconnecting') && retryable && <Button onClick={() => setAttempt(v => v + 1)}>다시 시도</Button>}
            </div>}
        </div>
    </div>;
}
