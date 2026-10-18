import { useEffect, useRef, useState } from 'react';
import { api, type PlatformCookieStatus } from '../../api/client';
import { useLanguage } from '../../contexts/LanguageContext';
import { getErrorMessage } from '../../utils/error';
import { makeRplaySessionExportScript } from '../../utils/rplaySessionExport';
import { Badge, Button, CollapsibleCard } from '../ui/primitives';
import { useConfirm } from '../ui/ConfirmModal';
import { useToast } from '../ui/Toast';

export function RplaySessionAuth({ onSaved }: { onSaved: () => void }) {
    const { t } = useLanguage();
    const confirm = useConfirm();
    const toast = useToast();
    const fileInput = useRef<HTMLInputElement>(null);
    const pending = useRef(false);
    const revision = useRef(0);
    const exportHelp = useRef<HTMLDetailsElement>(null);
    const exportCode = useRef<HTMLTextAreaElement>(null);
    const [status, setStatus] = useState<PlatformCookieStatus | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [method, setMethod] = useState<'account' | 'file'>('account');

    useEffect(() => {
        let active = true;
        const current = revision.current;
        void api.getRplaySessionStatus().then(data => { if (active && current === revision.current) setStatus(data); })
            .catch(cause => { if (active && current === revision.current) setError(getErrorMessage(cause, 'settings.rplaySessionInvalid')); });
        return () => { active = false; };
    }, []);

    const change = async (action: 'upload' | 'delete' | 'refresh' | 'login', file?: File) => {
        if (pending.current) return;
        revision.current += 1;
        pending.current = true; setBusy(true); setError('');
        try {
            const data = action === 'upload' && file ? await api.uploadRplaySession(file)
                : action === 'login' ? await api.loginRplay(email, password)
                : action === 'delete' ? await api.deleteRplaySession() : await api.getRplaySessionStatus();
            setStatus(data);
            if (action !== 'refresh') {
                onSaved();
                toast.success(t('settings.rplaySessionUpdated'));
                if (action === 'login') { setPassword(''); }
            }
        } catch (cause) { setError(getErrorMessage(cause, 'settings.rplaySessionInvalid')); }
        finally { pending.current = false; setBusy(false); if (action === 'login') setPassword(''); if (fileInput.current) fileInput.current.value = ''; }
    };

    const remove = async () => {
        if (pending.current) return;
        if (await confirm({ title: t('settings.rplaySessionRemove'), message: t('settings.rplaySessionRemoveHelp'), confirmText: t('common.delete'), variant: 'danger' })) void change('delete');
    };

    const handleLoginSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        if (!email.trim() || !password) return;
        void change('login');
    };

    const label = !status ? t('live.checkingStatus') : status.expired ? t('settings.rplaySessionExpired')
        : status.configured ? t(status.valid ? 'settings.rplaySessionRegistered' : 'settings.rplaySessionInvalid') : t('settings.rplaySessionEmpty');
    const script = makeRplaySessionExportScript({ wrongSite: t('settings.rplayExportWrongSite'),
        signedOut: t('settings.rplayExportSignedOut'), failed: t('settings.rplayExportFailed') });
    const copyExport = async () => {
        if (exportHelp.current) exportHelp.current.open = true;
        try {
            await navigator.clipboard.writeText(script);
            toast.success(t('settings.rplayExportCopied'));
        } catch {
            exportCode.current?.focus();
            exportCode.current?.select();
            toast.error(t('settings.rplayExportCopyManually'));
        }
    };

    return <div className="auth-platform-card" data-auth-platform="rplay" aria-busy={busy}>
        <CollapsibleCard title={t('platform.rplay')} description={t('settings.authAccountOrSession')}
            onOpenChange={open => { if (!open) setPassword(''); }}
            action={<Badge tone={status?.expired || (status?.configured && !status.valid) ? 'warn' : status?.configured ? 'ok' : undefined}>{label}</Badge>}>
        <div className="space-y-4">
        <div className="auth-methods" role="group" aria-label={t('settings.authMethod')}>
            <Button aria-pressed={method === 'account'} onClick={() => { setMethod('account'); setPassword(''); }}>{t('settings.authAccountMethod')}</Button>
            <Button aria-pressed={method === 'file'} onClick={() => { setMethod('file'); setPassword(''); }}>{t('settings.authSessionMethod')}</Button>
        </div>

        {method === 'account' && <form onSubmit={handleLoginSubmit} className="space-y-3">
            <div className="text-xs font-medium text-ink">{t('settings.rplayAccountLogin')}</div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <input
                    id="rplay-login-email" aria-label={t('settings.rplayEmailPlaceholder')}
                    type="email"
                    value={email}
                    onChange={e => setEmail(e.target.value)}
                    placeholder={t('settings.rplayEmailPlaceholder')}
                    disabled={busy}
                    className="ui-input input-focus text-xs"
                    autoComplete="username"
                />
                <input
                    id="rplay-login-password" aria-label={t('settings.rplayPasswordPlaceholder')}
                    type="password"
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    placeholder={t('settings.rplayPasswordPlaceholder')}
                    disabled={busy}
                    className="ui-input input-focus text-xs"
                    autoComplete="current-password"
                />
            </div>
            <div className="flex justify-end">
                <Button type="submit" disabled={busy || !email.trim() || !password} loading={busy}>
                    {t('settings.authAccountMethod')}
                </Button>
            </div>
            <p className="text-xs text-ink-muted">{t('settings.authPasswordHelp')}</p>
        </form>}

        <div className="flex flex-wrap items-center gap-2">
            <input ref={fileInput} type="file" accept=".json,application/json" className="hidden" disabled={busy}
                aria-label={`${t('platform.rplay')} ${t('settings.rplaySessionFile')}`}
                onChange={event => { const file = event.target.files?.[0]; if (file) void change('upload', file); }} />
            {method === 'file' && <Button disabled={busy} onClick={() => fileInput.current?.click()}>{t(status?.configured ? 'settings.replaceFile' : 'settings.chooseFile')}</Button>}
            <Button loading={busy} onClick={() => void change('refresh')}>{t('settings.checkStatus')}</Button>
            {method === 'file' && <Button disabled={busy} onClick={() => void copyExport()}>{t('settings.rplayExportCopy')}</Button>}
            {status?.configured && <Button variant="danger" disabled={busy} onClick={() => void remove()}>{t('common.delete')}</Button>}
        </div>
        {method === 'file' && <p className="text-xs text-ink-muted">{t('settings.rplaySessionHelp')}</p>}
        {method === 'file' && <details ref={exportHelp} className="text-xs text-ink-muted">
            <summary className="cursor-pointer text-ink">{t('settings.rplayExportHelp')}</summary>
            <ol className="my-3 list-decimal space-y-2 pl-5">
                <li>{t('settings.rplayExportStepOne')} <a href="https://rplay.live/" target="_blank" rel="noopener noreferrer" className="text-accent">rplay.live</a></li>
                <li>{t('settings.rplayExportStepTwo')}</li>
                <li>{t('settings.rplayExportStepThree')}</li>
            </ol>
            <textarea ref={exportCode} readOnly value={script} rows={5} spellCheck={false}
                aria-label={t('settings.rplayExportCopy')} className="ui-input input-focus w-full resize-y font-mono text-xs" />
        </details>}
        </div>
        </CollapsibleCard>
        {error && <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">{error}</p>}
    </div>;
}
