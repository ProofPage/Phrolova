import { translate } from "../../i18n";
import { Field, Input } from '../ui/primitives';
import { useLanguage } from '../../contexts/LanguageContext';

/** The receiver detects the actual source container; it is not a selectable format. */
export function RecordingSourceFormatField({ label = "settings.liveRecordingSourceFormat" }: { label?: string }) {
    const { t } = useLanguage();
    return (
        <Field label={label} hint={translate("settings.streamlinkRecordsTheOriginalStreamFormatTSAsTsAndFragmentedMP4FMP4AsNativeMp4AfterRecordingFullyStopsFMP4IsConvertedToTSAndThenToTheSelectedOutputFormat")}>
            <Input readOnly aria-label={t(label)} value={t("settings.autoDetectTSFMP4")} />
        </Field>
    );
}
