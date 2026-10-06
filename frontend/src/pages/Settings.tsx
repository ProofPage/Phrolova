import { useCallback, useEffect, useState } from "react";
import { useBlocker } from "react-router-dom";
import {
    Bell,
    AlertCircle,
    Download,
    Info,
    KeyRound,
    MonitorCog,
    Palette,
    Loader2,
    RefreshCw,
    Settings as SettingsIcon,
    type LucideIcon,
} from "lucide-react";
import { api, type Settings as SettingsType } from "../api/client";
import { AppearanceTab } from "../components/settings/AppearanceTab";
import { AuthTab } from "../components/settings/AuthTab";
import { DownloadTab } from "../components/settings/DownloadTab";
import { GeneralTab } from "../components/settings/GeneralTab";
import { InfoTab } from "../components/settings/InfoTab";
import { NotificationsTab } from "../components/settings/NotificationsTab";
import { SystemTab } from "../components/settings/SystemTab";
import { useConfirm } from "../components/ui/ConfirmModal";
import { Badge, Button, Card, PageHeader } from "../components/ui/primitives";
import { useLanguage } from "../contexts/LanguageContext";

type TabId = "general" | "download" | "auth" | "notifications" | "appearance" | "system" | "info";

const TABS: { id: TabId; label: string; icon: LucideIcon }[] = [
    { id: "general", label: "일반", icon: SettingsIcon },
    { id: "download", label: "다운로드", icon: Download },
    { id: "auth", label: "인증", icon: KeyRound },
    { id: "notifications", label: "알림", icon: Bell },
    { id: "appearance", label: "외관", icon: Palette },
    { id: "system", label: "시스템", icon: MonitorCog },
    { id: "info", label: "정보", icon: Info },
];

const EMPTY_DIRTY: Record<TabId, boolean> = {
    general: false,
    download: false,
    auth: false,
    notifications: false,
    appearance: false,
    system: false,
    info: false,
};

export default function Settings() {
    const { t } = useLanguage();
    const [settings, setSettings] = useState<SettingsType | null>(null);
    const [loadError, setLoadError] = useState(false);
    const [activeTab, setActiveTab] = useState<TabId>("general");
    const [dirtyTabs, setDirtyTabs] = useState<Record<TabId, boolean>>(EMPTY_DIRTY);
    const [updateAvailable, setUpdateAvailable] = useState(false);
    const confirm = useConfirm();

    const loadSettings = useCallback(async () => {
        setLoadError(false);
        try {
            setSettings(await api.getSettings());
        } catch {
            setLoadError(true);
        }
    }, []);

    useEffect(() => {
        loadSettings();
        // 시스템 탭을 열기 전에도 새 버전 표시를 놓치지 않도록 상태를 미리 읽는다.
        api.getUpdateStatus()
            .then((info) => setUpdateAvailable(info.has_update))
            .catch(() => {});
    }, [loadSettings]);

    const setTabDirty = useCallback((tab: TabId, dirty: boolean) => {
        setDirtyTabs((current) => current[tab] === dirty ? current : { ...current, [tab]: dirty });
    }, []);

    const hasDirtyTab = TABS.some((tab) => dirtyTabs[tab.id]);

    const handleTabChange = async (newTab: TabId) => {
        if (activeTab === newTab) return;
        if (dirtyTabs[activeTab]) {
            const ok = await confirm({
                title: "저장되지 않은 변경사항",
                message: "현재 탭에 저장하지 않은 설정이 있습니다. 이동하시겠습니까?\n이동하면 변경사항은 초기화됩니다.",
                confirmText: "이동",
                variant: "danger",
            });
            if (!ok) return;

            setTabDirty(activeTab, false);
            loadSettings();
        }
        setActiveTab(newTab);
    };

    const blocker = useBlocker(
        ({ currentLocation, nextLocation }) =>
            currentLocation.pathname !== nextLocation.pathname && hasDirtyTab,
    );

    useEffect(() => {
        if (blocker.state !== "blocked") return;
        confirm({
            title: "저장되지 않은 변경사항",
            message: "저장하지 않은 설정이 있습니다. 페이지를 이동하시겠습니까?\n이동하면 변경사항은 초기화됩니다.",
            confirmText: "이동",
            variant: "danger",
        }).then((ok) => ok ? blocker.proceed() : blocker.reset());
    }, [blocker.state]);

    useEffect(() => {
        const warnBeforeUnload = (event: BeforeUnloadEvent) => {
            if (!hasDirtyTab) return;
            event.preventDefault();
            event.returnValue = "";
        };
        window.addEventListener("beforeunload", warnBeforeUnload);
        return () => window.removeEventListener("beforeunload", warnBeforeUnload);
    }, [hasDirtyTab]);

    return (
        <div className="product-page settings-page space-y-4">
            <PageHeader
                icon={SettingsIcon}
                title={t("설정")}
                description={t("녹화, 다운로드, 인증, 알림 및 애플리케이션 동작을 구성합니다.")}
                meta={hasDirtyTab || updateAvailable ? (
                    <>
                        {hasDirtyTab && <Badge tone="warn">{t("저장하지 않은 변경사항")}</Badge>}
                        {updateAvailable && <Badge tone="ok">{t("업데이트 가능")}</Badge>}
                    </>
                ) : undefined}
            />

            {settings === null ? (
                <Card className="flex min-h-48 flex-col items-center justify-center gap-3 text-center">
                    {loadError ? <AlertCircle className="size-6 text-danger" /> : <Loader2 className="size-6 animate-spin text-[var(--primary)]" />}
                    <div>
                        <p className="text-sm font-medium text-ink">{loadError ? t("설정을 불러오지 못했습니다") : t("설정을 불러오는 중")}</p>
                        <p className="mt-1 text-xs text-ink-faint">{loadError ? t("서버 연결을 확인한 뒤 다시 시도해 주세요.") : t("잠시만 기다려 주세요.")}</p>
                    </div>
                    {loadError && <Button icon={RefreshCw} onClick={() => void loadSettings()} variant="primary">다시 시도</Button>}
                </Card>
            ) : <div className="space-y-4">
            <nav className="settings-tabs flex min-w-0 items-center gap-1 overflow-x-auto rounded-[var(--radius-card)] border border-line bg-surface-2 p-1.5" aria-label={t("설정 탭")}>
                {TABS.map((tab) => {
                    const Icon = tab.icon;
                    return (
                        <button
                            key={tab.id}
                            type="button"
                            onClick={() => handleTabChange(tab.id)}
                            aria-current={activeTab === tab.id ? "page" : undefined}
                            className={`relative flex min-h-10 shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-[var(--radius-control)] px-3 text-[12px] font-medium transition-all sm:px-3.5 sm:text-[13px] ${activeTab === tab.id ? "text-ink" : "text-ink-faint hover:bg-surface-3 hover:text-ink-muted"}`}
                        >
                            <Icon className="w-4 h-4" />
                            {t(tab.label)}
                            {dirtyTabs[tab.id] && <span className="w-2 h-2 rounded-full bg-warn absolute top-2 right-2 animate-pulse" />}
                            {tab.id === "system" && updateAvailable && <span className="w-2 h-2 rounded-full bg-ok absolute top-2 right-2 animate-pulse" />}
                        </button>
                    );
                })}
            </nav>

            {activeTab === "general" && <GeneralTab settings={settings} onSaved={loadSettings} onDirtyChange={(dirty) => setTabDirty("general", dirty)} />}
            {activeTab === "download" && <DownloadTab settings={settings} onSaved={loadSettings} onDirtyChange={(dirty) => setTabDirty("download", dirty)} />}
            {activeTab === "auth" && <AuthTab settings={settings} onSaved={loadSettings} onDirtyChange={(dirty) => setTabDirty("auth", dirty)} />}
            {activeTab === "notifications" && <NotificationsTab settings={settings} onSaved={loadSettings} onDirtyChange={(dirty) => setTabDirty("notifications", dirty)} />}
            {activeTab === "appearance" && <AppearanceTab settings={settings} onSaved={loadSettings} onDirtyChange={(dirty) => setTabDirty("appearance", dirty)} />}
            {activeTab === "system" && <SystemTab settings={settings} onSaved={loadSettings} onDirtyChange={(dirty) => setTabDirty("system", dirty)} onUpdateAvailabilityChange={setUpdateAvailable} />}
            {activeTab === "info" && <InfoTab settings={settings} onSaved={loadSettings} onDirtyChange={(dirty) => setTabDirty("info", dirty)} />}
            </div>}
        </div>
    );
}
