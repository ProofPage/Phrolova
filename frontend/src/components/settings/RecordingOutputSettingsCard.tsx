import { useLanguage } from "../../contexts/LanguageContext";
import { translate } from "../../i18n";
import { RECORDING_OUTPUT_FORMATS } from '../../utils/recordingFormats';
import { useEffect, useRef, useState } from 'react';
import { FileVideo, Save } from 'lucide-react';
import { api, type RecordingOutputSettings } from '../../api/client';
import { getErrorMessage } from '../../utils/error';
import { Button, Card, CardHeader, Field, Select, SettingRow, Switch } from '../ui/primitives';
import { useToast } from '../ui/Toast';
import { RecordingSourceFormatField } from './RecordingSourceFormatField';

export function RecordingOutputSettingsCard({ onSaved, onDirtyChange }: { onSaved: () => void; onDirtyChange?: (dirty: boolean) => void }) {
    useLanguage();
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
        }).catch(() => { if (active) setError("settings.couldNotLoadFileProcessingSettings"); });
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
            toast.success("settings.fileProcessingSettingsSaved");
            onSaved();
        } catch (cause) { setError(getErrorMessage(cause, "settings.couldNotSaveFileProcessingSettings")); }
        finally { pending.current = false; setBusy(false); }
    };
    return <Card className="settings-section space-y-3" data-settings-section="processing" aria-busy={busy}>
        <CardHeader icon={FileVideo} title={translate("settings.recordingProcessingSettings")} description={translate("settings.theseSettingsApplyToConversionAndTSRetentionAfterRecording")} />
        {!value ? <p role={error ? 'alert' : 'status'} className="text-xs text-ink-muted">{error || translate("settings.loadingFileProcessingSettings")}</p> : <>
            <RecordingSourceFormatField />
            <Field label={translate("live.outputFormatAfterRecording")} hint={translate("settings.convertToTheSelectedFormatWhenRecordingEndsChangesApplyToTheNextRecording")}>
                <Select aria-label={translate("live.outputFormatAfterRecording")} value={value.output_format} disabled={busy} onChange={e => setValue({ ...value, output_format: e.target.value as RecordingOutputSettings['output_format'] })}
                    options={[...RECORDING_OUTPUT_FORMATS, ...(value.output_format === 'ts' ? [{ value: 'ts', label: translate("settings.tsKeepExistingSetting") }] : [])]} />
            </Field>
            <SettingRow label={translate("settings.keepSourceTSAfterConversion")} hint={translate("settings.tsIsKeptIfConversionOrInspectionFailsEvenWhenRetentionIsOffFMP4SourceRecordingsAreKeptSeparately")}
                control={<Switch label={translate("settings.keepSourceTSAfterConversion")} checked={value.keep_source_ts} disabled={busy} onChange={keep_source_ts => setValue({ ...value, keep_source_ts })} />} />
            <Field label={translate("settings.concurrentConversions")} hint={translate("settings.theDefaultOf1IsRecommendedToKeepLiveRecordingStable")}>
                <Select aria-label={translate("settings.concurrentConversions")} value={String(value.max_concurrent)} disabled={busy} onChange={e => setValue({ ...value, max_concurrent: Number(e.target.value) })}
                    options={[1, 2, 3].map(n => ({ value: String(n), label: String(n) }))} />
            </Field>
            {error && <p role="alert" className="text-xs text-danger break-words">{error}</p>}
            <div className="settings-save-row flex justify-start border-t border-line pt-3">
                <Button icon={Save} variant="primary" disabled={!dirty} loading={busy} onClick={() => void save()}>{translate("settings.saveProcessingSettings")}</Button>
            </div>
        </>}
    </Card>;
}
