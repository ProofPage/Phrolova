import { translate } from "../../i18n";
/**
 * 알림 설정 탭.
 *
 * 백엔드 알림 파이프라인(큐 + 재시도 + 웹훅 폴백 + 종류별 필터)을
 * 화면에서 전부 제어한다. 이전에는 Bot 토큰과 채널 ID만 입력할 수 있어
 * 나머지는 .env를 직접 고쳐야 했다.
 */
import { useCallback, useEffect, useState } from "react";
import {
    AtSign,
    Bell,
    BellRing,
    Bot,
    RefreshCcw,
    Save,
    Webhook,
} from "lucide-react";
import {
    api,
    type NotificationKindInfo,
    type Settings as SettingsType,
} from "../../api/client";
import { useToast } from "../ui/Toast";
import { useLanguage } from "../../contexts/LanguageContext";
import { NotificationDeliveryCard } from "./NotificationDeliveryCard";
import { getErrorMessage } from "../../utils/error";
import {
    Badge,
    Button,
    Card,
    CardHeader,
    CollapsibleCard,
    Divider,
    Field,
    Input,
    SettingRow,
    StatusDot,
    Switch,
} from "../ui/primitives";

/** 멘션 대상 프리셋. 역할 멘션은 직접 입력한다. */
const MENTION_PRESETS = [
    { value: "@here", label: "settings.hereOnlineMembersOnly" },
    { value: "@everyone", label: "settings.everyoneEntireServer" },
];

interface Props {
    settings: SettingsType | null;
    /** 저장 후 상위의 설정 상태를 갱신한다. */
    onSaved: () => void;
    /** 변경사항 유무를 상위 탭 전환 경고에 알린다. */
    onDirtyChange?: (dirty: boolean) => void;
}

export function NotificationsTab({ settings, onSaved, onDirtyChange }: Props) {
    const toast = useToast();
    const { t } = useLanguage();

    // ── 폼 상태 ──────────────────────────────────────
    const [botToken, setBotToken] = useState("");
    const [channelId, setChannelId] = useState("");
    const [commandUserIds, setCommandUserIds] = useState("");
    const [commandChannelId, setCommandChannelId] = useState("");
    const [webhookUrl, setWebhookUrl] = useState("");
    const [enabledKinds, setEnabledKinds] = useState<Set<string>>(new Set());
    const [mentionKinds, setMentionKinds] = useState<Set<string>>(new Set());
    const [mentionTarget, setMentionTarget] = useState("@here");
    const [ttlMinutes, setTtlMinutes] = useState(60);

    const [saving, setSaving] = useState(false);
    const [dirty, setDirty] = useState(false);
    // 저장 직후 진단 카드가 5초 주기를 기다리지 않고 바로 다시 조회하도록 하는 신호.
    const [statusRefreshSignal, setStatusRefreshSignal] = useState(0);

    const kinds: NotificationKindInfo[] = settings?.notification_kinds ?? [];

    // ── 서버 값으로 폼 초기화 ────────────────────────
    useEffect(() => {
        if (!settings) return;

        const allValues = (settings.notification_kinds ?? []).map((k) => k.value);
        const notify = settings.discord_notify_events ?? ["all"];
        // "all"은 전체 선택으로 펼쳐서 체크박스에 반영한다.
        setEnabledKinds(
            new Set(notify.includes("all") ? allValues : notify.filter((v) => v !== "none")),
        );
        setCommandUserIds(settings.discord_command_user_ids || "");
        setCommandChannelId(settings.discord_command_channel_id || "");
        setMentionKinds(new Set(settings.discord_mention_events ?? []));
        setMentionTarget(settings.discord_mention_target || "@here");
        setTtlMinutes(Math.round((settings.discord_notify_ttl ?? 3600) / 60));
        setDirty(false);
    }, [settings]);

    const markDirty = useCallback(() => {
        setDirty(true);
        onDirtyChange?.(true);
    }, [onDirtyChange]);

    // ── 핸들러 ───────────────────────────────────────
    const toggleKind = (value: string, set: Set<string>, apply: (s: Set<string>) => void) => {
        const next = new Set(set);
        next.has(value) ? next.delete(value) : next.add(value);
        apply(next);
        markDirty();
    };

    const handleSave = async () => {
        setSaving(true);
        try {
            const allSelected = kinds.length > 0 && enabledKinds.size === kinds.length;
            await api.updateDiscordSettings({
                // 토큰과 웹훅 URL은 입력했을 때만 보낸다 (빈 값으로 덮어쓰지 않도록).
                ...(botToken.trim() ? { discord_bot_token: botToken.trim() } : {}),
                ...(webhookUrl.trim() ? { discord_webhook_url: webhookUrl.trim() } : {}),
                discord_notification_channel_id: channelId.trim() || undefined,
                // 빈 문자열도 그대로 보낸다 — 허용 목록을 지우는 조작이어야 하므로.
                discord_command_user_ids: commandUserIds.trim(),
                discord_command_channel_id: commandChannelId.trim(),
                discord_notify_events: allSelected ? ["all"] : [...enabledKinds],
                discord_mention_events: [...mentionKinds],
                discord_mention_target: mentionTarget,
                discord_notify_ttl: Math.max(60, ttlMinutes * 60),
            });
            setBotToken("");
            setWebhookUrl("");
            setDirty(false);
            onDirtyChange?.(false);
            toast.success("settings.notificationSettingsSaved");
            onSaved();
            setStatusRefreshSignal((n) => n + 1);
        } catch (e) {
            toast.error(getErrorMessage(e, "settings.couldNotSaveNotificationSettings"));
        } finally {
            setSaving(false);
        }
    };

    const botReady = settings?.discord_bot_configured && !!settings?.discord_notification_channel_id;

    return (
        <div className="space-y-5">
            <NotificationDeliveryCard settings={settings} refreshSignal={statusRefreshSignal} />

            {/* ══ Webhook — 기본 알림 경로 ═════════════ */}
            <Card>
                <CardHeader
                    icon={Webhook}
                    title="Webhook"
                    action={
                        <div className="flex items-center gap-2">
                            <Badge tone="ok">{translate("settings.recommended")}</Badge>
                            <StatusDot
                                active={!!settings?.discord_webhook_configured}
                                label={settings?.discord_webhook_configured ? translate("settings.configured") : translate("settings.notConfigured")}
                                tone={settings?.discord_webhook_configured ? "ok" : "warn"}
                            />
                        </div>
                    }
                />

                <Field
                    label="Webhook URL"
                    htmlFor="webhook-url"
                    hint={translate("settings.createThisInDiscordChannelSettingsIntegrationsWebhooksNotificationsWorkWithoutCreatingABot")}
                >
                    <Input
                        id="webhook-url"
                        type="password"
                        autoComplete="off"
                        value={webhookUrl}
                        onChange={(e) => {
                            setWebhookUrl(e.target.value);
                            markDirty();
                        }}
                        placeholder={
                            settings?.discord_webhook_configured
                                ? translate("settings.configuredEnterANewValueToChange")
                                : "https://discord.com/api/webhooks/..."
                        }
                    />
                </Field>
            </Card>

            {/* ══ Discord Bot — 원격 제어용 (선택) ══════ */}
            {/*
              Bot은 개발자 포털에서 앱을 만들어야 해서 진입 장벽이 높다.
              대부분은 위 Webhook으로 충분하므로 접어두고, 이미 설정한
              사용자에게는 펼친 채로 보여준다.
            */}
            <CollapsibleCard
                icon={Bot}
                title={t("settings.forRemoteControlThroughDiscord")}
                description={t("settings.registerABotToControlRecordingsWithSlashCommandsSuchAsStatusStartAndStopYouCanLeaveThisUnsetIfYouOnlyNeedNotifications")}
                defaultOpen={!!botReady}
                action={
                    // 봇은 선택 사항이므로 미설정을 경고로 보이지 않게 둔다.
                    // active=false면 tone과 무관하게 회색 점으로 렌더된다.
                    <StatusDot active={!!botReady} label={botReady ? translate("settings.configured") : translate("settings.notConfigured")} />
                }
            >
                <div className="space-y-4">
                    <Field
                        label={translate("settings.botToken")}
                        htmlFor="bot-token"
                        hint={translate("settings.leaveThisBlankToKeepTheCurrentTokenGetOneFromTheDiscordDeveloperPortalTokenChangesTakeEffectAfterRestarting")}
                    >
                        <Input
                            id="bot-token"
                            type="password"
                            autoComplete="off"
                            value={botToken}
                            onChange={(e) => {
                                setBotToken(e.target.value);
                                markDirty();
                            }}
                            placeholder={settings?.discord_bot_configured ? translate("settings.configuredEnterANewValueToChange") : translate("settings.botToken")}
                        />
                    </Field>

                    <Field
                        label={translate("settings.notificationChannelID")}
                        htmlFor="channel-id"
                        hint={translate("settings.enableDeveloperModeInDiscordThenRightClickTheChannelAndChooseCopyID")}
                    >
                        <Input
                            id="channel-id"
                            inputMode="numeric"
                            value={channelId || settings?.discord_notification_channel_id || ""}
                            onChange={(e) => {
                                setChannelId(e.target.value);
                                markDirty();
                            }}
                            placeholder={translate("settings.eG1234567890123456789")}
                        />
                    </Field>

                    <Field
                        label={translate("settings.allowedUserIDsForCommands")}
                        htmlFor="command-user-ids"
                        hint={translate("settings.separateIDsWithCommasLeaveBlankToRestrictCommandsByChannelOnly")}
                    >
                        <Input
                            id="command-user-ids"
                            value={commandUserIds}
                            onChange={(e) => {
                                setCommandUserIds(e.target.value);
                                markDirty();
                            }}
                            placeholder={translate("settings.eG12345678901234567899876543210987654321")}
                        />
                    </Field>

                    <Field
                        label={translate("settings.allowedChannelIDForCommands")}
                        htmlFor="command-channel-id"
                        hint={translate("settings.leaveBlankToAllowCommandsOnlyInTheNotificationChannelAboveIfAllThreeFieldsAreEmptyEveryCommandIsRejected")}
                    >
                        <Input
                            id="command-channel-id"
                            inputMode="numeric"
                            value={commandChannelId}
                            onChange={(e) => {
                                setCommandChannelId(e.target.value);
                                markDirty();
                            }}
                            placeholder={translate("settings.eG1234567890123456789")}
                        />
                    </Field>
                </div>
            </CollapsibleCard>


            {/* ══ 알림 종류 ═════════════════════════════ */}
            <Card>
                <CardHeader
                    icon={Bell}
                    title={translate("settings.notificationsToReceive")}
                    action={
                        <div className="flex gap-2">
                            <Button
                                variant="ghost"
                                className="px-3 py-1.5 text-[13px]"
                                onClick={() => {
                                    setEnabledKinds(new Set(kinds.map((k) => k.value)));
                                    markDirty();
                                }}
                            >
                                {translate("settings.selectAll")}</Button>
                            <Button
                                variant="ghost"
                                className="px-3 py-1.5 text-[13px]"
                                onClick={() => {
                                    setEnabledKinds(new Set());
                                    markDirty();
                                }}
                            >
                                {translate("settings.clearAll")}</Button>
                        </div>
                    }
                />

                <div className="divide-y divide-line">
                    {kinds.map((kind) => (
                        <SettingRow
                            key={kind.value}
                            label={t(`settings.notification.${kind.value}`)}
                            control={
                                <Switch
                                    label={t(`settings.notification.${kind.value}`)}
                                    checked={enabledKinds.has(kind.value)}
                                    onChange={() =>
                                        toggleKind(kind.value, enabledKinds, setEnabledKinds)
                                    }
                                />
                            }
                        />
                    ))}
                </div>
            </Card>

            {/* ══ 멘션 ══════════════════════════════════ */}
            <Card>
                <CardHeader
                    icon={AtSign}
                    title={translate("settings.mentions")}
                    description={translate("settings.useMentionsOnlyForNotificationsYouCannotAffordToMiss")}
                />

                <div className="space-y-4">
                    <Field
                        label={translate("settings.mentionTarget")}
                        htmlFor="mention-target"
                        hint={translate("settings.toMentionARoleEnterItsIDInTheFormatRoleId")}
                    >
                        <div className="flex flex-wrap gap-2 mb-2">
                            {MENTION_PRESETS.map((p) => (
                                <button
                                    key={p.value}
                                    type="button"
                                    aria-pressed={mentionTarget === p.value}
                                    onClick={() => {
                                        setMentionTarget(p.value);
                                        markDirty();
                                    }}
                                    className={
                                        "ui-chip px-3 py-1.5 rounded-[var(--radius-control)] text-[13px] font-medium border transition-colors " +
                                        (mentionTarget === p.value
                                            ? "btn-ghost-primary border-transparent"
                                            : "bg-surface-3 border-line-strong text-ink-faint hover:text-ink-muted")
                                    }
                                >
                                    {t(p.label)}
                                </button>
                            ))}
                        </div>
                        <Input
                            id="mention-target"
                            value={mentionTarget}
                            onChange={(e) => {
                                setMentionTarget(e.target.value);
                                markDirty();
                            }}
                            placeholder="@here"
                        />
                    </Field>

                    <Divider />

                    <div>
                        <p className="text-[13px] font-medium text-ink-muted mb-1">
                            {t("settings.notificationsToMention")}
                        </p>
                        <p className="text-xs text-ink-faint mb-3">
                            {t("settings.notificationsAreSentWithoutAMentionIfNoneAreSelected")}
                        </p>
                        <div className="flex flex-wrap gap-2">
                            {kinds.map((kind) => {
                                const on = mentionKinds.has(kind.value);
                                const disabled = !enabledKinds.has(kind.value);
                                return (
                                    <button
                                        key={kind.value}
                                        type="button"
                                        disabled={disabled}
                                        aria-pressed={on}
                                        title={disabled ? translate("settings.thisNotificationIsDisabled") : undefined}
                                        onClick={() =>
                                            toggleKind(kind.value, mentionKinds, setMentionKinds)
                                        }
                                        className={
                                            "ui-chip inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[13px] font-medium border transition-colors disabled:opacity-35 disabled:cursor-not-allowed " +
                                            (on
                                                ? "btn-ghost-primary border-transparent"
                                                : "bg-surface-3 border-line-strong text-ink-faint hover:text-ink-muted")
                                        }
                                    >
                                        {on && <BellRing className="w-3 h-3" />}
                                        {t(`settings.notification.${kind.value}`)}
                                    </button>
                                );
                            })}
                        </div>
                    </div>
                </div>
            </Card>

            {/* ══ 고급 ══════════════════════════════════ */}
            <Card>
                <CardHeader
                    icon={RefreshCcw}
                    title={translate("settings.advanced")}
                />

                <Field
                    label={translate("settings.notificationExpirationMinutes")}
                    htmlFor="ttl"
                    hint={translate("settings.olderNotificationsAreDiscardedInsteadOfBeingDeliveredLateThisPreventsAFloodOfStaleAlertsAfterALongOutage")}
                >
                    <Input
                        id="ttl"
                        type="number"
                        min={1}
                        max={1440}
                        value={ttlMinutes}
                        onChange={(e) => {
                            setTtlMinutes(Number(e.target.value));
                            markDirty();
                        }}
                        className="max-w-[160px]"
                    />
                </Field>
            </Card>

            {/* ══ 저장 ══════════════════════════════════ */}
            <div className="settings-save sticky bottom-0 -mx-1 px-1 pb-1 pt-3 bg-surface-0">
                <Button
                    variant="primary"
                    icon={Save}
                    loading={saving}
                    disabled={!dirty}
                    onClick={handleSave}
                    className="w-full"
                >
                    {translate("settings.saveChanges")}
                </Button>
            </div>
        </div>
    );
}
