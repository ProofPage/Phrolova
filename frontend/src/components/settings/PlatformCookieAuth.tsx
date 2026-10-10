import { useEffect, useRef, useState } from 'react';
import { KeyRound, RefreshCw, Trash2, Upload } from 'lucide-react';
import { api, PLATFORM_LABELS, type PlatformCookieStatus } from '../../api/client';
import { getErrorMessage } from '../../utils/error';
import { useLanguage } from '../../contexts/LanguageContext';
import { useConfirm } from '../ui/ConfirmModal';
import { useToast } from '../ui/Toast';
import { Badge, Button, Card, CardHeader } from '../ui/primitives';

/** Cookie values stay in the uploaded file; only file status is returned to this UI. */
export function PlatformCookieAuth({ platform, onSaved }: { platform: 'soop' | 'cime'; onSaved?: () => void }) {
    const { t } = useLanguage();
    const toast = useToast();
    const confirm = useConfirm();
    const name = PLATFORM_LABELS[platform];
    const fileInput = useRef<HTMLInputElement>(null);
    const pending = useRef(false);
    const [status, setStatus] = useState<PlatformCookieStatus | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    useEffect(() => {
        let active = true;
        void api.getPlatformCookieStatus(platform).then(data => { if (active) setStatus(data); })
            .catch(() => { if (active) setError(t('쿠키 파일 상태를 확인하지 못했습니다. 다시 확인하세요.')); });
        return () => { active = false; };
    }, [platform]);
    const change = async (action: 'upload' | 'delete' | 'refresh', file?: File) => {
        if (pending.current) return;
        pending.current = true;
        setBusy(true);
        setError('');
        try {
            const data = action === 'upload' && file ? await api.uploadPlatformCookie(platform, file)
                : action === 'delete' ? await api.deletePlatformCookie(platform) : await api.getPlatformCookieStatus(platform);
            setStatus(data);
            if (action !== 'refresh') {
                toast.success(t(action === 'upload' ? '쿠키 파일을 등록했습니다.' : '쿠키 파일이 삭제되었습니다.'));
                onSaved?.();
            }
        } catch (cause) {
            const message = getErrorMessage(cause, t('쿠키 파일 처리에 실패했습니다. 다시 시도하세요.'));
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
        if (await confirm({ title: `${name} ${t('쿠키 파일 삭제')}`, message: t('등록된 쿠키 파일을 삭제하시겠습니까? 공개 콘텐츠는 쿠키 없이 이용할 수 있습니다.'), confirmText: t('삭제'), variant: 'danger' })) void change('delete');
    };
    const label = !status ? t('상태 확인 중') : status.expired ? t('쿠키 만료')
        : status.configured && status.valid === false ? t('쿠키 파일 확인 필요') : status.configured ? t('쿠키 파일 등록됨') : t('등록된 쿠키 없음');
    return <Card className="space-y-4" data-cookie-platform={platform} aria-busy={busy}>
        <CardHeader icon={KeyRound} title={t(name)} description={t('선택 사항 · 공개 콘텐츠는 쿠키 없이 이용합니다. 로그인이 필요한 콘텐츠에 사용할 Netscape 형식 쿠키 파일을 등록하세요.')}
            action={<Badge tone={status?.expired || (status?.configured && status.valid === false) ? 'warn' : status?.configured ? 'ok' : undefined}>{label}</Badge>} />
        <div className="flex flex-wrap items-center gap-2">
            <input ref={fileInput} type="file" accept=".txt" aria-label={`${name} ${t('쿠키 파일')}`} className="hidden" disabled={busy} onChange={event => { const file = event.target.files?.[0]; if (file) void change('upload', file); }} />
            <Button icon={Upload} disabled={busy} onClick={() => fileInput.current?.click()} aria-label={`${name} ${t('쿠키 파일 선택')}`}>{t(status?.configured ? '파일 갱신' : '파일 선택')}</Button>
            <Button icon={RefreshCw} loading={busy} onClick={() => void change('refresh')} aria-label={`${name} ${t('쿠키 상태 확인')}`}>{t('상태 확인')}</Button>
            {status?.configured && <Button variant="danger" icon={Trash2} disabled={busy} onClick={() => void remove()} aria-label={`${name} ${t('쿠키 파일 삭제')}`}>{t('삭제')}</Button>}
        </div>
        {status?.message && <p className="text-xs text-ink-muted [overflow-wrap:anywhere]" role="status">{t(status.message)}</p>}
        {status?.expired && <p className="text-xs text-warn">{t('로그인한 브라우저에서 쿠키 파일을 다시 내보내 등록하세요.')}</p>}
        {error && <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">{error}</p>}
    </Card>;
}
