import { useState } from 'react';
import { Button } from '../ui/primitives';
import { api } from '../../api/client';
import { useLanguage } from '../../contexts/LanguageContext';
import { connectionEventLabel } from '../../utils/recordingStatus';

type Result = { sha256: string; full_decode: string; limitation: string; detail: string; size_bytes: number; capture_assessment?: string; connection_events?: {at: string; event: string; code?: string}[] };
export function RecordingIntegrity({ id }: { id: string }) {
    const { t } = useLanguage();
    const [busy, setBusy] = useState(false);
    const [result, setResult] = useState<Result | null>(null);
    const [error, setError] = useState('');
    const verify = async () => {
        setBusy(true); setError(''); setResult(null);
        try {
            setResult(await api.verifyRecordingIntegrity(id));
        } catch { setError(t('errors.inspection')); }
        finally { setBusy(false); }
    };
    return <div className="text-xs space-y-2 min-w-0">
        <Button disabled={busy} onClick={() => void verify()}>{t(busy ? 'live.integrityRunning' : 'live.integrityCheck')}</Button>
        {error && <p role="alert">{error}</p>}
        {result && <div role="status" className="space-y-1">
            <p>{t(result.full_decode === 'passed' ? 'live.integrityPassed' : 'errors.inspection')}</p>
            <p className="break-all">SHA-256: {result.sha256}</p>
            <p>{result.size_bytes.toLocaleString()} bytes</p>
            <p>{t('live.integrityScope')}</p>
            <p>{t(result.capture_assessment === 'no_observed_discontinuities' ? 'live.captureObservedClean' : result.capture_assessment === 'observed_discontinuities' ? 'live.captureObservedGaps' : 'live.captureUnknown')}</p>
            {!!result.connection_events?.length && <details><summary>{t('live.connectionTimeline')}</summary>{result.connection_events.map((event, index) => <p key={index}>{event.at} · {t(connectionEventLabel(event))}</p>)}</details>}
            {result.detail && <pre className="whitespace-pre-wrap break-all">{result.detail}</pre>}
        </div>}
    </div>;
}
