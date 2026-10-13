import { useLanguage } from "../../contexts/LanguageContext";
import { translate } from "../../i18n";
import { RECORDING_OUTPUT_FORMATS } from '../../utils/recordingFormats';
import { FileVideo } from 'lucide-react';
import { type RecordingOutputSettings } from '../../api/client';
import { Card, CardHeader, Field, Select, SettingRow, Switch } from '../ui/primitives';
import { RecordingSourceFormatField } from './RecordingSourceFormatField';

interface Props {
    value: RecordingOutputSettings | null;
    onChange: (value: RecordingOutputSettings) => void;
    busy: boolean;
    error: string;
}

// 다운로드 탭이 세 영역의 저장 상태를 관리하고 이 카드는 입력만 담당한다.
export function RecordingOutputSettingsCard({ value, onChange, busy, error }: Props) {
    useLanguage();
    return <Card className="settings-section space-y-3" data-settings-section="processing" aria-busy={busy}>
        <CardHeader icon={FileVideo} title={translate("settings.recordingProcessingSettings")} description={translate("settings.theseSettingsApplyToConversionAndTSRetentionAfterRecording")} />
        {!value ? <p role={error ? 'alert' : 'status'} className="text-xs text-ink-muted">{error || translate("settings.loadingFileProcessingSettings")}</p> : <>
            <RecordingSourceFormatField />
            <Field label={translate("live.outputFormatAfterRecording")} hint={translate("settings.convertToTheSelectedFormatWhenRecordingEndsChangesApplyToTheNextRecording")}>
                <Select aria-label={translate("live.outputFormatAfterRecording")} value={value.output_format} disabled={busy} onChange={e => onChange({ ...value, output_format: e.target.value as RecordingOutputSettings['output_format'] })}
                    options={[...RECORDING_OUTPUT_FORMATS, ...(value.output_format === 'ts' ? [{ value: 'ts', label: translate("settings.tsKeepExistingSetting") }] : [])]} />
            </Field>
            <SettingRow label={translate("settings.keepSourceTSAfterConversion")} hint={translate("settings.tsIsKeptIfConversionOrInspectionFailsEvenWhenRetentionIsOffFMP4SourceRecordingsAreKeptSeparately")}
                control={<Switch label={translate("settings.keepSourceTSAfterConversion")} checked={value.keep_source_ts} disabled={busy} onChange={keep_source_ts => onChange({ ...value, keep_source_ts })} />} />
            <Field label={translate("settings.concurrentConversions")} hint={translate("settings.theDefaultOf1IsRecommendedToKeepLiveRecordingStable")}>
                <Select aria-label={translate("settings.concurrentConversions")} value={String(value.max_concurrent)} disabled={busy} onChange={e => onChange({ ...value, max_concurrent: Number(e.target.value) })}
                    options={[1, 2, 3].map(n => ({ value: String(n), label: String(n) }))} />
            </Field>
            {error && <p role="alert" className="text-xs text-danger break-words">{error}</p>}
        </>}
    </Card>;
}
