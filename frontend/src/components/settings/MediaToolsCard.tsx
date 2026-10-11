import { useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { api } from '../../api/client';
import { Button, Card, CardHeader } from '../ui/primitives';

export function MediaToolsCard() {
    const [attempt, setAttempt] = useState(0);
    const [tools, setTools] = useState<Awaited<ReturnType<typeof api.getMediaTools>>>({});
    const [busy, setBusy] = useState(true);
    const [error, setError] = useState(false);
    useEffect(() => {
        const controller = new AbortController();
        setBusy(true); setError(false);
        void api.getMediaTools(controller.signal).then(data => {
            if (!controller.signal.aborted) setTools(data);
        }).catch(() => { if (!controller.signal.aborted) setError(true); })
          .finally(() => { if (!controller.signal.aborted) setBusy(false); });
        return () => controller.abort();
    }, [attempt]);
    return <Card className="space-y-3" aria-busy={busy}>
        <CardHeader title="미디어 도구" />
        <dl className="grid gap-3 text-xs">
            {['ffmpeg', 'ffprobe'].map(name => <div key={name} className="min-w-0 space-y-1">
                <dt className="font-medium text-ink">{name === 'ffmpeg' ? 'FFmpeg' : 'FFprobe'}</dt>
                <dd className={tools[name]?.available ? 'text-ok break-all' : 'text-warn break-words'}>
                    {busy ? '실행 확인 중' : error ? '도구 상태를 불러오지 못했습니다.' : tools[name]?.available ? `정상 · ${tools[name].path}` : tools[name]?.message || '도구 상태를 확인할 수 없습니다.'}
                </dd>
            </div>)}
        </dl>
        <p className="text-xs text-ink-muted break-words">Windows: 프로그램 옆 bin 폴더에 ffmpeg.exe와 ffprobe.exe를 함께 설치하세요. Linux: ffmpeg 패키지를 설치하세요. Termux Native: pkg install ffmpeg. 사용자 경로는 FFMPEG_PATH·FFPROBE_PATH로 지정할 수 있습니다. 설치 후 다시 검사하고 녹화 파일 처리를 재시도하세요.</p>
        <Button icon={RefreshCw} disabled={busy} onClick={() => setAttempt(value => value + 1)}>도구 다시 검사</Button>
    </Card>;
}
