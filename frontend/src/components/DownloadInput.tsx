import { translate, translatePlural } from "../i18n";
import { useEffect, useMemo, useRef, useState } from 'react';
import { Download, Plus } from 'lucide-react';
import { api, type VodTask } from '../api/client';
import { useVod } from '../contexts/VodContext';
import { Button } from './ui/primitives';
import { DownloadSourceSelect } from './DownloadSourceSelect';
import { useLanguage } from '../contexts/LanguageContext';
import { getErrorMessage } from '../utils/error';
import { normalizeDownloadInput, parseDownloadInputs, type DownloadSource } from '../utils/downloads';
import { droppedVodText } from '../utils/vodUrls';

type InputProblem = { message: string; url?: string };
const defaults: { id: DownloadSource; label: string }[] = [{ id: 'chzzk', label: "platform.chzzk" }, { id: 'youtube', label: "platform.youtube" }, { id: 'external', label: "download.externalVideo" }];
const supportedIds: DownloadSource[] = ['chzzk', 'youtube', 'soop', 'cime', 'kick', 'external'];

export function DownloadInput({ tasks }: { tasks: VodTask[] }) {
    const { t } = useLanguage();
    const { addTask, refreshTasks } = useVod();
    const [sources, setSources] = useState(defaults);
    const [source, setSource] = useState<DownloadSource>('chzzk');
    const [text, setText] = useState('');
    const [busy, setBusy] = useState<'queue' | 'start' | null>(null);
    const busyRef = useRef(false);
    const [problems, setProblems] = useState<InputProblem[]>([]);
    const [result, setResult] = useState<{ key: string; count: number } | null>(null);
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
        const errors: InputProblem[] = parsed.invalid.map(url => ({message: "download.unsupportedURL", url}));
        errors.push(...parsed.duplicates.map(url => ({message: "download.duplicateLinksAreAddedOnce", url})));
        if (!parsed.items.length) { setProblems(errors); return; }
        if (parsed.items.length > 100) { setProblems([{message: "download.registerUpTo100URLsAtOnce"}]); return; }
        busyRef.current = true; setBusy(mode); setResult(null);
        let successful = 0;
        const failedInputs: string[] = [...parsed.invalid];
        try {
            const existing = new Set(tasks.map(task => normalizeDownloadInput(task.url, source)?.url ?? task.url));
            const fresh = parsed.items.filter(item => {
                if (!existing.has(item.url)) return true;
                errors.push({message: "download.thisVODIsAlreadyRegistered", url: item.url}); return false;
            });
            if (mode === 'queue' && fresh.length) {
                const response = await api.prepareVods(fresh.map(item => item.url), fresh.every(item => item.source === source) ? source : undefined);
                for (const item of response.results) {
                    if (item.error) { errors.push({message: "download.couldNotAddThisItemCheckTheURLAndAuthenticationSettings", url: item.url}); failedInputs.push(item.url); }
                    else if (item.duplicate) errors.push({message: "download.thisVODIsAlreadyRegistered", url: item.url});
                    else successful++;
                }
            } else if (mode === 'start') {
                // Serialize admission, not downloads; engine keeps the existing concurrency limit.
                for (const item of fresh) {
                    try { await addTask(item.url); successful++; }
                    catch (error) { failedInputs.push(item.url); errors.push({message: getErrorMessage(error, "download.couldNotAddTheVideo"), url: item.url}); }
                }
            }
            await refreshTasks();
            setText(failedInputs.join('\n'));
            setResult({ key: successful ? mode === 'queue' ? "download.addedLinks" : "download.startedLinks" : "download.noNewLinksAdded", count: successful });
        } catch (error) { errors.push({message: getErrorMessage(error, "download.couldNotAddTheVideo")}); }
        finally { setProblems(errors); busyRef.current = false; setBusy(null); }
    };
    return <div className={`download-input-card media-add-form ${dragging ? 'is-dragging' : ''}`} data-testid="vod-preparation"
        onDragOver={event => { if (event.dataTransfer.types.some(type => ['text/uri-list', 'text/plain', 'text/html'].includes(type))) { event.preventDefault(); setDragging(true); } }}
        onDragLeave={() => setDragging(false)} onDrop={event => { const input = droppedVodText(event.dataTransfer); setDragging(false); if (input && !busyRef.current) { event.preventDefault(); setText(input); setProblems([]); setResult(null); } }}>
        <div className="download-input-fields">
            <DownloadSourceSelect sources={sources} value={source} disabled={!!busy} onChange={value => { setSource(value); setProblems([]); setResult(null); }} />
            <textarea id="vod-url" className="ui-input min-w-0 w-full resize-y" rows={Math.min(4, Math.max(1, text.split('\n').length))} aria-label={t("download.downloadURLList")} aria-describedby="download-input-help" aria-invalid={parsed.invalid.length > 0} value={text} disabled={!!busy}
                onChange={event => { setText(event.target.value); setProblems([]); setResult(null); }}
                placeholder={source === 'chzzk' ? 'https://chzzk.naver.com/video/...' : source === 'youtube' ? 'https://www.youtube.com/watch?v=...' : source === 'soop' ? 'https://vod.sooplive.com/player/...' : source === 'cime' ? 'https://ci.me/@channel/vods/...' : source === 'kick' ? 'https://kick.com/channel/videos/...' : 'https://...'} />
        </div>
        <p id="download-input-help" className="text-xs text-ink-muted">{t("download.enterVODOrClipLinksSeparateMultipleLinksWithLineBreaks")}</p>
        {(busy || parsed.count > 0) && <div className="download-input-summary text-xs text-ink-faint" role="status" aria-live="polite">
            {busy ? t(busy === 'queue' ? translate("download.addingURLsToTheList") : translate("download.requestingDownloadStart")) : parsed.count ? t("download.inputSummary", {count: parsed.count, valid: parsed.items.length}) : t("download.enterLinksToAddThemToTheListOrDownloadImmediately")}
            {parsed.invalid.length > 0 && <span className="text-warn"> · {t("download.unsupportedCount", {count: parsed.invalid.length})}</span>}
            {parsed.duplicates.length > 0 && <span> · {t("download.duplicateCount", {count: parsed.duplicates.length})}</span>}
        </div>}
        {hasCollection && <p className="text-xs text-ink-muted">{t("download.useStartDownloadForChannelLinksDownloadsBeginAsVideosAreFound")}</p>}
        <div className="download-input-buttons">
            <Button className="download-queue-button" icon={Plus} loading={busy === 'queue'} disabled={!!busy || !parsed.items.length || hasCollection} onClick={() => void submit('queue')} title={hasCollection ? t("download.useStartDownloadForChannelLinks") : undefined}>{t("download.addToList")}</Button>
            <Button icon={Download} variant="primary" loading={busy === 'start'} disabled={!!busy || !parsed.items.length} onClick={() => void submit('start')}>{t("download.startDownload")}</Button>
        </div>
        {result && <p role="status" className="text-xs text-ok">{result.count ? translatePlural(result.key, result.count) : t(result.key)}</p>}
        {problems.length > 0 && <ul role="alert" className="text-xs text-warn break-words space-y-1">{problems.map((problem, index) => <li key={index}>{problem.url && `${problem.url}: `}{t(problem.message)}</li>)}</ul>}
    </div>;
}
