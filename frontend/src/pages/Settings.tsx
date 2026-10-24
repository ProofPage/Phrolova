import { translate } from "../i18n";
import { useCallback, useEffect, useRef, useState } from "react";
import { useBlocker } from "react-router-dom";
import {
    AlertCircle,
    Loader2,
    RefreshCw,
    Settings as SettingsIcon,
} from "lucide-react";
import { api, type Settings as SettingsType } from "../api/client";
import { AppearanceTab } from "../components/settings/AppearanceTab";
import { AuthTab } from "../components/settings/AuthTab";
import { DownloadTab } from "../components/settings/DownloadTab";
import { InfoTab } from "../components/settings/InfoTab";
import { NotificationsTab } from "../components/settings/NotificationsTab";
import { useConfirm } from "../components/ui/ConfirmModal";
import { Badge, Button, Card, PageHeader } from "../components/ui/primitives";
import { useLanguage } from "../contexts/LanguageContext";

type TabId = "download" | "auth" | "notifications" | "appearance" | "info";

const TABS: { id: TabId; label: string }[] = [
    { id: "download", label: "settings.downloads" },
    { id: "auth", label: "settings.authentication" },
    { id: "notifications", label: "settings.notifications" },
    { id: "appearance", label: "settings.appearanceInSettings" },
    { id: "info", label: "settings.aboutInSettings" },
];

const EMPTY_DIRTY: Record<TabId, boolean> = {
    download: false,
    auth: false,
    notifications: false,
    appearance: false,
    info: false,
};

export default function Settings() {
    const { t } = useLanguage();
    const [settings, setSettings] = useState<SettingsType | null>(null);
    const [loadError, setLoadError] = useState(false);
    const [activeTab, setActiveTab] = useState<TabId>("download");
    const [dirtyTabs, setDirtyTabs] = useState<Record<TabId, boolean>>(EMPTY_DIRTY);
    const [updateAvailable, setUpdateAvailable] = useState(false);
    const confirm = useConfirm();
    const tabsRef = useRef<HTMLElement>(null);
    useEffect(() => {
        const tabs = tabsRef.current;
        const active = tabs?.querySelector<HTMLElement>('[aria-current="page"]');
        if (!tabs || !active) return;
        const bounds = tabs.getBoundingClientRect();
        const selected = active.getBoundingClientRect();
        const left = selected.left < bounds.left ? selected.left - bounds.left : selected.right > bounds.right ? selected.right - bounds.right : 0;
        // 탭 표시 때문에 폼의 세로 스크롤까지 바뀌지 않게 한다.
        if (left) tabs.scrollBy({ left, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    }, [activeTab, settings]);

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
        // 정보 탭을 열기 전에도 새 버전 표시를 놓치지 않도록 상태를 미리 읽는다.
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
                title: "settings.unsavedChanges",
                message: "settings.thisTabHasUnsavedSettingsLeaveThisTabChangesWillBeDiscarded",
                confirmText: "settings.leave",
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
            title: "settings.unsavedChanges",
            message: "settings.youHaveUnsavedSettingsLeaveThisPageChangesWillBeDiscarded",
            confirmText: "settings.leave",
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
                title={t("settings.title")}
                description={t("workspace.settingsDescription")}
                meta={hasDirtyTab || updateAvailable ? (
                    <>
                        {hasDirtyTab && <Badge tone="warn">{t("settings.unsavedChangesInSettings")}</Badge>}
                        {updateAvailable && <Badge tone="ok">{t("settings.updateAvailable")}</Badge>}
                    </>
                ) : undefined}
            />

            {settings === null ? (
                <Card className="flex min-h-48 flex-col items-center justify-center gap-3 text-center">
                    {loadError ? <AlertCircle className="size-6 text-danger" /> : <Loader2 className="size-6 animate-spin text-[var(--primary)]" />}
                    <div>
                        <p className="text-sm font-medium text-ink">{loadError ? t("settings.couldNotLoadSettings") : t("settings.loadingSettings")}</p>
                        <p className="mt-1 text-xs text-ink-faint">{loadError ? t("settings.checkTheServerConnectionAndTryAgain") : t("settings.pleaseWaitAMoment")}</p>
                    </div>
                    {loadError && <Button icon={RefreshCw} onClick={() => void loadSettings()} variant="primary">{translate("live.tryAgain")}</Button>}
                </Card>
            ) : <div className="settings-workspace">
            <nav ref={tabsRef} className="settings-tabs flex min-w-0 items-center gap-1 overflow-x-auto rounded-[var(--radius-card)] border border-line bg-surface-2 p-1.5" aria-label={t("settings.settingsTabs")}>
                {TABS.map((tab) => {
                    return (
                        <button
                            key={tab.id}
                            type="button"
                            onClick={() => handleTabChange(tab.id)}
                            aria-current={activeTab === tab.id ? "page" : undefined}
                            className={`relative flex min-h-10 shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-[var(--radius-control)] px-3 text-[12px] font-medium transition-all sm:px-3.5 sm:text-[13px] ${activeTab === tab.id ? "text-ink" : "text-ink-faint hover:bg-surface-3 hover:text-ink-muted"}`}
                        >
                            {t(tab.label)}
                            {dirtyTabs[tab.id] && <span className="size-2 shrink-0 rounded-full bg-warn" />}
                            {tab.id === "info" && updateAvailable && <span className="size-2 shrink-0 rounded-full bg-ok" />}
                        </button>
                    );
                })}
            </nav>

            <div className="settings-tab-content">
            {activeTab === "download" && <DownloadTab settings={settings} onSaved={loadSettings} onDirtyChange={(dirty) => setTabDirty("download", dirty)} />}
            {activeTab === "auth" && <AuthTab settings={settings} onSaved={loadSettings} onDirtyChange={(dirty) => setTabDirty("auth", dirty)} />}
            {activeTab === "notifications" && <NotificationsTab settings={settings} onSaved={loadSettings} onDirtyChange={(dirty) => setTabDirty("notifications", dirty)} />}
            {activeTab === "appearance" && <AppearanceTab settings={settings} onSaved={loadSettings} onDirtyChange={(dirty) => setTabDirty("appearance", dirty)} />}
            {activeTab === "info" && <InfoTab settings={settings} onSaved={loadSettings} onDirtyChange={(dirty) => setTabDirty("info", dirty)} onUpdateAvailabilityChange={setUpdateAvailable} />}
            </div>
            </div>}
        </div>
    );
}
