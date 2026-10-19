import { translate } from "../../i18n";
import { useEffect, useRef, useState } from 'react';
import { RefreshCw, Trash2, Upload } from 'lucide-react';
import { api, DOWNLOAD_SOURCE_LABELS, PLATFORM_LABELS, type AccountLoginPlatform, type CookiePlatform, type PlatformCookieStatus } from '../../api/client';
import { getErrorMessage } from '../../utils/error';
import { useLanguage } from '../../contexts/LanguageContext';
import { useConfirm } from '../ui/ConfirmModal';
import { useToast } from '../ui/Toast';
import { Badge, Button } from '../ui/primitives';
import { AuthPlatformCard } from './AuthPlatformCard';

const ACCOUNT_LOGINS: Record<AccountLoginPlatform, { email: boolean; url: string }> = {
    cime: { email: true, url: 'https://ci.me/auth/login' },
    pandalive: { email: false, url: 'https://www.pandalive.co.kr/' },
    popkontv: { email: false, url: 'https://www.popkontv.com/' },
    hearheart: { email: true, url: 'https://hearheart.com/' },
};

/** Only registration/validation status is returned; cookie values never enter UI state. */
export function PlatformCookieAuth({ platform, onSaved }: { platform: CookiePlatform; onSaved?: () => void }) {
    const { t } = useLanguage();
    const toast = useToast();
    const confirm = useConfirm();
    const name = t(platform === 'tvchak' || platform === 'hearheart' ? DOWNLOAD_SOURCE_LABELS[platform] : PLATFORM_LABELS[platform]);
    const fileInput = useRef<HTMLInputElement>(null);
    const pending = useRef(false);
    const revision = useRef(0);
    const [status, setStatus] = useState<PlatformCookieStatus | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [method, setMethod] = useState<'account' | 'file'>('account');
    const accountPlatform = platform in ACCOUNT_LOGINS ? platform as AccountLoginPlatform : null;
    const account = accountPlatform ? ACCOUNT_LOGINS[accountPlatform] : null;
    useEffect(() => {
        let active = true;
        const current = revision.current;
        void api.getPlatformCookieStatus(platform).then(data => { if (active && current === revision.current) setStatus(data); })
            .catch(() => { if (active && current === revision.current) setError(t("settings.couldNotCheckCookieFileStatusTryAgain")); });
        return () => { active = false; };
    }, [platform]);
    const change = async (action: 'upload' | 'delete' | 'refresh' | 'login', file?: File) => {
        if (pending.current) return;
        revision.current += 1;
        pending.current = true;
        setBusy(true);
        setError('');
        try {
            const data = action === 'upload' && file ? await api.uploadPlatformCookie(platform, file)
                : action === 'login' && accountPlatform ? await api.loginPlatform(accountPlatform, username.trim(), password)
                : action === 'delete' ? await api.deletePlatformCookie(platform) : await api.checkPlatformCookies(platform);
            setStatus(data);
            if (action !== 'refresh') {
                toast.success(t(action === 'login' ? "settings.authLoginSuccess" : action === 'upload' ? "settings.cookieFileRegistered" : "settings.registeredCookiesRemoved"));
                onSaved?.();
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
    const label = !status ? t(error ? "settings.cookieFileNeedsAttention" : "live.checkingStatus") : status.expired ? t("settings.cookieExpired")
        : status.configured && status.valid === false ? t("settings.cookieFileNeedsAttention") : status.configured ? t("settings.cookiesRegistered") : t("settings.noRegisteredCookies");
    return <div className="auth-platform-card" data-cookie-platform={platform} aria-busy={busy}>
        <AuthPlatformCard platform={platform} title={t(name)}
            description={t(account ? "settings.authAccountOrCookie" : "settings.authCookieMethod")}
            onClose={() => setPassword('')}
            action={<Badge tone={status?.expired || (status?.configured && status.valid === false) ? 'warn' : status?.configured ? 'ok' : undefined}>{label}</Badge>}>
        <div className="space-y-4">
        {account && <div className="auth-methods" role="group" aria-label={t('settings.authMethod')}>
            <Button disabled={busy} aria-pressed={method === 'account'} onClick={() => { setMethod('account'); setPassword(''); }}>{t('settings.authAccountMethod')}</Button>
            <Button disabled={busy} aria-pressed={method === 'file'} onClick={() => { setMethod('file'); setPassword(''); }}>{t('settings.authCookieMethod')}</Button>
        </div>}
        {account && method === 'account' && <form data-account-login={platform} className="space-y-3"
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
            <p className="text-xs text-ink-muted">{t('settings.authPasswordHelp')}</p>
            {platform === 'cime' && <p className="text-xs text-ink-muted">{t('settings.cimeAccountLoginHelp')}</p>}
            <div className="flex flex-wrap items-center justify-between gap-2">
                <a href={account.url} target="_blank" rel="noopener noreferrer" className="text-xs text-accent hover:underline">
                    {t('settings.platformOpenLogin')}
                </a>
                <Button type="submit" loading={busy} disabled={busy || !username.trim() || !password}>{t('settings.authAccountMethod')}</Button>
            </div>
        </form>}
        <div className="flex flex-wrap items-center gap-2">
            <input ref={fileInput} type="file" accept=".txt" aria-label={`${name} ${t("settings.cookieFile")}`} className="hidden" disabled={busy} onChange={event => { const file = event.target.files?.[0]; if (file) void change('upload', file); }} />
            {(!account || method === 'file') && <Button icon={Upload} disabled={busy} onClick={() => fileInput.current?.click()} aria-label={`${name} ${t("settings.selectCookieFile")}`}>{t(status?.configured ? translate("settings.replaceFile") : translate("settings.chooseFile"))}</Button>}
            <Button icon={RefreshCw} loading={busy} onClick={() => void change('refresh')} aria-label={`${name} ${t("settings.checkCookieStatus")}`}>{t("settings.checkStatus")}</Button>
            {status?.configured && <Button variant="danger" icon={Trash2} disabled={busy} onClick={() => void remove()} aria-label={`${name} ${t("settings.removeCookieFile")}`}>{t("common.delete")}</Button>}
        </div>
        {(!account || method === 'file') && <p className="text-xs text-ink-muted">{t('settings.authCookieFileHelp')}</p>}
        {t(`settings.cookieHelp.${platform}`) !== `settings.cookieHelp.${platform}` ? (
            <p className="text-xs text-ink-muted">{t(`settings.cookieHelp.${platform}`)}</p>
        ) : platform === 'tvchak' ? (
            <p className="text-xs text-ink-muted">{t('settings.tvchakCookieHelp')}</p>
        ) : platform === 'kick' ? (
            <p className="text-xs text-ink-muted">{t('live.kickQualityAuthentication')}</p>
        ) : null}
        {status?.expired && <p className="text-xs text-warn">{t("settings.exportCookiesAgainFromASignedInBrowserAndRegisterTheFile")}</p>}
        </div>
        {error && <p role="alert" className="mt-2 text-xs text-danger [overflow-wrap:anywhere]">{t(error)}</p>}
        </AuthPlatformCard>
    </div>;
}
