import { useRef, useState } from 'react';
import { Copy, ExternalLink, FolderOpen, RefreshCw } from 'lucide-react';
import { api,type RecordingJob } from '../../api/client';
import { Button } from '../ui/primitives';
import { useToast } from '../ui/Toast';
import { getErrorMessage } from '../../utils/error';

function readableLog(value: unknown, prefix = ''): string {
    if (typeof value === 'string') return `${prefix}${value.replace(/\\r\\n|\\n/g, '\n')}`;
    if (value && typeof value === 'object') return Object.entries(value).map(([key, item])=>readableLog(item, `${prefix}${key}: `)).join('\n');
    return `${prefix}${String(value)}`;
}

export function RecordingPostprocess({job}:{job:RecordingJob}) {
    const [busy,setBusy]=useState(false);const pending=useRef(false);const toast=useToast();
    if(job.state==='recording')return null;
    const active=['pending','normalizing','converting','verifying'].includes(job.state);
    const hasSource=job.source_available===true;
    const warning = job.warning_message || (job.state === 'completed' && job.diagnostics?.returncode === 0 && job.diagnostics?.stderr ? '변환 결과 검사를 통과했지만 FFmpeg 경고가 있습니다.' : null);
    const log = readableLog(job.diagnostics || {});
    const completion = job.continuity_valid === false ? '변환 완료 · 녹화 데이터 확인 필요' : '녹화 완료';
    const labels:Record<string,string>={pending:'변환 대기',normalizing:'원본 TS 변환 중',converting:`${job.target_format.toUpperCase()} 변환 중`,verifying:'파일 검사 중',completed:`${completion} · ${job.target_format.toUpperCase()}${warning ? ' · 경고 있음' : ''}`,failed:job.error_code==='tool_missing'?'FFprobe 설치 필요':job.processing_stage==='source_inspection'?'원본 파일 검사 실패':`${job.target_format.toUpperCase()} 변환 실패`,attention:'파일 확인 필요',capture_failed:'녹화 원본 파일 없음'};
    const copyLog = async () => {
        try {
            if (navigator.clipboard) await navigator.clipboard.writeText(log);
            else {
                const focused = document.activeElement;
                const field = document.createElement('textarea');
                field.value = log; field.style.position = 'fixed'; field.style.opacity = '0';
                document.body.appendChild(field);
                try { field.select(); if (!document.execCommand('copy')) throw new Error('Copy failed'); }
                finally { field.remove(); if (focused instanceof HTMLElement) focused.focus(); }
            }
            toast.success('로그를 복사했습니다.');
        } catch { toast.error('로그를 복사하지 못했습니다.'); }
    };
    const act=async(kind:'retry'|'mkv'|'inspect'|'folder')=>{
        if(pending.current)return;pending.current=true;setBusy(true);
        try {
            if(kind==='folder'){const data=await api.openRecordingLocation(job.id);toast.success(data.message);}
            else if(kind==='inspect')await api.inspectRecording(job.id);
            else await api.retryRecording(job.id,kind==='mkv'?'mkv':undefined);
        }catch(error){toast.error(getErrorMessage(error,'파일 처리를 요청하지 못했습니다.'));}
        finally{pending.current=false;setBusy(false);}
    };
    return <div className="recording-processing min-w-0" aria-busy={active||busy}>
        <div className="recording-processing-copy min-w-0 space-y-2">
        <div className="flex flex-wrap items-center gap-2 text-xs" role="status" aria-live="polite">
            <span className={job.state==='completed'?(job.continuity_valid===false?'text-warn':'text-ok'):active?'text-info':job.state==='capture_failed'?'text-danger':'text-warn'}>{labels[job.state]||job.state}</span>
            {job.state==='failed'&&hasSource&&<span className="text-ink-muted">원본 파일 보관</span>}
            {job.state==='converting'&&job.progress!==null&&<span className="tabular-nums">{job.progress.toFixed(1)}%</span>}
        </div>
        {active&&job.progress!==null&&<div role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={job.progress} aria-label="파일 변환 진행률" className="w-full h-1 bg-surface-3 rounded overflow-hidden"><div className="h-full bg-info" style={{width:`${job.progress}%`}}/></div>}
        {job.error_message&&<p className="text-xs text-warn break-words">{job.error_message}</p>}
        {warning && <p className="text-xs text-warn break-words">{warning}</p>}
        {job.source_cleanup_warning&&<p className="text-xs text-warn break-words">{job.source_cleanup_warning}</p>}
        </div>
        {!active&&<div className="recording-processing-actions flex flex-wrap items-center gap-2">
            <Button icon={ExternalLink} title={job.can_open ? undefined : "저장된 원본 또는 완료 파일이 없습니다."} disabled={busy||job.can_open!==true} onClick={()=>window.open(api.recordingFileUrl(job.id),'_blank','noopener,noreferrer')}>{job.output_available?'파일 열기':'원본 파일 열기'}</Button>
            {job.output_available && hasSource && <Button icon={ExternalLink} disabled={busy} onClick={()=>window.open(api.recordingFileUrl(job.id,true),'_blank','noopener,noreferrer')}>원본 파일 열기</Button>}
            <Button icon={FolderOpen} title={job.can_open ? undefined : "저장된 원본 또는 완료 파일이 없습니다."} disabled={busy||job.can_open!==true} onClick={()=>void act('folder')}>저장 폴더 열기</Button>
            <Button icon={RefreshCw} title={job.can_inspect ? undefined : "처리 종료 후 파일이 존재할 때 검사할 수 있습니다."} disabled={busy||job.can_inspect!==true} onClick={()=>void act('inspect')}>다시 검사</Button>
            {(job.state!=='completed'||warning)&&<><Button icon={RefreshCw} title={job.can_retry ? undefined : "녹화가 종료된 유효한 원본 파일이 필요합니다."} disabled={busy||job.can_retry!==true} onClick={()=>void act('retry')}>다시 변환</Button>
                {job.target_format==='mp4'&&hasSource&&<Button title={job.can_retry ? undefined : "녹화가 종료된 유효한 원본 파일이 필요합니다."} disabled={busy||job.can_retry!==true} onClick={()=>void act('mkv')}>MKV로 변환</Button>}</>}
        </div>}
        {!!Object.keys(job.diagnostics||{}).length&&<details className="recording-processing-diagnostics text-xs text-ink-muted"><summary className="cursor-pointer">{job.state === 'completed' ? '처리 로그' : '오류 상세'}</summary><Button icon={Copy} className="mt-2" onClick={()=>void copyLog()}>로그 복사</Button><pre className="mt-2 whitespace-pre-wrap [overflow-wrap:anywhere] max-h-40 overflow-auto">{log}</pre></details>}
    </div>;
}
