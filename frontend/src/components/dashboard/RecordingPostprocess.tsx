import { useRef, useState } from 'react';
import { ExternalLink, FolderOpen, RefreshCw } from 'lucide-react';
import { api,type RecordingJob } from '../../api/client';
import { Button } from '../ui/primitives';
import { useToast } from '../ui/Toast';
import { getErrorMessage } from '../../utils/error';

export function RecordingPostprocess({job}:{job:RecordingJob}) {
    const [busy,setBusy]=useState(false);const pending=useRef(false);const toast=useToast();
    if(job.state==='recording')return null;
    const active=['pending','converting','verifying'].includes(job.state);
    const labels:Record<string,string>={pending:'변환 대기',converting:`${job.target_format.toUpperCase()} 변환 중`,verifying:'파일 검사 중',completed:`녹화 완료 · ${job.target_format.toUpperCase()}`,failed:'변환 실패 · 원본 TS 보관',attention:'파일 확인 필요 · 원본 TS 보관'};
    const act=async(kind:'retry'|'mkv'|'inspect'|'folder')=>{
        if(pending.current)return;pending.current=true;setBusy(true);
        try {
            if(kind==='folder'){const data=await api.openRecordingLocation(job.id);toast.success(data.message);}
            else if(kind==='inspect')await api.inspectRecording(job.id);
            else await api.retryRecording(job.id,kind==='mkv'?'mkv':undefined);
        }catch(error){toast.error(getErrorMessage(error,'파일 처리를 요청하지 못했습니다.'));}
        finally{pending.current=false;setBusy(false);}
    };
    return <div className="border-t border-line pt-3 space-y-2 min-w-0" aria-busy={active||busy}>
        <div className="flex flex-wrap items-center gap-2 text-xs" role="status" aria-live="polite">
            <span className={job.state==='completed'?'text-ok':active?'text-info':'text-warn'}>{labels[job.state]||job.state}</span>
            {job.state==='converting'&&job.progress!==null&&<span className="tabular-nums">{job.progress.toFixed(1)}%</span>}
        </div>
        {active&&job.progress!==null&&<div role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={job.progress} aria-label="파일 변환 진행률" className="w-full h-1 bg-surface-3 rounded overflow-hidden"><div className="h-full bg-info" style={{width:`${job.progress}%`}}/></div>}
        {job.error_message&&<p className="text-xs text-warn break-words">{job.error_message}</p>}
        {job.source_cleanup_warning&&<p className="text-xs text-warn break-words">{job.source_cleanup_warning}</p>}
        {!active&&<div className="flex flex-wrap items-center gap-2">
            <Button icon={ExternalLink} onClick={()=>window.open(api.recordingFileUrl(job.id),'_blank','noopener,noreferrer')}>파일 열기</Button>
            <Button icon={FolderOpen} disabled={busy} onClick={()=>void act('folder')}>저장 폴더 열기</Button>
            <Button icon={RefreshCw} disabled={busy} onClick={()=>void act('inspect')}>다시 검사</Button>
            {job.state!=='completed'&&<><Button icon={RefreshCw} disabled={busy} onClick={()=>void act('retry')}>다시 변환</Button>
                {job.target_format==='mp4'&&<Button disabled={busy} onClick={()=>void act('mkv')}>MKV로 변환</Button>}</>}
        </div>}
    </div>;
}
