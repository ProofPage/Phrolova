import { Field, Input } from '../ui/primitives';
import { useLanguage } from '../../contexts/LanguageContext';

/** The receiver detects the actual source container; it is not a selectable format. */
export function RecordingSourceFormatField({ label = '라이브 녹화 원본 형식' }: { label?: string }) {
    const { t } = useLanguage();
    return (
        <Field label={label} hint="Streamlink로 실제 원본 형식을 그대로 녹화합니다. TS는 .ts, 분할 MP4(fMP4)는 .native.mp4로 저장합니다. 녹화가 완전히 종료되면 fMP4를 TS로 변환하고, 선택한 완료 형식으로 저장합니다.">
            <Input readOnly aria-label={t(label)} value={t('자동 감지 · TS / fMP4')} />
        </Field>
    );
}
