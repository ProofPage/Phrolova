import { useEffect, useRef, useState } from "react";
import { NavLink } from "react-router-dom";
import { AlertCircle, AlertTriangle, Bell, CheckCircle2, Gift, Menu, Search, Trash2, Tv, X } from "lucide-react";
import { clsx } from "clsx";
import { api, type UpdateInfo } from "../../api/client";
import { NAV_GROUPS } from "../../config/navigation";
import { useTheme } from "../../contexts/ThemeContext";
import { useLanguage } from "../../contexts/LanguageContext";
import { useVod } from "../../contexts/VodContext";
import { useToastHistory } from "../ui/Toast";

export function Topbar() {
    const [menuOpen, setMenuOpen] = useState(false);
    const [notificationsOpen, setNotificationsOpen] = useState(false);
    const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
    const menuRef = useRef<HTMLDivElement>(null);
    const notificationRef = useRef<HTMLDivElement>(null);
    const { pageTitle, iconUrl } = useTheme();
    const { t } = useLanguage();
    const { activeCount, tasks } = useVod();
    const { history, markAllRead, clearHistory } = useToastHistory();
    const unreadCount = history.filter((item) => !item.read).length;
    const primaryTask = tasks.find((task) => task.state === "downloading");

    useEffect(() => { api.getUpdateStatus().then(setUpdateInfo).catch(() => {}); }, []);

    useEffect(() => {
        const onMouseDown = (event: MouseEvent) => {
            if (menuRef.current && !menuRef.current.contains(event.target as Node)) setMenuOpen(false);
            if (notificationRef.current && !notificationRef.current.contains(event.target as Node)) setNotificationsOpen(false);
        };
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === "Escape") { setMenuOpen(false); setNotificationsOpen(false); }
        };
        document.addEventListener("mousedown", onMouseDown);
        document.addEventListener("keydown", onKeyDown);
        return () => { document.removeEventListener("mousedown", onMouseDown); document.removeEventListener("keydown", onKeyDown); };
    }, []);

    const openSearch = () => document.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true }));

    return <header className="app-topbar relative z-30 shrink-0">
        <a href="#main-content" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-2 focus:z-50 focus:rounded-lg focus:bg-surface-3 focus:px-3 focus:py-2">{t("본문으로 이동")}</a>
        <div className="mx-auto flex h-[62px] max-w-[1760px] items-center gap-3 px-3 sm:px-5 lg:px-7">
            <NavLink to="/" className="flex min-w-0 shrink-0 items-center gap-2.5 pr-2" aria-label={pageTitle}>
                <span className="brand-mark grid size-8 shrink-0 place-items-center overflow-hidden rounded-[10px]">{iconUrl ? <img src={iconUrl} alt="" className="size-full object-cover" /> : <Tv className="size-[17px]" />}</span>
                <span className="hidden truncate text-[14px] font-bold tracking-[-0.025em] text-ink sm:block">{pageTitle}</span>
            </NavLink>

            <nav className="hidden min-w-0 flex-1 items-center gap-0.5 overflow-x-auto lg:flex" aria-label={t("주 메뉴")}>
                {NAV_GROUPS.flatMap((group) => group.items).map((item) => <NavLink key={item.to} to={item.to} end={item.to === "/"} className={({ isActive }) => clsx("top-nav-link", isActive && "top-nav-link-active")}>
                    <item.icon className="size-[15px] shrink-0" /><span>{t(item.name)}</span>
                </NavLink>)}
            </nav>

            <div className="ml-auto flex shrink-0 items-center gap-1.5">
                {activeCount > 0 && primaryTask && <NavLink to="/vod" className="download-pill hidden max-w-52 items-center gap-2 rounded-full px-3 py-1.5 text-[11px] font-semibold text-ink-muted hover:text-ink md:flex" title={primaryTask.title}>
                    <span className="size-1.5 shrink-0 rounded-full bg-ok" /><span className="truncate">{t("다운로드")} {activeCount}</span><span className="font-mono text-ok">{Math.round(primaryTask.progress)}%</span>
                </NavLink>}
                <button type="button" onClick={openSearch} className="top-search hidden items-center gap-2 rounded-[10px] px-3 py-2 text-[12px] text-ink-faint hover:text-ink sm:flex" aria-label={t("빠른 이동")}>
                    <Search className="size-4" /><span>{t("빠른 이동")}</span><kbd className="ml-3 rounded px-1.5 py-0.5 text-[10px]">Ctrl K</kbd>
                </button>
                <button type="button" onClick={openSearch} className="icon-button grid sm:hidden" aria-label={t("빠른 이동")}><Search className="size-[18px]" /></button>
                <div className="relative" ref={notificationRef}>
                    <button type="button" onClick={() => { setNotificationsOpen((open) => !open); if (!notificationsOpen && unreadCount > 0) markAllRead(); }} className="icon-button relative grid" aria-label={t("알림 센터")} aria-expanded={notificationsOpen}>
                        <Bell className="size-[18px]" />{unreadCount > 0 && <span className="absolute right-1.5 top-1.5 size-2 rounded-full bg-live ring-2 ring-surface-1" />}
                    </button>
                    {notificationsOpen && <div className="glass-popover absolute right-0 top-full z-50 mt-3 w-[min(22rem,calc(100vw-1.5rem))] overflow-hidden rounded-[16px] shadow-[var(--shadow-pop)] animate-slide-in-top">
                        <div className="flex items-center justify-between border-b border-line px-4 py-3"><div><p className="text-sm font-semibold text-ink">{t("알림 센터")}</p><p className="mt-0.5 text-[11px] text-ink-faint">{t("최근 앱 이벤트")}</p></div><button type="button" onClick={clearHistory} disabled={history.length === 0} aria-label={t("모두 지우기")} className="icon-button grid disabled:opacity-40"><Trash2 className="size-4" /></button></div>
                        <div className="max-h-80 overflow-y-auto">{history.length === 0 ? <p className="p-8 text-center text-xs text-ink-faint">{t("아직 알림 내역이 없습니다.")}</p> : history.map((item) => { const Icon = item.type === "success" ? CheckCircle2 : item.type === "error" ? AlertCircle : AlertTriangle; return <div key={item.id} className="flex gap-2.5 border-b border-line px-4 py-3 last:border-0 hover:bg-white/[0.04]"><Icon className={clsx("mt-0.5 size-4 shrink-0", item.type === "success" ? "text-ok" : item.type === "error" ? "text-danger" : "text-warn")} /><div className="min-w-0"><p className="break-words text-xs leading-relaxed text-ink-muted">{item.message}</p><p className="mt-1 font-mono text-[10px] text-ink-faint">{item.timestamp.toLocaleTimeString()}</p></div></div>; })}</div>
                    </div>}
                </div>
                {updateInfo?.has_update && <NavLink to="/settings" className="icon-button hidden place-items-center text-[var(--primary)] sm:grid" title={t("업데이트")} aria-label={t("업데이트")}><Gift className="size-[18px]" /></NavLink>}
                <div className="relative lg:hidden" ref={menuRef}>
                    <button type="button" onClick={() => setMenuOpen((open) => !open)} className="icon-button grid" aria-label={t("메뉴 열기")} aria-expanded={menuOpen}>{menuOpen ? <X className="size-[18px]" /> : <Menu className="size-[18px]" />}</button>
                    {menuOpen && <nav className="glass-popover absolute right-0 top-full z-50 mt-3 w-64 rounded-[16px] p-2 shadow-[var(--shadow-pop)]" aria-label={t("주 메뉴")}>
                        {NAV_GROUPS.map((group) => <div key={group.title} className="py-1"><p className="px-3 py-1 text-[10px] font-semibold tracking-wide text-ink-faint">{t(group.title)}</p>{group.items.map((item) => <NavLink key={item.to} to={item.to} end={item.to === "/"} onClick={() => setMenuOpen(false)} className={({ isActive }) => clsx("mobile-nav-link", isActive && "mobile-nav-link-active")}><item.icon className="size-4" />{t(item.name)}</NavLink>)}</div>)}
                    </nav>}
                </div>
            </div>
        </div>
    </header>;
}
