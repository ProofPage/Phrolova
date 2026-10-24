import { getActiveLocale } from "../../i18n";
import { useLanguage } from "../../contexts/LanguageContext";
import { translate } from "../../i18n";
import { useEffect, useState } from 'react';
import { api, type RecordingJob } from '../../api/client';
import { RecordingPostprocess } from './RecordingPostprocess';
import { PlatformBadge } from '../ui/PlatformBadge';
import { Button } from '../ui/primitives';
import { useToast } from '../ui/Toast';
import { formatBytes } from '../../utils/format';
import { RecordingIntegrity } from './RecordingIntegrity';

const active=(job:RecordingJob)=>['pending','normalizing','converting','verifying'].includes(job.state);
/** Empty legacy attempts are grouped for display; their records and files survive. */
export function RecordingJobsPanel({visibleIds}:{visibleIds:string[]}) {
    useLanguage();
    const [jobs,setJobs]=useState<RecordingJob[]>([]);
    const [error,setError]=useState(false);const [filter,setFilter]=useState('all');
    const [page,setPage]=useState(1);const [busy,setBusy]=useState(false);const toast=useToast();
    useEffect(()=>{
        let alive=true;let timer:ReturnType<typeof setTimeout>;
        const refresh=async()=>{
            try {const result=await api.getRecordingJobs();if(alive){setJobs(Array.isArray(result.jobs)?result.jobs:[]);setError(false);}}
            catch {if(alive)setError(true);}
            if(alive)timer=setTimeout(()=>void refresh(),2500);
        };
        void refresh();return()=>{alive=false;clearTimeout(timer);};
    },[]);
    const history=[...new Map(jobs.filter(job=>job.state!=='recording'&&!visibleIds.includes(job.id)).map(job=>[job.id,job])).values()];
    const selected=history.filter(job=>filter==='all'||(filter==='processing'?active(job):filter==='completed'?job.state==='completed':['failed','attention','capture_failed'].includes(job.state)));
    const groups=new Map<string,{job:RecordingJob;ids:string[]}>();
    for(const job of selected){
        const key=job.state==='capture_failed'?`empty:${job.composite_key}`:job.session_id||job.id;
        const group=groups.get(key);if(group)group.ids.push(job.id);else groups.set(key,{job,ids:[job.id]});
    }
    const rows=[...groups.values()];
    const clear=async()=>{
        if(busy)return;setBusy(true);
        const ids=selected.filter(job=>!active(job)).map(job=>job.id).slice(0,200);
        try {await api.clearRecordingHistory(ids);setJobs(current=>current.filter(job=>!ids.includes(job.id)));toast.success("live.historyRemovedSavedFilesWereKept");}
        catch {toast.error("live.couldNotClearHistory");}finally{setBusy(false);}
    };
    if(!history.length&&!error)return null;
    return <section className="recording-history-panel" aria-label={translate("live.recordingProcessingHistory")}>
        <div className="workspace-panel-heading flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-sm font-semibold">{translate("live.recordingProcessingHistory")}</h2>
            <Button disabled={busy||!selected.some(job=>!active(job))} onClick={()=>void clear()} title={translate("live.removeHistoryOnlyKeepSavedFiles")}>{translate("live.clearHistory")}</Button>
        </div>
            <div className="recording-history-filters" role="group" aria-label={translate("live.processingHistoryFilter")}>
                {[['all',translate("live.all")],['processing',translate("live.converting")],['completed',translate("live.completed")],['failed',translate("live.failed")]].map(([key,label])=><Button key={key} variant={filter===key?'secondary':'ghost'} aria-pressed={filter===key} onClick={()=>{setFilter(key);setPage(1);}}>{label}</Button>)}
            </div>
        {error&&<p role="status" className="recording-history-message text-xs text-warn">{translate("live.couldNotLoadProcessingStatusReconnecting")}</p>}
        {rows.slice(0,page*20).map(({job,ids})=><article key={job.id} className="recording-history-row">
            <div className="recording-history-identity min-w-0 space-y-1">
                <div className="flex items-center gap-2 min-w-0"><p className="text-sm font-medium truncate" title={job.channel_name}>{job.channel_name}</p>{job.platform&&<PlatformBadge platform={job.platform}/>}</div>
                <p className="text-xs text-ink-muted flex flex-wrap gap-x-2 gap-y-1"><span>{job.started_at?new Date(job.started_at).toLocaleString(getActiveLocale()): translate("live.timeUnavailable")}</span><span>{job.capture_format==='fmp4'?'fMP4 → TS':'TS'} → {job.target_format.toUpperCase()}</span>{!!job.file_size_bytes&&<span>{formatBytes(job.file_size_bytes)}</span>}</p>
                {ids.length>1&&<p className="text-xs text-ink-faint">{translate("live.startFailedWithoutAFile")}{ids.length}{translate("live.items")}</p>}
            </div>
            <RecordingPostprocess job={job} plainActions/>
            {job.state === 'completed' && job.output_available && <RecordingIntegrity id={job.id}/>}
        </article>)}
        {!rows.length&&<p className="recording-history-message text-xs text-ink-muted">{translate("live.noProcessingHistoryWithThisStatus")}</p>}
        {rows.length>page*20&&<div className="recording-history-message"><Button onClick={()=>setPage(value=>value+1)}>{translate("live.showMoreHistory")}</Button></div>}
    </section>;
}
