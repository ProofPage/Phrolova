import { translate } from "../../i18n";
/**
 * 알림 전송 진단 카드.
 *
 * 알림 설정 탭에서 유일하게 폼과 무관한 조각이다. 무엇을 저장할지가 아니라
 * "지금 실제로 나가고 있는지"만 보여주므로, 상태 조회와 주기 갱신을 스스로 들고 있다.
 * 덕분에 설정 탭은 폼에만 집중한다.
 */
import { useCallback, useEffect, useState } from "react";
import { Activity, CheckCircle2, RefreshCcw, Send } from "lucide-react";
import {
    api,
    type NotificationStatus,
    type Settings as SettingsType,
} from "../../api/client";
import { useToast } from "../ui/Toast";
import { useLanguage } from "../../contexts/LanguageContext";
import { getErrorMessage, localizedStatus } from "../../utils/error";
import { Badge, Button, Card, CardHeader, Divider } from "../ui/primitives";

/** 전송 채널 이름을 사람이 읽을 문구로. */
const TRANSPORT_LABELS: Record<string, string> = {
    discord_bot: "Discord Bot",
    webhook: "Webhook",
};

interface Props {
    settings: SettingsType | null;
    /**
     * 값이 바뀌면 즉시 다시 조회한다.
     *
     * 설정을 저장한 직후에는 5초 주기를 기다리지 않고 바로 반영돼야 한다.
     * 부모가 refreshStatus를 직접 부르게 하면 이 카드가 상태를 소유할 수 없어,
     * "지금 갱신하라"는 신호만 받는다.
     */
    refreshSignal: number;
}

export function NotificationDeliveryCard({ settings, refreshSignal }: Props) {
    const toast = useToast();
    const { t } = useLanguage();
    const [status, setStatus] = useState<NotificationStatus | null>(null);
    const [testing, setTesting] = useState(false);

    const refreshStatus = useCallback(async () => {
        try {
            setStatus(await api.getNotificationStatus());
        } catch {
            setStatus({ available: false, reason: "settings.couldNotLoadStatus" });
        }
    }, []);

    useEffect(() => {
        refreshStatus();
        // 큐가 비워지는 걸 볼 수 있도록 주기적으로 갱신한다.
        const timer = setInterval(refreshStatus, 5000);
        return () => clearInterval(timer);
    }, [refreshStatus]);

    // 저장 직후처럼 부모가 즉시 갱신을 요청했을 때.
    useEffect(() => {
        if (refreshSignal > 0) refreshStatus();
    }, [refreshSignal, refreshStatus]);

    const handleTest = async () => {
        setTesting(true);
        try {
            const res = await api.sendTestNotification();
            toast.success(localizedStatus(res.message, 'settings.testNotificationSent'));
            refreshStatus();
        } catch (e) {
            toast.error(getErrorMessage(e, "settings.couldNotSendTestNotification"));
        } finally {
            setTesting(false);
        }
    };

    const botReady = settings?.discord_bot_configured && !!settings?.discord_notification_channel_id;
    const anyTransport = botReady || settings?.discord_webhook_configured;

    return (
        <Card>
            <CardHeader
                icon={Activity}
                title={translate("settings.connectionStatus")}
                description={translate("settings.checkWhetherNotificationsAreBeingDelivered")}
                action={
                    <div className="flex items-center gap-2">
                        <Button
                            variant="ghost"
                            icon={RefreshCcw}
                            onClick={refreshStatus}
                            aria-label={t("settings.refreshStatus")}
                        />
                        <Button
                            variant="primary"
                            icon={Send}
                            loading={testing}
                            disabled={!anyTransport}
                            onClick={handleTest}
                        >
                            {translate("settings.sendTest")}</Button>
                    </div>
                }
            />

            {!anyTransport && (
                <p className="text-[13px] text-warn bg-warn/10 border border-warn/20 rounded-[var(--radius-control)] px-3 py-2.5 mb-4">
                    {t("settings.setEitherABotTokenAndChannelIDOrAWebhookURLToSendNotifications")}
                </p>
            )}

            <div className="grid gap-3 sm:grid-cols-2">
                {(status?.transports ?? []).map((transport) => (
                    <div
                        key={transport.name}
                        className="flex items-center justify-between gap-3 bg-surface-3 border border-line rounded-[var(--radius-control)] px-3.5 py-3"
                    >
                        <span className="text-[13px] font-medium text-ink">
                            {t(TRANSPORT_LABELS[transport.name] ?? transport.name)}
                        </span>
                        {!transport.configured ? (
                            <Badge tone="neutral">{translate("settings.notConfigured")}</Badge>
                        ) : transport.available ? (
                            <Badge tone="ok">
                                <CheckCircle2 className="w-3 h-3" />
                                {t("settings.connected")}
                            </Badge>
                        ) : (
                            <Badge tone="warn">{translate("settings.waiting")}</Badge>
                        )}
                    </div>
                ))}
            </div>

            {status?.available && (
                <>
                    <Divider className="my-4" />
                    <dl className="notification-delivery-summary">
                        {[
                            { label: translate("settings.queued"), value: status.pending ?? 0, tone: (status.pending ?? 0) > 0 ? "warn" : undefined },
                            { label: translate("settings.delivered"), value: status.delivered ?? 0 },
                            { label: translate("settings.dropped"), value: status.dropped ?? 0, tone: (status.dropped ?? 0) > 0 ? "danger" : undefined },
                            { label: translate("settings.expired"), value: status.expired ?? 0 },
                        ].map((s) => (
                            <div key={s.label}>
                                <dt className="text-[11px] uppercase tracking-wide text-ink-faint">
                                    {t(s.label)}
                                </dt>
                                <dd
                                    className="text-lg font-semibold mt-0.5"
                                    style={{
                                        color:
                                            s.tone === "danger" ? "var(--color-danger)"
                                            : s.tone === "warn" ? "var(--color-warn)"
                                            : "var(--color-ink)",
                                    }}
                                >
                                    {s.value}
                                </dd>
                            </div>
                        ))}
                    </dl>
                    <p className="text-xs text-ink-faint mt-3 leading-relaxed">
                        {translate("settings.pendingNotificationsAreSentAutomaticallyWhenTheConnectionReturnsTheyAreKeptAcrossAppRestarts")}</p>
                </>
            )}
        </Card>
    );
}
