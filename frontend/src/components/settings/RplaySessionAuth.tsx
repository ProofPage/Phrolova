import { useEffect, useRef, useState } from 'react';
import { api, type PlatformCookieStatus } from '../../api/client';
import { useLanguage } from '../../contexts/LanguageContext';
import { getErrorMessage } from '../../utils/error';
import { Badge, Button, Card, CardHeader } from '../ui/primitives';
import { useConfirm } from '../ui/ConfirmModal';
import { useToast } from '../ui/Toast';

export function RplaySessionAuth({ onSaved }: { onSaved: () => void }) {
    const { t } = useLanguage();
    const confirm = useConfirm();
    const toast = useToast();
    const fileInput = useRef<HTMLInputElement>(null);
    const pending = useRef(false);
    const [status, setStatus] = useState<PlatformCookieStatus | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    useEffect(() => {
        let active = true;
        void api.getRplaySessionStatus().then(data => { if (active) setStatus(data); })
            .catch(cause => { if (active) setError(getErrorMessage(cause, 'settings.rplaySessionInvalid')); });
        return () => { active = false; };
    }, []);
    const change = async (action: 'upload' | 'delete' | 'refresh', file?: File) => {
        if (pending.current) return;
        pending.current = true; setBusy(true); setError('');
        try {
            const data = action === 'upload' && file ? await api.uploadRplaySession(file)
                : action === 'delete' ? await api.deleteRplaySession() : await api.getRplaySessionStatus();
            setStatus(data);
            if (action !== 'refresh') { onSaved(); toast.success(t('settings.rplaySessionUpdated')); }
        } catch (cause) { setError(getErrorMessage(cause, 'settings.rplaySessionInvalid')); }
        finally { pending.current = false; setBusy(false); if (fileInput.current) fileInput.current.value = ''; }
    };
    const remove = async () => {
        if (pending.current) return;
        if (await confirm({ title: t('settings.rplaySessionRemove'), message: t('settings.rplaySessionRemoveHelp'), confirmText: t('common.delete'), variant: 'danger' })) void change('delete');
    };
    const label = !status ? t('live.checkingStatus') : status.expired ? t('settings.rplaySessionExpired')
        : status.configured ? t(status.valid ? 'settings.rplaySessionRegistered' : 'settings.rplaySessionInvalid') : t('settings.rplaySessionEmpty');
    return <Card className="space-y-4" data-auth-platform="rplay" aria-busy={busy}>
        <CardHeader title={t('platform.rplay')} action={<Badge tone={status?.expired || (status?.configured && !status.valid) ? 'warn' : status?.configured ? 'ok' : undefined}>{label}</Badge>} />
        <div className="flex flex-wrap items-center gap-2">
            <input ref={fileInput} type="file" accept=".json,application/json" className="hidden" disabled={busy}
                aria-label={`${t('platform.rplay')} ${t('settings.rplaySessionFile')}`}
                onChange={event => { const file = event.target.files?.[0]; if (file) void change('upload', file); }} />
            <Button disabled={busy} onClick={() => fileInput.current?.click()}>{t(status?.configured ? 'settings.replaceFile' : 'settings.chooseFile')}</Button>
            <Button loading={busy} onClick={() => void change('refresh')}>{t('settings.checkStatus')}</Button>
            {status?.configured && <Button variant="danger" disabled={busy} onClick={() => void remove()}>{t('common.delete')}</Button>}
        </div>
        <p role="status" className="text-xs text-ink-muted">{t('settings.rplaySessionHelp')}</p>
        {error && <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">{error}</p>}
    </Card>;
}
