import { useLanguage } from "../../contexts/LanguageContext";
import { translate, formatNumber } from "../../i18n";
import { useRef, useState } from 'react';
import { Copy, ExternalLink, FolderOpen, RefreshCw } from 'lucide-react';
import { api,type RecordingJob } from '../../api/client';
import { Button } from '../ui/primitives';
import { useToast } from '../ui/Toast';
import { getErrorMessage, localizedStatus } from '../../utils/error';

function readableLog(value: unknown, prefix = ''): string {
    if (typeof value === 'string') return `${prefix}${value.replace(/\\r\\n|\\n/g, '\n')}`;
    if (value && typeof value === 'object') return Object.entries(value).map(([key, item])=>readableLog(item, `${prefix}${key}: `)).join('\n');
    return `${prefix}${String(value)}`;
}

export function RecordingPostprocess({job}:{job:RecordingJob}) {
    useLanguage();
    const [busy,setBusy]=useState(false);const pending=useRef(false);const toast=useToast();
    if(job.state==='recording')return null;
    const active=['pending','normalizing','converting','verifying'].includes(job.state);
    const hasSource=job.source_available===true;
    const warning = job.warning_message || (job.state === 'completed' && job.diagnostics?.returncode === 0 && job.diagnostics?.stderr ? "live.theConvertedFilePassedInspectionButFFmpegReportedWarnings" : null);
    const log = readableLog(job.diagnostics || {});
    const completion = job.continuity_valid === false ? "live.conversionCompleteCheckRecordingData" : "live.recordingCompleted";
    const labels:Record<string,string>={pending:"live.waitingToConvert",normalizing:"live.convertingSourceTS",converting:translate('live.convertingFormat', {format:job.target_format.toUpperCase()}),verifying:"live.verifying",completed:`${translate(completion)} · ${job.target_format.toUpperCase()}${warning ? translate("live.warnings") : ''}`,failed:job.error_code==='tool_missing'?"live.ffprobeInstallationRequired":job.processing_stage==='source_inspection'?"live.sourceFileInspectionFailed":translate('live.conversionFailed', {format:job.target_format.toUpperCase()}),attention:"live.fileNeedsAttention",capture_failed:"live.recordingSourceFileMissing"};
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
            toast.success("live.logCopied");
        } catch { toast.error("live.couldNotCopyLog"); }
    };
    const act=async(kind:'retry'|'mkv'|'inspect'|'folder')=>{
        if(pending.current)return;pending.current=true;setBusy(true);
        try {
            if(kind==='folder'){const data=await api.openRecordingLocation(job.id);toast.success(localizedStatus(data.message, 'common.folderOpened'));}
            else if(kind==='inspect')await api.inspectRecording(job.id);
            else await api.retryRecording(job.id,kind==='mkv'?'mkv':undefined);
        }catch(error){toast.error(getErrorMessage(error,"live.couldNotRequestFileProcessing"));}
        finally{pending.current=false;setBusy(false);}
    };
    return <div className="recording-processing min-w-0" aria-busy={active||busy}>
        <div className="recording-processing-copy min-w-0 space-y-2">
        <div className="flex flex-wrap items-center gap-2 text-xs" role="status" aria-live="polite">
            <span className={job.state==='completed'?(job.continuity_valid===false?'text-warn':'text-ok'):active?'text-info':job.state==='capture_failed'?'text-danger':'text-warn'}>{translate(labels[job.state]||job.state)}</span>
            {job.state==='failed'&&hasSource&&<span className="text-ink-muted">{translate("live.keepSourceFile")}</span>}
            {job.state==='converting'&&job.progress!==null&&<span className="tabular-nums">{formatNumber(job.progress, {minimumFractionDigits:1, maximumFractionDigits:1})}%</span>}
        </div>
        {active&&job.progress!==null&&<div role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={job.progress} aria-label={translate("live.conversionProgress")} className="w-full h-1 bg-surface-3 rounded overflow-hidden"><div className="h-full bg-info" style={{width:`${job.progress}%`}}/></div>}
        {job.error_message&&<p className="text-xs text-warn break-words">{localizedStatus(job.error_message,"errors.processing")}</p>}
        {warning && <p className="text-xs text-warn break-words">{localizedStatus(warning,"live.fileProcessingWarning")}</p>}
        {job.source_cleanup_warning&&<p className="text-xs text-warn break-words">{localizedStatus(job.source_cleanup_warning,"errors.fileAccess")}</p>}
        </div>
        {!active&&<div className="recording-processing-actions flex flex-wrap items-center gap-2">
            <Button icon={ExternalLink} title={job.can_open ? undefined : translate("live.noSavedSourceOrCompletedFile")} disabled={busy||job.can_open!==true} onClick={()=>window.open(api.recordingFileUrl(job.id),'_blank','noopener,noreferrer')}>{job.output_available?translate("live.openFile"):translate("live.openSourceFile")}</Button>
            {job.output_available && hasSource && <Button icon={ExternalLink} disabled={busy} onClick={()=>window.open(api.recordingFileUrl(job.id,true),'_blank','noopener,noreferrer')}>{translate("live.openSourceFile")}</Button>}
            <Button icon={FolderOpen} title={job.can_open ? undefined : translate("live.noSavedSourceOrCompletedFile")} disabled={busy||job.can_open!==true} onClick={()=>void act('folder')}>{translate("live.openSavedFolder")}</Button>
            <Button icon={RefreshCw} title={job.can_inspect ? undefined : translate("live.inspectionIsAvailableAfterProcessingFinishesIfTheFileExists")} disabled={busy||job.can_inspect!==true} onClick={()=>void act('inspect')}>{translate("live.inspectAgain")}</Button>
            {(job.state!=='completed'||warning)&&<><Button icon={RefreshCw} title={job.can_retry ? undefined : translate("live.aValidSourceFileFromAFinishedRecordingIsRequired")} disabled={busy||job.can_retry!==true} onClick={()=>void act('retry')}>{translate("live.convertAgain")}</Button>
                {job.target_format==='mp4'&&hasSource&&<Button title={job.can_retry ? undefined : translate("live.aValidSourceFileFromAFinishedRecordingIsRequired")} disabled={busy||job.can_retry!==true} onClick={()=>void act('mkv')}>{translate("live.convertToMKV")}</Button>}</>}
        </div>}
        {!!Object.keys(job.diagnostics||{}).length&&<details className="recording-processing-diagnostics text-xs text-ink-muted"><summary className="cursor-pointer">{job.state === 'completed' ? translate("live.processingLog") : translate("live.errorDetails")}</summary><Button icon={Copy} className="mt-2" onClick={()=>void copyLog()}>{translate("live.copyLog")}</Button><pre className="mt-2 whitespace-pre-wrap [overflow-wrap:anywhere] max-h-40 overflow-auto">{log}</pre></details>}
    </div>;
}
