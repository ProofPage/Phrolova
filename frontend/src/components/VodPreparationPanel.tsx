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
    const parsedInput = parseVodUrls(text);
    const register = async (input: string) => {
        if (busyRef.current) return;
        const parsed = parseVodUrls(input);
        const errors = parsed.invalid.map(value => `${t('지원하지 않는 주소')}: ${value}`);
        errors.push(...parsed.duplicates.map(value => `${t('중복 링크는 한 번만 추가합니다.')}: ${value}`));
        if (!parsed.urls.length) { setProblems(errors.length ? errors : [t('치지직 다시보기 또는 클립 URL을 입력해 주세요.')]); return; }
        if (parsed.urls.length > 100) { setProblems([t('한 번에 최대 100개의 URL을 등록할 수 있습니다.')]); return; }
        busyRef.current = true; setBusy(true);
        try {
            const result = await api.prepareVods(parsed.urls);
            setProblems([...errors, ...result.results.filter(item => item.error || item.duplicate)
                .map(item => `${item.url}: ${item.duplicate ? t('이미 목록에 있는 영상입니다.') : t('목록에 추가하지 못했습니다. URL과 인증 설정을 확인하세요.')}`)]);
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
        <h3 className="text-sm font-semibold text-ink">{t('다운로드 대기 목록')}</h3>
        <p className="text-xs text-ink-muted" role="status">{t(dragging ? '치지직 다시보기 또는 클립 URL을 여기에 놓으세요.' : '치지직 다시보기 또는 클립 링크를 입력하세요. 여러 링크는 줄바꿈으로 구분할 수 있습니다.')}</p>
        <textarea className="ui-input w-full min-h-20 resize-y" aria-label={t('치지직 다시보기 또는 클립 URL 목록')} value={text} onChange={event => setText(event.target.value)} placeholder={'https://chzzk.naver.com/video/…\nhttps://chzzk.naver.com/clips/…'} disabled={busy} aria-describedby="vod-input-help" />
        <p id="vod-input-help" className="text-xs text-ink-muted" role="status">{t('입력 {count}건 · 목록에 추가한 후 화질을 선택하세요.').replace('{count}', String(parsedInput.count))}</p>
        <div className="flex flex-wrap items-center gap-2">
            <Button icon={Plus} loading={busy} disabled={busy || !text.trim()} onClick={() => void register(text)}>{t('목록에 추가')}</Button>
            <Button icon={Download} variant="primary" disabled={busy || ready.length === 0} onClick={() => void startAll()}>{t('전체 다운로드')} ({ready.length})</Button>
            <span className="text-xs text-ink-muted">{t('동시 다운로드 수는 서버 설정에서 변경할 수 있습니다.')}</span>
        </div>
        {problems.length > 0 && <ul className="text-xs text-warn break-all space-y-1" role="alert">{problems.map((problem, index) => <li key={index}>{problem}</li>)}</ul>}
    </section>;
}
