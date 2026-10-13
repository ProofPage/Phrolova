import { translate } from "../i18n";
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
        const errors = parsed.invalid.map(value => `${t("download.unsupportedURL")}: ${value}`);
        errors.push(...parsed.duplicates.map(value => `${t("download.duplicateLinksAreAddedOnce")}: ${value}`));
        if (!parsed.urls.length) { setProblems(errors.length ? errors : [t("download.enterAVODOrClipURL")]); return; }
        if (parsed.urls.length > 100) { setProblems([t("download.registerUpTo100URLsAtOnce")]); return; }
        busyRef.current = true; setBusy(true);
        try {
            const result = await api.prepareVods(parsed.urls);
            setProblems([...errors, ...result.results.filter(item => item.error || item.duplicate)
                .map(item => `${item.url}: ${item.duplicate ? t("download.thisVODIsAlreadyRegistered") : t("download.couldNotAddThisItemCheckTheURLAndAuthenticationSettings")}`)]);
            setText(''); await refresh();
        } catch (err) { toast.error(getErrorMessage(err, t("download.couldNotAddTheVideo"))); }
        finally { busyRef.current = false; setBusy(false); }
    };
    const startAll = async () => {
        if (busyRef.current) return; busyRef.current = true; setBusy(true);
        try {
            const result = await api.startPreparedVods(ready.map(task => task.task_id));
            setProblems(result.results.filter(item => item.error).map(item => item.error!));
            await refresh();
        } catch (err) { toast.error(getErrorMessage(err, t("download.theRequestFailed"))); }
        finally { busyRef.current = false; setBusy(false); }
    };
    return <section data-testid="vod-preparation" className={`rounded-[var(--radius-card)] border p-4 space-y-3 ${dragging ? 'border-info bg-info/10' : 'border-line bg-surface-2'}`}
        onDragEnter={event => { if (![...event.dataTransfer.types].some(type => ['text/uri-list', 'text/plain', 'text/html'].includes(type))) return; event.preventDefault(); depth.current++; setDragging(true); }}
        onDragOver={event => { if ([...event.dataTransfer.types].some(type => ['text/uri-list', 'text/plain', 'text/html'].includes(type))) { event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; } }}
        onDragLeave={() => { depth.current = Math.max(0, depth.current - 1); if (!depth.current) setDragging(false); }}
        onDrop={event => { const input = droppedVodText(event.dataTransfer); if (!input) return; event.preventDefault(); event.stopPropagation(); depth.current = 0; setDragging(false); void register(input); }}>
        <h3 className="text-sm font-semibold text-ink">{t("download.vodPreparation")}</h3>
        <p className="text-xs text-ink-muted" role="status">{t(dragging ? translate("download.dropVODURLsHere") : translate("download.dropLinksOrEnterOneURLPerLineChooseQualityAfterRegistration"))}</p>
        <textarea className="ui-input w-full min-h-20 resize-y" aria-label={t("download.vodURLList")} value={text} onChange={event => setText(event.target.value)} placeholder={'https://chzzk.naver.com/video/…\nhttps://chzzk.naver.com/clips/…'} disabled={busy} aria-describedby="vod-input-help" />
        <p id="vod-input-help" className="text-xs text-ink-muted" role="status">{t("download.countEntriesChooseQualityAfterAdding", {count: parsedInput.count})}</p>
        <div className="flex flex-wrap items-center gap-2">
            <Button icon={Plus} loading={busy} disabled={busy || !text.trim()} onClick={() => void register(text)}>{t("download.addToList")}</Button>
            <Button icon={Download} variant="primary" disabled={busy || ready.length === 0} onClick={() => void startAll()}>{t("download.startAllDownloads")} ({ready.length})</Button>
            <span className="text-xs text-ink-muted">{t("download.concurrentDownloadsFollowServerSettings")}</span>
        </div>
        {problems.length > 0 && <ul className="text-xs text-warn break-all space-y-1" role="alert">{problems.map((problem, index) => <li key={index}>{problem}</li>)}</ul>}
    </section>;
}
