import { useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { api } from '../../api/client';
import { Button, Card, CardHeader } from '../ui/primitives';

export function MediaToolsCard() {
    const [attempt, setAttempt] = useState(0);
    const [tools, setTools] = useState<Awaited<ReturnType<typeof api.getMediaTools>>>({});
    const [busy, setBusy] = useState(true);
    const [error, setError] = useState(false);
    const needsSetup = !busy && !error && ['ffmpeg', 'ffprobe'].some(name => tools[name]?.available === false);
    useEffect(() => {
        const controller = new AbortController();
        setBusy(true); setError(false);
        void api.getMediaTools(controller.signal).then(data => {
            if (!controller.signal.aborted) setTools(data);
        }).catch(() => { if (!controller.signal.aborted) setError(true); })
          .finally(() => { if (!controller.signal.aborted) setBusy(false); });
        return () => controller.abort();
    }, [attempt]);
    return <Card className="space-y-4" aria-busy={busy}>
        <CardHeader title="미디어 도구" />
        <dl className="grid gap-4 text-xs">
            {['ffmpeg', 'ffprobe'].map(name => <div key={name} className="grid min-w-0 gap-2 sm:grid-cols-[80px_minmax(0,1fr)] sm:gap-3">
                <dt className="font-medium leading-5 text-ink">{name === 'ffmpeg' ? 'FFmpeg' : 'FFprobe'}</dt>
                <dd className="min-w-0 space-y-1.5">
                    <span className={`inline-flex items-center gap-1.5 leading-5 ${busy || error ? 'text-ink-muted' : tools[name]?.available ? 'text-ok' : 'text-warn'}`}>
                        {!busy && !error && tools[name]?.available && <span className="size-1.5 rounded-full bg-current" aria-hidden="true" />}
                        {busy ? '실행 확인 중' : error ? '도구 상태를 불러오지 못했습니다.' : tools[name]?.available ? '정상' : tools[name]?.message || '도구 상태를 확인할 수 없습니다.'}
                    </span>
                    {!busy && !error && tools[name]?.available && tools[name]?.path && <p className="font-mono leading-relaxed text-ink-muted [overflow-wrap:anywhere]" title={tools[name].path}>{tools[name].path}</p>}
                </dd>
            </div>)}
        </dl>
        {needsSetup && <details className="text-xs text-ink-muted">
            <summary className="cursor-pointer rounded-[var(--radius-control)] text-ink focus-visible:outline-2 focus-visible:outline-info">설치 및 경로 설정 안내</summary>
            <ul className="mt-3 space-y-2 leading-relaxed [overflow-wrap:anywhere]">
                <li>Windows: 프로그램 옆 bin 폴더에 ffmpeg.exe와 ffprobe.exe를 함께 설치하세요. WinGet 또는 PATH로 설치한 도구도 자동 감지합니다.</li>
                <li>Linux: ffmpeg 패키지를 설치하세요. Termux Native: pkg install ffmpeg.</li>
                <li>사용자 경로는 FFMPEG_PATH·FFPROBE_PATH로 지정할 수 있습니다. 설치 후 도구를 다시 검사하고 녹화 파일 처리를 재시도하세요.</li>
            </ul>
        </details>}
        <Button icon={RefreshCw} disabled={busy} onClick={() => setAttempt(value => value + 1)}>도구 다시 검사</Button>
    </Card>;
}
