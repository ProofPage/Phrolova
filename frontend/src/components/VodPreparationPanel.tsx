import { useRef, useState } from 'react';
import { Download, Plus } from 'lucide-react';
import { api, VodTask } from '../api/client';
import { Button } from './ui/primitives';
import { useLanguage } from '../contexts/LanguageContext';
import { useToast } from './ui/Toast';
import { droppedVodText, parseVodUrls } from '../utils/vodUrls';
import { getErrorMessage } from '../utils/error';

export function VodPreparationPanel({ tasks, refresh }: { tasks: VodTask[]; refresh: () => Promise<void> }) {
    const { t } = useLanguage(); const toast = useToast();
    const [text, setText] = useState(''); const [busy, setBusy] = useState(false);
    const [dragging, setDragging] = useState(false); const depth = useRef(0); const busyRef = useRef(false);
    const [problems, setProblems] = useState<string[]>([]);
    const ready = tasks.filter(task => task.prepared && task.state === 'idle' && task.phase === 'ready');
    const register = async (input: string) => {
        if (busyRef.current) return;
        const parsed = parseVodUrls(input);
        const errors = parsed.invalid.map(value => `${t('지원하지 않는 주소')}: ${value}`);
        if (!parsed.urls.length) { setProblems(errors.length ? errors : [t('CHZZK 다시보기 주소를 입력해 주세요.')]); return; }
        if (parsed.urls.length > 100) { setProblems([t('한 번에 최대 100개의 URL을 등록할 수 있습니다.')]); return; }
        busyRef.current = true; setBusy(true);
        try {
            const result = await api.prepareVods(parsed.urls);
            setProblems([...errors, ...result.results.filter(item => item.error || item.duplicate)
                .map(item => `${item.url}: ${item.duplicate ? t('이미 등록된 VOD입니다.') : item.error}`)]);
            setText(''); await refresh();
        } catch (err) { toast.error(getErrorMessage(err, t('영상 추가에 실패했습니다.'))); }
        finally { busyRef.current = false; setBusy(false); }
    };
    const startAll = async () => {
        if (busyRef.current) return; busyRef.current = true; setBusy(true);
        try {
            const result = await api.startPreparedVods(ready.map(task => task.task_id));
            setProblems(result.results.filter(item => item.error).map(item => item.error!));
            await refresh();
        } catch (err) { toast.error(getErrorMessage(err, t('요청에 실패했습니다.'))); }
        finally { busyRef.current = false; setBusy(false); }
    };
    return <section data-testid="vod-preparation" className={`rounded-[var(--radius-card)] border p-4 space-y-3 ${dragging ? 'border-info bg-info/10' : 'border-line bg-surface-2'}`}
        onDragEnter={event => { if (![...event.dataTransfer.types].some(type => ['text/uri-list', 'text/plain', 'text/html'].includes(type))) return; event.preventDefault(); depth.current++; setDragging(true); }}
        onDragOver={event => { if ([...event.dataTransfer.types].some(type => ['text/uri-list', 'text/plain', 'text/html'].includes(type))) { event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; } }}
        onDragLeave={() => { depth.current = Math.max(0, depth.current - 1); if (!depth.current) setDragging(false); }}
        onDrop={event => { const input = droppedVodText(event.dataTransfer); if (!input) return; event.preventDefault(); event.stopPropagation(); depth.current = 0; setDragging(false); void register(input); }}>
        <h3 className="text-sm font-semibold text-ink">{t('CHZZK VOD 준비 목록')}</h3>
        <p className="text-xs text-ink-muted" role="status">{t(dragging ? 'CHZZK 다시보기 URL을 여기에 놓으세요.' : '링크를 놓거나 여러 URL을 줄바꿈으로 입력하세요. 등록 후 화질을 선택할 수 있습니다.')}</p>
        <textarea className="ui-input w-full min-h-20 resize-y" aria-label={t('CHZZK 다시보기 URL 목록')} value={text} onChange={event => setText(event.target.value)} placeholder="https://chzzk.naver.com/video/…" disabled={busy} />
        <div className="flex flex-wrap items-center gap-2">
            <Button icon={Plus} loading={busy} disabled={!text.trim()} onClick={() => void register(text)}>{t('VOD 등록')}</Button>
            <Button icon={Download} variant="primary" disabled={busy || ready.length === 0} onClick={() => void startAll()}>{t('전체 다운로드 시작')} ({ready.length})</Button>
            <span className="text-xs text-ink-muted">{t('동시 다운로드 제한은 서버 설정을 따릅니다.')}</span>
        </div>
        {problems.length > 0 && <ul className="text-xs text-warn break-all space-y-1" role="alert">{problems.map((problem, index) => <li key={index}>{problem}</li>)}</ul>}
    </section>;
}
