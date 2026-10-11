import { useEffect, useState } from 'react';
import { Trash2 } from 'lucide-react';
import { api, type RecordingJob } from '../../api/client';
import { RecordingPostprocess } from './RecordingPostprocess';
import { PlatformBadge } from '../ui/PlatformBadge';
import { Button } from '../ui/primitives';
import { useToast } from '../ui/Toast';
import { formatBytes } from '../../utils/format';

const active=(job:RecordingJob)=>['pending','normalizing','converting','verifying'].includes(job.state);
/** Empty legacy attempts are grouped for display; their records and files survive. */
export function RecordingJobsPanel({visibleIds}:{visibleIds:string[]}) {
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
        try {await api.clearRecordingHistory(ids);setJobs(current=>current.filter(job=>!ids.includes(job.id)));toast.success('이력을 목록에서 제거했습니다. 저장 파일은 유지됩니다.');}
        catch {toast.error('이력을 정리하지 못했습니다.');}finally{setBusy(false);}
    };
    if(!history.length&&!error)return null;
    return <section className="space-y-2 min-w-0" aria-label="녹화 파일 처리 이력">
        <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-sm font-semibold">녹화 파일 처리 이력</h2>
            <div className="flex flex-wrap items-center gap-1" role="group" aria-label="처리 이력 필터">
                {[['all','전체'],['processing','변환 중'],['completed','완료'],['failed','실패']].map(([key,label])=><Button key={key} variant={filter===key?'secondary':'ghost'} aria-pressed={filter===key} onClick={()=>{setFilter(key);setPage(1);}}>{label}</Button>)}
            </div>
            <Button icon={Trash2} disabled={busy||!selected.some(job=>!active(job))} onClick={()=>void clear()} title="목록에서만 제거하며 저장 파일은 유지합니다.">이력 정리</Button>
        </div>
        {error&&<p role="status" className="text-xs text-warn">파일 처리 상태를 불러오지 못했습니다. 다시 연결하고 있습니다.</p>}
        {rows.slice(0,page*20).map(({job,ids})=><article key={job.id} className="recording-history-row rounded-[var(--radius-card)] border border-line bg-surface p-3 min-w-0">
            <div className="min-w-0 space-y-1">
                <div className="flex items-center gap-2 min-w-0"><p className="text-sm font-medium truncate" title={job.channel_name}>{job.channel_name}</p>{job.platform&&<PlatformBadge platform={job.platform}/>}</div>
                <p className="text-xs text-ink-muted flex flex-wrap gap-x-2 gap-y-1"><span>{job.started_at?new Date(job.started_at).toLocaleString(): '시각 정보 없음'}</span><span>{job.capture_format==='fmp4'?'fMP4 → TS':'TS'} → {job.target_format.toUpperCase()}</span>{!!job.file_size_bytes&&<span>{formatBytes(job.file_size_bytes)}</span>}</p>
                {ids.length>1&&<p className="text-xs text-ink-faint">파일 없는 시작 실패 {ids.length}건</p>}
            </div>
            <RecordingPostprocess job={job}/>
        </article>)}
        {!rows.length&&<p className="text-xs text-ink-muted py-3">해당 상태의 처리 이력이 없습니다.</p>}
        {rows.length>page*20&&<Button onClick={()=>setPage(value=>value+1)}>이력 더 보기</Button>}
    </section>;
}
