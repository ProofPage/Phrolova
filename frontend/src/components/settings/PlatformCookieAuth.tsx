import { translate } from "../../i18n";
import { useEffect, useRef, useState } from 'react';
import { KeyRound, RefreshCw, Trash2, Upload } from 'lucide-react';
import { api, DOWNLOAD_SOURCE_LABELS, PLATFORM_LABELS, type CookiePlatform, type PlatformCookieStatus } from '../../api/client';
import { getErrorMessage, localizedStatus } from '../../utils/error';
import { useLanguage } from '../../contexts/LanguageContext';
import { useConfirm } from '../ui/ConfirmModal';
import { useToast } from '../ui/Toast';
import { Badge, Button, Card, CardHeader } from '../ui/primitives';

/** Only registration/validation status is returned; cookie values never enter UI state. */
export function PlatformCookieAuth({ platform, onSaved }: { platform: CookiePlatform; onSaved?: () => void }) {
    const { t } = useLanguage();
    const toast = useToast();
    const confirm = useConfirm();
    const name = t(platform === 'tvchak' || platform === 'hearheart' ? DOWNLOAD_SOURCE_LABELS[platform] : PLATFORM_LABELS[platform]);
    const fileInput = useRef<HTMLInputElement>(null);
    const pending = useRef(false);
    const [status, setStatus] = useState<PlatformCookieStatus | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    useEffect(() => {
        let active = true;
        void api.getPlatformCookieStatus(platform).then(data => { if (active) setStatus(data); })
            .catch(() => { if (active) setError(t("settings.couldNotCheckCookieFileStatusTryAgain")); });
        return () => { active = false; };
    }, [platform]);
    const change = async (action: 'upload' | 'delete' | 'refresh', file?: File) => {
        if (pending.current) return;
        pending.current = true;
        setBusy(true);
        setError('');
        try {
            const data = action === 'upload' && file ? await api.uploadPlatformCookie(platform, file)
                : action === 'delete' ? await api.deletePlatformCookie(platform) : await api.checkPlatformCookies(platform);
            setStatus(data);
            if (action !== 'refresh') {
                toast.success(t(action === 'upload' ? "settings.cookieFileRegistered" : "settings.registeredCookiesRemoved"));
                onSaved?.();
            }
        } catch (cause) {
            const message = getErrorMessage(cause, t("settings.couldNotProcessTheCookieFileTryAgain"));
            setError(message);
            toast.error(message);
        } finally {
            pending.current = false;
            setBusy(false);
            if (fileInput.current) fileInput.current.value = '';
        }
    };
    const remove = async () => {
        if (pending.current) return;
        if (await confirm({ title: `${name} ${t("settings.removeCookieFile")}`, message: t("settings.removeTheRegisteredCookiesPublicContentRemainsAvailableWithoutCookies"), confirmText: t("common.delete"), variant: 'danger' })) void change('delete');
    };
    const label = !status ? t("live.checkingStatus") : status.expired ? t("settings.cookieExpired")
        : status.configured && status.valid === false ? t("settings.cookieFileNeedsAttention") : status.configured ? t("settings.cookiesRegistered") : t("settings.noRegisteredCookies");
    return <Card className="space-y-4" data-cookie-platform={platform} aria-busy={busy}>
        <CardHeader icon={KeyRound} title={t(name)}
            action={<Badge tone={status?.expired || (status?.configured && status.valid === false) ? 'warn' : status?.configured ? 'ok' : undefined}>{label}</Badge>} />
        <div className="flex flex-wrap items-center gap-2">
            <input ref={fileInput} type="file" accept=".txt" aria-label={`${name} ${t("settings.cookieFile")}`} className="hidden" disabled={busy} onChange={event => { const file = event.target.files?.[0]; if (file) void change('upload', file); }} />
            <Button icon={Upload} disabled={busy} onClick={() => fileInput.current?.click()} aria-label={`${name} ${t("settings.selectCookieFile")}`}>{t(status?.configured ? translate("settings.replaceFile") : translate("settings.chooseFile"))}</Button>
            <Button icon={RefreshCw} loading={busy} onClick={() => void change('refresh')} aria-label={`${name} ${t("settings.checkCookieStatus")}`}>{t("settings.checkStatus")}</Button>
            {status?.configured && <Button variant="danger" icon={Trash2} disabled={busy} onClick={() => void remove()} aria-label={`${name} ${t("settings.removeCookieFile")}`}>{t("common.delete")}</Button>}
        </div>
        {status?.message && <p className="text-xs text-ink-muted [overflow-wrap:anywhere]" role="status">{localizedStatus(status.message, label)}</p>}
        {platform === 'tvchak' && <p className="text-xs text-ink-muted">{t('settings.tvchakCookieHelp')}</p>}
        {platform === 'kick' && <p className="text-xs text-ink-muted">{t('live.kickQualityAuthentication')}</p>}
        {status?.expired && <p className="text-xs text-warn">{t("settings.exportCookiesAgainFromASignedInBrowserAndRegisterTheFile")}</p>}
        {error && <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">{t(error)}</p>}
    </Card>;
}
