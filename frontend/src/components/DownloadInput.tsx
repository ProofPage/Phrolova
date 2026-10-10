import { useEffect, useMemo, useRef, useState } from 'react';
import { Download, Plus } from 'lucide-react';
import { api, type VodTask } from '../api/client';
import { useVod } from '../contexts/VodContext';
import { Button, Card } from './ui/primitives';
import { DownloadSourceSelect } from './DownloadSourceSelect';
import { useLanguage } from '../contexts/LanguageContext';
import { getErrorMessage } from '../utils/error';
import { normalizeDownloadInput, parseDownloadInputs, type DownloadSource } from '../utils/downloads';
import { droppedVodText } from '../utils/vodUrls';

const defaults: { id: DownloadSource; label: string }[] = [{ id: 'chzzk', label: '치지직' }, { id: 'youtube', label: '유튜브' }, { id: 'external', label: '외부 영상' }];
const supportedIds: DownloadSource[] = ['chzzk', 'youtube', 'soop', 'cime', 'external'];

export function DownloadInput({ tasks }: { tasks: VodTask[] }) {
    const { t } = useLanguage();
    const { addTask, refreshTasks } = useVod();
    const [sources, setSources] = useState(defaults);
    const [source, setSource] = useState<DownloadSource>('chzzk');
    const [text, setText] = useState('');
    const [busy, setBusy] = useState<'queue' | 'start' | null>(null);
    const busyRef = useRef(false);
    const [problems, setProblems] = useState<string[]>([]);
    const [result, setResult] = useState('');
    const [dragging, setDragging] = useState(false);
    const parsed = useMemo(() => parseDownloadInputs(text, source), [text, source]);
    const hasCollection = parsed.items.some(item => item.collection);
    useEffect(() => {
        api.getVodCapabilities().then(data => {
            const supported = data.sources?.filter(item => supportedIds.includes(item.id));
            if (supported?.length) { setSources(supported); setSource(current => supported.some(item => item.id === current) ? current : supported[0].id); }
        }).catch(() => {});
    }, []);
    const submit = async (mode: 'queue' | 'start') => {
        if (busyRef.current) return;
        const errors = parsed.invalid.map(value => `${t('지원하지 않는 주소')}: ${value}`);
        errors.push(...parsed.duplicates.map(value => `${t('중복 링크는 한 번만 추가합니다.')}: ${value}`));
        if (!parsed.items.length) { setProblems(errors); return; }
        if (parsed.items.length > 100) { setProblems([t('한 번에 최대 100개의 URL을 등록할 수 있습니다.')]); return; }
        busyRef.current = true; setBusy(mode); setResult('');
        let successful = 0;
        const failedInputs: string[] = [...parsed.invalid];
        try {
            const existing = new Set(tasks.map(task => normalizeDownloadInput(task.url, source)?.url ?? task.url));
            const fresh = parsed.items.filter(item => {
                if (!existing.has(item.url)) return true;
                errors.push(`${item.url}: ${t('이미 목록에 있는 영상입니다.')}`); return false;
            });
            if (mode === 'queue' && fresh.length) {
                const response = await api.prepareVods(fresh.map(item => item.url), fresh.every(item => item.source === source) ? source : undefined);
                for (const item of response.results) {
                    if (item.error) { errors.push(`${item.url}: ${t('목록에 추가하지 못했습니다. URL과 인증 설정을 확인하세요.')}`); failedInputs.push(item.url); }
                    else if (item.duplicate) errors.push(`${item.url}: ${t('이미 목록에 있는 영상입니다.')}`);
                    else successful++;
                }
            } else if (mode === 'start') {
                // Serialize admission, not downloads; engine keeps the existing concurrency limit.
                for (const item of fresh) {
                    try { await addTask(item.url); successful++; }
                    catch (error) { failedInputs.push(item.url); errors.push(`${item.url}: ${getErrorMessage(error, t('영상 추가에 실패했습니다.'))}`); }
                }
            }
            await refreshTasks();
            setText(failedInputs.join('\n'));
            setResult(successful ? `${successful}${t('개 링크를')} ${t(mode === 'queue' ? '목록에 추가했습니다.' : '다운로드 시작했습니다.')}` : t('새로 추가한 링크가 없습니다.'));
        } catch (error) { errors.push(getErrorMessage(error, t('영상 추가에 실패했습니다.'))); }
        finally { setProblems(errors); busyRef.current = false; setBusy(null); }
    };
    return <Card padded={false} className={`download-input-card ${dragging ? 'is-dragging' : ''}`} data-testid="vod-preparation"
        onDragOver={event => { if (event.dataTransfer.types.some(type => ['text/uri-list', 'text/plain', 'text/html'].includes(type))) { event.preventDefault(); setDragging(true); } }}
        onDragLeave={() => setDragging(false)} onDrop={event => { const input = droppedVodText(event.dataTransfer); setDragging(false); if (input && !busyRef.current) { event.preventDefault(); setText(input); setProblems([]); setResult(''); } }}>
        <div className="download-input-fields">
            <DownloadSourceSelect sources={sources} value={source} disabled={!!busy} onChange={value => { setSource(value); setProblems([]); setResult(''); }} />
            <textarea id="vod-url" className="ui-input min-w-0 w-full resize-y" rows={Math.min(4, Math.max(1, text.split('\n').length))} aria-label={t('다운로드 URL 목록')} aria-describedby="download-input-help" aria-invalid={parsed.invalid.length > 0} value={text} disabled={!!busy}
                onChange={event => { setText(event.target.value); setProblems([]); setResult(''); }}
                placeholder={source === 'chzzk' ? 'https://chzzk.naver.com/video/...' : source === 'youtube' ? 'https://www.youtube.com/watch?v=...' : source === 'soop' ? 'https://vod.sooplive.com/player/...' : source === 'cime' ? 'https://ci.me/@channel/vods/...' : 'https://...'} />
        </div>
        <p id="download-input-help" className="text-xs text-ink-muted">{t('다시보기 또는 클립 링크를 입력하세요. 여러 링크는 줄바꿈으로 구분할 수 있습니다.')}</p>
        {(busy || parsed.count > 0) && <div className="download-input-summary text-xs text-ink-faint" role="status" aria-live="polite">
            {busy ? t(busy === 'queue' ? 'URL을 목록에 등록하고 있습니다.' : '다운로드 시작을 요청하고 있습니다.') : parsed.count ? `${t('입력한 링크')} ${parsed.count}${t('개')} · ${t('정상 링크')} ${parsed.items.length}${t('개')}` : t('링크를 입력하면 목록에 추가하거나 바로 다운로드할 수 있습니다.')}
            {parsed.invalid.length > 0 && <span className="text-warn"> · {t('지원하지 않는 주소')} {parsed.invalid.length}{t('개')}</span>}
            {parsed.duplicates.length > 0 && <span> · {t('중복 링크')} {parsed.duplicates.length}{t('개')}</span>}
        </div>}
        {hasCollection && <p className="text-xs text-ink-muted">{t('채널 링크는 다운로드 시작으로 추가하세요. 찾은 영상부터 다운로드합니다.')}</p>}
        <div className="download-input-buttons">
            <Button className="download-queue-button" icon={Plus} loading={busy === 'queue'} disabled={!!busy || !parsed.items.length || hasCollection} onClick={() => void submit('queue')} title={hasCollection ? t('채널 링크는 다운로드 시작으로 추가하세요.') : undefined}>{t('목록에 추가')}</Button>
            <Button icon={Download} variant="primary" loading={busy === 'start'} disabled={!!busy || !parsed.items.length} onClick={() => void submit('start')}>{t('다운로드 시작')}</Button>
        </div>
        {result && <p role="status" className="text-xs text-ok">{result}</p>}
        {problems.length > 0 && <ul role="alert" className="text-xs text-warn break-words space-y-1">{problems.map((problem, index) => <li key={index}>{problem}</li>)}</ul>}
    </Card>;
}
