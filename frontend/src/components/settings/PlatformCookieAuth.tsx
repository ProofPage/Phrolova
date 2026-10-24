import { translate } from "../../i18n";
import { useEffect, useRef, useState } from 'react';
import { ClipboardPaste, Globe, RefreshCw, Trash2, Upload } from 'lucide-react';
import { api, DOWNLOAD_SOURCE_LABELS, PLATFORM_LABELS, type AccountLoginPlatform, type CookiePlatform, type PlatformCookieStatus } from '../../api/client';
import { getErrorMessage } from '../../utils/error';
import { useLanguage } from '../../contexts/LanguageContext';
import { useConfirm } from '../ui/ConfirmModal';
import { useToast } from '../ui/Toast';
import { Badge, Button } from '../ui/primitives';
import { AuthPlatformCard } from './AuthPlatformCard';
import { useDialogKeyboard } from '../../hooks/useDialogKeyboard';

const ACCOUNT_LOGINS: Record<AccountLoginPlatform, { email: boolean; url: string }> = {
    cime: { email: true, url: 'https://ci.me/auth/login' },
    pandalive: { email: false, url: 'https://www.pandalive.co.kr/' },
    popkontv: { email: false, url: 'https://www.popkontv.com/' },
    hearheart: { email: true, url: 'https://hearheart.com/' },
    animaru: { email: false, url: 'https://animaru1.com/' },
    anilife: { email: false, url: 'https://anilife01.tv/' },
};

/** Only registration/validation status is returned; cookie values never enter UI state. */
export function PlatformCookieAuth({ platform, onSaved }: { platform: CookiePlatform; onSaved?: () => void }) {
    const { t } = useLanguage();
    const toast = useToast();
    const confirm = useConfirm();
    const name = t(platform === 'hearheart' || platform === 'animaru' || platform === 'anilife' ? DOWNLOAD_SOURCE_LABELS[platform] : PLATFORM_LABELS[platform]);
    const fileInput = useRef<HTMLInputElement>(null);
    const pending = useRef(false);
    const revision = useRef(0);
    const [status, setStatus] = useState<PlatformCookieStatus | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [method, setMethod] = useState<'account' | 'file'>('account');
    const [textModalOpen, setTextModalOpen] = useState(false);
    const [pastedText, setPastedText] = useState('');
    const textDialog = useRef<HTMLDivElement>(null);
    useDialogKeyboard(textDialog, () => {
        if (!pending.current) { setTextModalOpen(false); setPastedText(''); }
    }, textModalOpen);
    const accountPlatform = platform in ACCOUNT_LOGINS ? platform as AccountLoginPlatform : null;
    const account = accountPlatform ? ACCOUNT_LOGINS[accountPlatform] : null;
    useEffect(() => {
        let active = true;
        const current = revision.current;
        void api.getPlatformCookieStatus(platform).then(data => { if (active && current === revision.current) setStatus(data); })
            .catch(() => { if (active && current === revision.current) setError(t("settings.couldNotCheckCookieFileStatusTryAgain")); });
        return () => { active = false; };
    }, [platform]);
    const change = async (action: 'upload' | 'delete' | 'refresh' | 'login' | 'text' | 'browser', payload?: File | string) => {
        if (pending.current) return;
        revision.current += 1;
        pending.current = true;
        setBusy(true);
        setError('');
        try {
            const data = action === 'upload' && payload instanceof File ? await api.uploadPlatformCookie(platform, payload)
                : action === 'text' && typeof payload === 'string' ? await api.savePlatformCookieText(platform, payload)
                : action === 'browser' ? await api.importPlatformCookieFromBrowser(platform, typeof payload === 'string' ? payload : 'auto')
                : action === 'login' && accountPlatform ? await api.loginPlatform(accountPlatform, username.trim(), password)
                : action === 'delete' ? await api.deletePlatformCookie(platform) : await api.checkPlatformCookies(platform);
            setStatus(data);
            if (action === 'text') { setPastedText(''); setTextModalOpen(false); }
            if (action !== 'refresh') {
                const successMsg = action === 'login' ? "settings.authLoginSuccess"
                    : action === 'browser' ? "settings.browserImportSuccess"
                    : action === 'text' ? "settings.cookieTextRegistered"
                    : action === 'upload' ? "settings.cookieFileRegistered"
                    : "settings.registeredCookiesRemoved";
                toast.success(t(successMsg));
                onSaved?.();
            } else {
                if (data?.valid === true && data.login_verified === true) {
                    toast.success(data.message || t("settings.loginConfirmed"));
                } else if (data?.configured && data?.valid === false) {
                    toast.error(data.message || t("settings.cookieFileNeedsAttention"));
                } else {
                    toast.warning(data?.message || t("settings.noRegisteredCookies"));
                }
            }
        } catch (cause) {
            const message = getErrorMessage(cause, t("settings.couldNotProcessTheCookieFileTryAgain"));
            setError(message);
            toast.error(message);
        } finally {
            pending.current = false;
            setBusy(false);
            if (action === 'login') setPassword('');
            if (fileInput.current) fileInput.current.value = '';
        }
    };
    const remove = async () => {
        if (pending.current) return;
        if (await confirm({ title: `${name} ${t("settings.removeCookieFile")}`, message: t("settings.removeTheRegisteredCookiesPublicContentRemainsAvailableWithoutCookies"), confirmText: t("common.delete"), variant: 'danger' })) void change('delete');
    };
    const label = error ? t("settings.cookieFileNeedsAttention") : !status ? t("live.checkingStatus") : status.expired ? t("settings.cookieExpired")
        : status.configured && status.valid === true && status.login_verified === true ? t("settings.loginConfirmed")
        : status.configured && status.valid === false ? t("settings.cookieFileNeedsAttention") : status.configured ? t("settings.cookiesRegistered") : t("settings.noRegisteredCookies");
    return <div className="auth-platform-card" data-cookie-platform={platform} aria-busy={busy}>
        <AuthPlatformCard platform={platform} title={t(name)}
            description={t(account ? "settings.authAccountOrCookie" : "settings.authCookieMethod")}
            onClose={() => { setPassword(''); setPastedText(''); setTextModalOpen(false); }}
            action={<Badge tone={error || status?.expired || (status?.configured && status.valid === false) ? 'warn' : (status?.configured && status.valid === true && status.login_verified === true) ? 'ok' : status?.configured ? 'neutral' : undefined}>{label}</Badge>}>
        <div className="space-y-4">
        {account && <div className="auth-methods" role="group" aria-label={t('settings.authMethod')}>
            <Button disabled={busy} aria-pressed={method === 'account'} onClick={() => { setMethod('account'); setPassword(''); }}>{t('settings.authAccountMethod')}</Button>
            <Button disabled={busy} aria-pressed={method === 'file'} onClick={() => { setMethod('file'); setPassword(''); }}>{t('settings.authCookieMethod')}</Button>
        </div>}
        {account && method === 'account' && <form data-account-login={platform} className="auth-login-form"
            onSubmit={event => { event.preventDefault(); if (username.trim() && password) void change('login'); }}>
            <div className="text-xs font-medium text-ink">{t('settings.platformAccountLogin', { platform: name })}</div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <label className="space-y-1 text-xs text-ink-muted" htmlFor={`${platform}-login-username`}>
                    <span>{t(account.email ? 'settings.rplayEmailPlaceholder' : 'settings.platformUsername')}</span>
                    <input id={`${platform}-login-username`} name="username" type={account.email ? 'email' : 'text'}
                        autoComplete="username" required maxLength={320} value={username} disabled={busy}
                        onChange={event => setUsername(event.target.value)} className="ui-input input-focus w-full text-xs" />
                </label>
                <label className="space-y-1 text-xs text-ink-muted" htmlFor={`${platform}-login-password`}>
                    <span>{t('settings.rplayPasswordPlaceholder')}</span>
                    <input id={`${platform}-login-password`} name="password" type="password" autoComplete="current-password"
                        required maxLength={4096} value={password} disabled={busy}
                        onChange={event => setPassword(event.target.value)} className="ui-input input-focus w-full text-xs" />
                </label>
            </div>
            <div className="auth-login-actions">
                <Button variant="primary" type="submit" loading={busy} disabled={busy || !username.trim() || !password}>{t('settings.authAccountMethod')}</Button>
                <a href={account.url} target="_blank" rel="noopener noreferrer" className="text-xs text-accent hover:underline">
                    {t('settings.platformOpenLogin')}
                </a>
            </div>
            <div className="auth-login-help">
                <p className="text-xs text-ink-muted">{t('settings.authPasswordHelp')}</p>
                {platform === 'cime' && <p className="text-xs text-ink-muted">{t('settings.cimeAccountLoginHelp')}</p>}
            </div>
        </form>}
        <div className="auth-tools">
            <input ref={fileInput} type="file" accept=".txt" aria-label={`${name} ${t("settings.cookieFile")}`} className="hidden" disabled={busy} onChange={event => { const file = event.target.files?.[0]; if (file) void change('upload', file); }} />
            {(!account || method === 'file') && <>
                <Button icon={Upload} disabled={busy} onClick={() => fileInput.current?.click()} aria-label={`${name} ${t("settings.selectCookieFile")}`}>{t(status?.configured ? translate("settings.replaceFile") : translate("settings.chooseFile"))}</Button>
                <Button icon={ClipboardPaste} disabled={busy} onClick={() => setTextModalOpen(true)}>{t("settings.pasteCookieText")}</Button>
            </>}
            <Button icon={Globe} loading={busy} disabled={busy} onClick={() => void change('browser', 'auto')} title={t("settings.importFromBrowser")}>{t("settings.importFromBrowser")}</Button>
            <Button className="auth-check" icon={RefreshCw} loading={busy} disabled={busy} onClick={() => void change('refresh')} aria-label={`${name} ${t("settings.checkCookieStatus")}`}>{t("settings.checkStatus")}</Button>
            {status?.configured && <Button className="auth-remove" variant="danger" icon={Trash2} disabled={busy} onClick={() => void remove()} aria-label={`${name} ${t("settings.removeCookieFile")}`}>{t("common.delete")}</Button>}
        </div>
        {(!account || method === 'file') && <p className="text-xs text-ink-muted">{t('settings.authCookieFileHelp')}</p>}
        {t(`settings.cookieHelp.${platform}`) !== `settings.cookieHelp.${platform}` ? (
            <p className="text-xs text-ink-muted">{t(`settings.cookieHelp.${platform}`)}</p>
        ) : platform === 'kick' ? (
            <p className="text-xs text-ink-muted">{t('live.kickQualityAuthentication')}</p>
        ) : null}
        {status?.expired && <p className="text-xs text-warn">{t("settings.exportCookiesAgainFromASignedInBrowserAndRegisterTheFile")}</p>}
        {!error && status?.message && <p className="text-xs text-ink-muted" role="status">{status.message}</p>}
        </div>
        {error && !textModalOpen && <p role="alert" className="mt-2 text-xs text-danger [overflow-wrap:anywhere]">{t(error)}</p>}

        {textModalOpen && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs">
                <div ref={textDialog} role="dialog" aria-modal="true" aria-labelledby={`${platform}-cookie-dialog-title`} tabIndex={-1}
                    className="ui-dialog w-full max-w-lg rounded-xl border border-line bg-surface-1 p-5 shadow-2xl space-y-4">
                    <div className="space-y-1">
                        <h4 id={`${platform}-cookie-dialog-title`} className="text-sm font-semibold text-ink">{name} {t("settings.pasteCookieText")}</h4>
                        <p className="text-xs text-ink-muted">{t("settings.pasteCookieDescription")}</p>
                    </div>
                    <textarea
                        className="ui-input input-focus w-full h-44 font-mono text-xs p-3 leading-relaxed resize-none rounded-lg"
                        placeholder={t("settings.pasteCookieDescription")}
                        aria-label={`${name} ${t("settings.pasteCookieText")}`}
                        value={pastedText}
                        disabled={busy}
                        onChange={e => setPastedText(e.target.value)}
                    />
                    {error && <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">{t(error)}</p>}
                    <div className="flex justify-end gap-2 pt-2">
                        <Button variant="secondary" disabled={busy} onClick={() => { setTextModalOpen(false); setPastedText(''); }}>{t("common.cancel")}</Button>
                        <Button disabled={busy || !pastedText.trim()} loading={busy} onClick={() => void change('text', pastedText.trim())}>{t("settings.saveChanges")}</Button>
                    </div>
                </div>
            </div>
        )}
        </AuthPlatformCard>
    </div>;
}
