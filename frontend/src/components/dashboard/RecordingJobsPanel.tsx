import { useEffect, useState } from 'react';
import { api, type RecordingJob } from '../../api/client';
import { RecordingPostprocess } from './RecordingPostprocess';

/** Older jobs remain manageable even after their channel is removed. */
export function RecordingJobsPanel({visibleIds}:{visibleIds:string[]}) {
    const [jobs,setJobs]=useState<RecordingJob[]>([]);
    const [error,setError]=useState(false);
    useEffect(()=>{
        let alive=true;let timer:ReturnType<typeof setTimeout>;
        const refresh=async()=>{
            try {const result=await api.getRecordingJobs();if(alive){setJobs(Array.isArray(result.jobs)?result.jobs:[]);setError(false);}}
            catch {if(alive)setError(true);}
            if(alive)timer=setTimeout(()=>void refresh(),2500);
        };
        void refresh();return()=>{alive=false;clearTimeout(timer);};
    },[]);
    const history=jobs.filter(job=>job.state!=='recording'&&!visibleIds.includes(job.id));
    if(!history.length&&!error)return null;
    return <section className="space-y-2 min-w-0" aria-label="녹화 파일 처리 이력">
        <h2 className="text-sm font-semibold">녹화 파일 처리 이력</h2>
        {error&&<p role="status" className="text-xs text-warn">파일 처리 상태를 불러오지 못했습니다. 다시 연결하고 있습니다.</p>}
        {history.map(job=><article key={job.id} className="rounded-[var(--radius-card)] border border-line bg-surface p-3 min-w-0 space-y-2">
            <p className="text-sm font-medium truncate" title={job.channel_name}>{job.channel_name}</p>
            <RecordingPostprocess job={job}/>
        </article>)}
    </section>;
}
