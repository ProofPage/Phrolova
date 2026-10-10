import { useEffect, useState } from 'react';
import { Save } from 'lucide-react';
import { api, type RecordingOutputSettings } from '../../api/client';
import { getErrorMessage } from '../../utils/error';
import { Button, Field, Select, SettingRow, Switch } from '../ui/primitives';
import { useToast } from '../ui/Toast';

export function RecordingOutputSettingsCard({onSaved,onDirtyChange}:{onSaved:()=>void;onDirtyChange?:(dirty:boolean)=>void}) {
    const [value,setValue]=useState<RecordingOutputSettings|null>(null);
    const [saved,setSaved]=useState<RecordingOutputSettings|null>(null);
    const [busy,setBusy]=useState(false);const [error,setError]=useState('');const toast=useToast();
    const dirty=!!value && JSON.stringify(value)!==JSON.stringify(saved);
    useEffect(()=>{void api.getRecordingOutputSettings().then(data=>{setValue(data);setSaved(data);}).catch(()=>setError('녹화 저장 설정을 불러오지 못했습니다.'));},[]);
    useEffect(()=>onDirtyChange?.(dirty),[dirty,onDirtyChange]);
    const save=async()=>{
        if(!value || busy)return;
        setBusy(true);setError('');
        try {const data=await api.updateRecordingOutputSettings(value);setSaved(data);setValue(data);toast.success('녹화 저장 설정을 저장했습니다.');onSaved();}
        catch(cause){setError(getErrorMessage(cause,'설정을 저장하지 못했습니다.'));}
        finally{setBusy(false);}
    };
    if(!value)return <p role="status" className="text-xs text-ink-muted">{error || '녹화 저장 설정을 불러오는 중'}</p>;
    return <div className="space-y-4 border-b border-line pb-5">
        <Field label="녹화 완료 후 저장 형식" hint="라이브 녹화가 종료되면 선택한 형식으로 자동 변환합니다. 변경 사항은 다음 녹화부터 적용됩니다.">
            <Select aria-label="녹화 완료 후 저장 형식" value={value.output_format} disabled={busy} onChange={e=>setValue({...value,output_format:e.target.value as 'mp4'|'mkv'})}
                options={[{value:'mp4',label:'MP4'},{value:'mkv',label:'MKV'},...(value.output_format==='ts'?[{value:'ts',label:'TS · 기존 설정 유지'}]:[])]}/>
        </Field>
        <SettingRow label="변환 후 원본 TS 보관" hint="보관을 끄더라도 변환과 파일 검사에 실패하면 원본을 유지합니다."
            control={<Switch label="변환 후 원본 TS 보관" checked={value.keep_source_ts} disabled={busy} onChange={keep_source_ts=>setValue({...value,keep_source_ts})}/>}/>
        <Field label="동시 파일 변환 수" hint="라이브 녹화가 안정적으로 유지되도록 기본 1개를 권장합니다.">
            <Select aria-label="동시 파일 변환 수" value={String(value.max_concurrent)} disabled={busy} onChange={e=>setValue({...value,max_concurrent:Number(e.target.value)})}
                options={[1,2,3].map(n=>({value:String(n),label:`${n}개`}))}/>
        </Field>
        {error&&<p role="alert" className="text-xs text-danger break-words">{error}</p>}
        <Button icon={Save} variant="primary" disabled={!dirty} loading={busy} onClick={()=>void save()}>녹화 저장 설정 저장</Button>
    </div>;
}
