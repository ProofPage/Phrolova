import { RECORDING_OUTPUT_FORMATS } from '../../utils/recordingFormats';
import { useEffect, useRef, useState } from 'react';
import { FileVideo, Save } from 'lucide-react';
import { api, type RecordingOutputSettings } from '../../api/client';
import { getErrorMessage } from '../../utils/error';
import { Button, Card, CardHeader, Field, Select, SettingRow, Switch } from '../ui/primitives';
import { useToast } from '../ui/Toast';
import { RecordingSourceFormatField } from './RecordingSourceFormatField';

export function RecordingOutputSettingsCard({ onSaved, onDirtyChange }: { onSaved: () => void; onDirtyChange?: (dirty: boolean) => void }) {
    const [value, setValue] = useState<RecordingOutputSettings | null>(null);
    const [saved, setSaved] = useState<RecordingOutputSettings | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const pending = useRef(false);
    const toast = useToast();
    const dirty = !!value && JSON.stringify(value) !== JSON.stringify(saved);
    useEffect(() => {
        let active = true;
        void api.getRecordingOutputSettings().then(data => {
            if (active) { setValue(data); setSaved(data); }
        }).catch(() => { if (active) setError('파일 처리 설정을 불러오지 못했습니다.'); });
        return () => { active = false; };
    }, []);
    useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);
    const save = async () => {
        if (!value || pending.current) return;
        pending.current = true;
        setBusy(true);
        setError('');
        try {
            const data = await api.updateRecordingOutputSettings(value);
            setSaved(data); setValue(data);
            toast.success('파일 처리 설정을 저장했습니다.');
            onSaved();
        } catch (cause) { setError(getErrorMessage(cause, '파일 처리 설정을 저장하지 못했습니다.')); }
        finally { pending.current = false; setBusy(false); }
    };
    return <Card className="settings-section space-y-3" data-settings-section="processing" aria-busy={busy}>
        <CardHeader icon={FileVideo} title="녹화 파일 처리 설정" description="이 영역의 설정은 녹화 종료 후 변환과 TS 보관에 적용됩니다." />
        {!value ? <p role={error ? 'alert' : 'status'} className="text-xs text-ink-muted">{error || '파일 처리 설정을 불러오는 중'}</p> : <>
            <RecordingSourceFormatField />
            <Field label="녹화 완료 후 저장 형식" hint="녹화가 종료되면 선택한 형식으로 변환합니다. 변경 사항은 다음 녹화부터 적용됩니다.">
                <Select aria-label="녹화 완료 후 저장 형식" value={value.output_format} disabled={busy} onChange={e => setValue({ ...value, output_format: e.target.value as RecordingOutputSettings['output_format'] })}
                    options={[...RECORDING_OUTPUT_FORMATS, ...(value.output_format === 'ts' ? [{ value: 'ts', label: 'TS · 기존 설정 유지' }] : [])]} />
            </Field>
            <SettingRow label="변환 후 원본 TS 보관" hint="보관을 꺼도 변환·검사 실패 시 TS를 유지합니다. fMP4 녹화 원본은 별도로 보관됩니다."
                control={<Switch label="변환 후 원본 TS 보관" checked={value.keep_source_ts} disabled={busy} onChange={keep_source_ts => setValue({ ...value, keep_source_ts })} />} />
            <Field label="동시 파일 변환 수" hint="라이브 녹화가 안정적으로 유지되도록 기본 1개를 권장합니다.">
                <Select aria-label="동시 파일 변환 수" value={String(value.max_concurrent)} disabled={busy} onChange={e => setValue({ ...value, max_concurrent: Number(e.target.value) })}
                    options={[1, 2, 3].map(n => ({ value: String(n), label: `${n}개` }))} />
            </Field>
            {error && <p role="alert" className="text-xs text-danger break-words">{error}</p>}
            <div className="settings-save-row flex justify-start border-t border-line pt-3">
                <Button icon={Save} variant="primary" disabled={!dirty} loading={busy} onClick={() => void save()}>파일 처리 설정 저장</Button>
            </div>
        </>}
    </Card>;
}
