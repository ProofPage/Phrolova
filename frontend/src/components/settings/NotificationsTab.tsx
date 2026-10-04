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
    { value: "@here", label: "@here — 접속 중인 사람만" },
    { value: "@everyone", label: "@everyone — 서버 전체" },
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
            toast.success("알림 설정을 저장했습니다.");
            onSaved();
            setStatusRefreshSignal((n) => n + 1);
        } catch (e) {
            toast.error(getErrorMessage(e, "알림 설정 저장에 실패했습니다."));
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
                    description="Discord 채널 설정에서 URL 하나만 복사하면 끝납니다. 알림만 받을 거라면 이것으로 충분합니다."
                    action={
                        <div className="flex items-center gap-2">
                            <Badge tone="ok">권장</Badge>
                            <StatusDot
                                active={!!settings?.discord_webhook_configured}
                                label={settings?.discord_webhook_configured ? "설정됨" : "미설정"}
                                tone={settings?.discord_webhook_configured ? "ok" : "warn"}
                            />
                        </div>
                    }
                />

                <Field
                    label="Webhook URL"
                    htmlFor="webhook-url"
                    hint="Discord 채널 설정 → 연동 → 웹후크에서 만듭니다. Bot을 만들지 않아도 모든 알림이 정상 동작합니다."
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
                                ? "설정됨 — 변경하려면 입력"
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
                title="디스코드에서 원격 제어까지 하려면"
                description="Bot을 등록하면 /status, /start, /stop 같은 슬래시 커맨드로 녹화를 제어할 수 있습니다. 알림만 받을 거라면 설정하지 않아도 됩니다."
                defaultOpen={!!botReady}
                action={
                    // 봇은 선택 사항이므로 미설정을 경고로 보이지 않게 둔다.
                    // active=false면 tone과 무관하게 회색 점으로 렌더된다.
                    <StatusDot active={!!botReady} label={botReady ? "설정됨" : "미설정"} />
                }
            >
                <div className="space-y-4">
                    <Field
                        label="Bot 토큰"
                        htmlFor="bot-token"
                        hint="비워두면 기존 토큰을 유지합니다. Discord Developer Portal에서 발급받으세요. 토큰 변경은 재시작 후 적용됩니다."
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
                            placeholder={settings?.discord_bot_configured ? "설정됨 — 변경하려면 입력" : "Bot 토큰"}
                        />
                    </Field>

                    <Field
                        label="알림 채널 ID"
                        htmlFor="channel-id"
                        hint="Discord에서 개발자 모드를 켠 뒤 채널 우클릭 → 'ID 복사'로 얻은 숫자입니다."
                    >
                        <Input
                            id="channel-id"
                            inputMode="numeric"
                            value={channelId || settings?.discord_notification_channel_id || ""}
                            onChange={(e) => {
                                setChannelId(e.target.value);
                                markDirty();
                            }}
                            placeholder="예: 1234567890123456789"
                        />
                    </Field>

                    <Field
                        label="명령어 허용 사용자 ID"
                        htmlFor="command-user-ids"
                        hint="쉼표로 구분합니다. 비워두면 사용자 제한 없이 채널 조건만 적용됩니다."
                    >
                        <Input
                            id="command-user-ids"
                            value={commandUserIds}
                            onChange={(e) => {
                                setCommandUserIds(e.target.value);
                                markDirty();
                            }}
                            placeholder="예: 1234567890123456789, 9876543210987654321"
                        />
                    </Field>

                    <Field
                        label="명령어 허용 채널 ID"
                        htmlFor="command-channel-id"
                        hint="비워두면 위 알림 채널에서만 명령어가 동작합니다. 셋 다 비어 있으면 모든 명령어가 거부됩니다."
                    >
                        <Input
                            id="command-channel-id"
                            inputMode="numeric"
                            value={commandChannelId}
                            onChange={(e) => {
                                setCommandChannelId(e.target.value);
                                markDirty();
                            }}
                            placeholder="예: 1234567890123456789"
                        />
                    </Field>
                </div>
            </CollapsibleCard>


            {/* ══ 알림 종류 ═════════════════════════════ */}
            <Card>
                <CardHeader
                    icon={Bell}
                    title="받을 알림"
                    description="꺼둔 종류는 아예 전송되지 않습니다."
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
                                전체 선택
                            </Button>
                            <Button
                                variant="ghost"
                                className="px-3 py-1.5 text-[13px]"
                                onClick={() => {
                                    setEnabledKinds(new Set());
                                    markDirty();
                                }}
                            >
                                전체 해제
                            </Button>
                        </div>
                    }
                />

                <div className="divide-y divide-line">
                    {kinds.map((kind) => (
                        <SettingRow
                            key={kind.value}
                            label={kind.label}
                            control={
                                <Switch
                                    label={kind.label}
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
                    title="멘션"
                    description="놓치면 안 되는 알림에만 멘션을 붙이세요."
                />

                <div className="space-y-4">
                    <Field
                        label="멘션 대상"
                        htmlFor="mention-target"
                        hint="역할을 멘션하려면 <@&역할ID> 형식으로 직접 입력합니다."
                    >
                        <div className="flex flex-wrap gap-2 mb-2">
                            {MENTION_PRESETS.map((p) => (
                                <button
                                    key={p.value}
                                    type="button"
                                    onClick={() => {
                                        setMentionTarget(p.value);
                                        markDirty();
                                    }}
                                    className={
                                        "px-3 py-1.5 rounded-[var(--radius-control)] text-[13px] font-medium border transition-colors " +
                                        (mentionTarget === p.value
                                            ? "btn-ghost-primary border-transparent"
                                            : "bg-surface-3 border-line-strong text-ink-faint hover:text-ink-muted")
                                    }
                                >
                                    {p.label}
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
                            멘션을 붙일 알림
                        </p>
                        <p className="text-xs text-ink-faint mb-3">
                            아무것도 고르지 않으면 멘션 없이 전송됩니다.
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
                                        title={disabled ? "이 알림이 꺼져 있습니다" : undefined}
                                        onClick={() =>
                                            toggleKind(kind.value, mentionKinds, setMentionKinds)
                                        }
                                        className={
                                            "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[13px] font-medium border transition-colors disabled:opacity-35 disabled:cursor-not-allowed " +
                                            (on
                                                ? "btn-ghost-primary border-transparent"
                                                : "bg-surface-3 border-line-strong text-ink-faint hover:text-ink-muted")
                                        }
                                    >
                                        {on && <BellRing className="w-3 h-3" />}
                                        {kind.label}
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
                    title="고급"
                    description="전송이 밀렸을 때의 동작을 조정합니다."
                />

                <Field
                    label="알림 유효 시간 (분)"
                    htmlFor="ttl"
                    hint="이 시간을 넘긴 알림은 뒷북이 되므로 전송하지 않고 버립니다. 연결이 오래 끊겼다가 복구됐을 때 지난 알림이 쏟아지는 걸 막습니다."
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
            <div className="sticky bottom-0 -mx-1 px-1 pb-1 pt-3 bg-gradient-to-t from-surface-0 via-surface-0 to-transparent">
                <Button
                    variant="primary"
                    icon={Save}
                    loading={saving}
                    onClick={handleSave}
                    className="w-full"
                >
                    {dirty ? "변경사항 저장" : "저장됨"}
                </Button>
            </div>
        </div>
    );
}
