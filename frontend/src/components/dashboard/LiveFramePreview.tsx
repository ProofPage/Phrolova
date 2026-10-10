import { useEffect, useState } from 'react';
import { CircleAlert, VideoOff } from 'lucide-react';
import { api } from '../../api/client';
import { Button } from '../ui/primitives';

export function LiveFramePreview({ channelKey, isLive, name }: {channelKey: string; isLive: boolean; name: string}) {
    const [attempt, setAttempt] = useState(0);
    const [frame, setFrame] = useState('');
    const [state, setState] = useState<'loading'|'ready'|'error'>('loading');
    useEffect(() => {
        if (!isLive) return;
        const controller = new AbortController();
        let stopped = false;
        let current = '';
        let timer: ReturnType<typeof setTimeout>;
        setFrame(''); setState('loading');
        const refresh = async () => {
            let next = '';
            try {
                const data = await api.getLivePreviewFrame(channelKey, controller.signal);
                if (stopped) return;
                next = URL.createObjectURL(data);
                const image = new Image(); image.src = next;
                await image.decode();
                if (stopped) { URL.revokeObjectURL(next); return; }
                const old = current; current = next;
                setFrame(next); setState('ready');
                if (old) URL.revokeObjectURL(old);
                timer = setTimeout(() => { void refresh(); }, 5000);
            } catch {
                if (next && next !== current) URL.revokeObjectURL(next);
                if (!stopped) setState('error');
            }
        };
        timer = setTimeout(() => { void refresh(); }, 0);
        return () => { stopped = true; controller.abort(); clearTimeout(timer); if (current) URL.revokeObjectURL(current); };
    }, [channelKey, isLive, attempt]);
    return <div className="channel-live-preview" aria-label={`${name} 방송 미리보기`}>
        <div className="channel-preview-stage">
            {isLive && state === 'ready' && frame ? <div className="channel-preview-player"><img src={frame} alt={`${name} 방송 미리보기`} className="size-full object-contain" /></div>
                : <div className="channel-preview-status" role="status" aria-busy={isLive && state === 'loading'}>
                    {!isLive ? <VideoOff className="size-5 text-ink-faint" aria-hidden="true" /> : state === 'loading' ? <span className="size-5 shrink-0 animate-spin rounded-full border-2 border-line-strong border-t-info" aria-hidden="true" /> : <CircleAlert className="size-5 text-ink-faint" aria-hidden="true" />}
                    <span className="channel-preview-message">{!isLive ? '현재 방송 중이 아닙니다.' : state === 'loading' ? '미리보기를 불러오는 중' : '미리보기를 불러올 수 없습니다.'}</span>
                    {isLive && state === 'error' && <Button onClick={() => setAttempt(v => v + 1)}>다시 시도</Button>}
                </div>}
        </div>
    </div>;
}
