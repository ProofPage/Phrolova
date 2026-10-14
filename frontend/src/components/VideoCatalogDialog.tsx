import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { api, type VideoEpisode } from '../api/client';
import { useLanguage } from '../contexts/LanguageContext';
import { getErrorMessage } from '../utils/error';
import { isEpisodeSource } from '../utils/episodeSites';
import { parseDownloadInputs } from '../utils/downloads';
import { Button } from './ui/primitives';
import './video-catalog.css';

type Entry = ReturnType<typeof parseDownloadInputs>['items'][number];
export function VideoCatalogDialog({ inputs, start, onClose, onConfirm }: {
    inputs: Entry[]; start:boolean; onClose: () => void; onConfirm: (urls:string[]) => void;
}) {
    const {t} = useLanguage();
    const dialog = useRef<HTMLDialogElement>(null);
    const [rows,setRows] = useState<VideoEpisode[]>([]);
    const [selected,setSelected] = useState(new Set<string>());
    const [title,setTitle] = useState('');
    const [incomplete,setIncomplete] = useState(false);
    const [loading,setLoading] = useState(true);
    const [error,setError] = useState('');
    const [attempt,setAttempt] = useState(0);
    const [query,setQuery] = useState('');
    const [page,setPage] = useState(0);
    useEffect(()=> { dialog.current?.showModal(); },[]);
    useEffect(()=> {
        const controller = new AbortController();
        setLoading(true); setError('');
        void (async()=> {
            const results: VideoEpisode[]=[]; const titles:string[]=[]; let partial=false;
            try {
                for (const item of inputs) {
                    if (item.collection && isEpisodeSource(item.source)) {
                        const data = await api.getVideoCatalog(item.url,controller.signal);
                        if (controller.signal.aborted) return;
                        titles.push(data.title); results.push(...data.episodes);
                        partial=partial || !!data.incomplete;
                    } else results.push({id:item.url,title:item.url,url:item.url,available:true});
                    if (results.length>10000) throw new Error(t('episodes.tooMany'));
                }
                const unique=[...new Map(results.map(row=>[row.url,row])).values()];
                setRows(unique); setTitle(titles.join(' · ')); setIncomplete(partial);
                setSelected(new Set(unique.length===1 && unique[0].available ? [unique[0].url] : []));
            } catch (err) {
                if (!controller.signal.aborted) setError(getErrorMessage(err,'episodes.loadFailed'));
            } finally { if (!controller.signal.aborted) setLoading(false); }
        })();
        return ()=>controller.abort();
    },[inputs,attempt,t]);
    const filtered=useMemo(()=>rows.filter(row=>row.title.toLocaleLowerCase().includes(query.toLocaleLowerCase())),[rows,query]);
    const visible=filtered.slice(page*50,page*50+50);
    const toggle=(url:string)=>setSelected(old=>{
        const next=new Set(old);
        if (next.has(url)) next.delete(url); else if (next.size<100) next.add(url);
        return next;
    });
    return createPortal(<dialog ref={dialog} className="video-catalog-dialog ui-dialog" aria-labelledby="video-catalog-title"
        onCancel={event=>{event.preventDefault();onClose();}}>
        <header><h2 id="video-catalog-title">{t('episodes.title')}</h2><Button onClick={onClose}>{t('common.cancel')}</Button></header>
        <div className="video-catalog-body">
            {loading ? <p role="status">{t('episodes.loading')}</p> : error ? <div role="alert"><p className="text-danger">{t(error)}</p><Button onClick={()=>setAttempt(n=>n+1)}>{t('episodes.retry')}</Button></div> : <>
                <h3 className="break-words">{title}</h3>
                <p className="text-xs text-ink-muted">{t('episodes.limit')}</p>
                {incomplete && <p className="text-xs text-warn" role="status">{t('episodes.partial')}</p>}
                <input className="ui-input w-full" aria-label={t('episodes.search')} placeholder={t('episodes.search')} value={query}
                    onChange={event=>{setQuery(event.target.value);setPage(0);}} />
                <div className="video-catalog-tools"><Button onClick={()=>setSelected(old=>{
                    const next=new Set(old);for(const row of filtered) if(row.available && next.size<100) next.add(row.url);return next;
                })}>{t('episodes.select')}</Button><Button onClick={()=>setSelected(new Set())}>{t('episodes.clear')}</Button>
                    <span role="status">{t('episodes.count',{selected:selected.size,total:rows.length})}</span></div>
                <div className="video-catalog-rows">
                    {visible.map(row=><label key={row.url} className={!row.available?'is-unavailable':''}>
                        <input type="checkbox" checked={selected.has(row.url)} disabled={!row.available || selected.size>=100 && !selected.has(row.url)} onChange={()=>toggle(row.url)} />
                        <span>{row.title}{!row.available && <small>{t('episodes.unavailable')}</small>}</span>
                    </label>)}
                    {!visible.length && <p>{t('episodes.noMatches')}</p>}
                </div>
                {filtered.length>50 && <div className="video-catalog-pagination"><Button disabled={page===0} onClick={()=>setPage(n=>n-1)}>{t('episodes.previous')}</Button>
                    <span>{page+1} / {Math.ceil(filtered.length/50)}</span><Button disabled={(page+1)*50>=filtered.length} onClick={()=>setPage(n=>n+1)}>{t('episodes.next')}</Button></div>}
            </>}
        </div>
        <footer><Button variant="primary" disabled={loading || !!error || !selected.size} onClick={()=>onConfirm(rows.filter(row=>selected.has(row.url)).map(row=>row.url))}>{t(start?'episodes.start':'episodes.confirm',{count:selected.size})}</Button></footer>
    </dialog>,document.body);
}
