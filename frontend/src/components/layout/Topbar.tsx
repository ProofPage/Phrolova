import { useEffect, useState } from "react";
import { Gift, Search } from "lucide-react";
import { NavLink } from "react-router-dom";
import { api, type UpdateInfo } from "../../api/client";
import { useLanguage } from "../../contexts/LanguageContext";

export function Topbar() {
    const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
    const { t } = useLanguage();

    useEffect(() => { api.getUpdateStatus().then(setUpdateInfo).catch(() => {}); }, []);

    const openSearch = (event: React.MouseEvent<HTMLButtonElement>) => {
        event.currentTarget.focus({ preventScroll: true });
        document.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true }));
    };

    return (
        <header className="app-topbar relative z-30 shrink-0">
            <a href="#main-content" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-2 focus:z-50 focus:rounded-lg focus:bg-surface-3 focus:px-3 focus:py-2">{t("common.skipToContent")}</a>
            <div className="app-topbar-inner flex h-[54px] sm:h-11 items-center justify-end gap-2 px-3 sm:px-5 lg:px-6">
                <button type="button" onClick={openSearch} className="top-search hidden items-center gap-2 rounded-[10px] px-3 py-2 text-[12px] text-ink-faint hover:text-ink sm:flex" aria-label={t("common.quickNavigation")}>
                    <Search className="size-4" /><span>{t("common.quickNavigation")}</span><kbd className="top-search-key ml-2 rounded px-1.5 py-0.5 text-[10px]">Ctrl K</kbd>
                </button>
                <button type="button" onClick={openSearch} className="icon-button grid sm:hidden" aria-label={t("common.quickNavigation")}><Search className="size-[18px]" /></button>
                {updateInfo?.has_update && <NavLink to="/settings" className="icon-button grid text-[var(--primary)]" title={t("common.update")} aria-label={t("common.update")}><Gift className="size-[18px]" /></NavLink>}
            </div>
        </header>
    );
}
