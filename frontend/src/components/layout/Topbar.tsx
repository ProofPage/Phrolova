import { useEffect, useId, useRef, useState } from "react";
import { AlertCircle, AlertTriangle, Bell, CheckCircle2, Gift, Search, Trash2 } from "lucide-react";
import { Link, NavLink } from "react-router-dom";
import { clsx } from "clsx";
import { api, type UpdateInfo } from "../../api/client";
import { useLanguage } from "../../contexts/LanguageContext";
import { useVod } from "../../contexts/VodContext";
import { useToastHistory } from "../ui/Toast";

export function Topbar() {
    const [notificationsOpen, setNotificationsOpen] = useState(false);
    const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
    const notificationRef = useRef<HTMLDivElement>(null);
    const notificationTriggerRef = useRef<HTMLButtonElement>(null);
    const notificationId = useId();
    const { t } = useLanguage();
    const { activeCount, tasks } = useVod();
    const { history, markAllRead, clearHistory } = useToastHistory();
    const unreadCount = history.filter((item) => !item.read).length;
    const primaryTask = tasks.find((task) => task.state === "downloading");

    useEffect(() => { api.getUpdateStatus().then(setUpdateInfo).catch(() => {}); }, []);

    useEffect(() => {
        const onMouseDown = (event: MouseEvent) => {
            if (notificationRef.current && !notificationRef.current.contains(event.target as Node)) setNotificationsOpen(false);
        };
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === "Escape" && notificationsOpen && !document.querySelector('[aria-modal="true"]')) { setNotificationsOpen(false); notificationTriggerRef.current?.focus({ preventScroll: true }); }
        };
        document.addEventListener("mousedown", onMouseDown);
        document.addEventListener("keydown", onKeyDown);
        return () => { document.removeEventListener("mousedown", onMouseDown); document.removeEventListener("keydown", onKeyDown); };
    }, [notificationsOpen]);

    const openSearch = (event: React.MouseEvent<HTMLButtonElement>) => {
        event.currentTarget.focus({ preventScroll: true });
        document.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true }));
    };

    return (
        <header className="app-topbar relative z-30 shrink-0">
            <a href="#main-content" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-2 focus:z-50 focus:rounded-lg focus:bg-surface-3 focus:px-3 focus:py-2">{t("본문으로 이동")}</a>
            <div className="app-topbar-inner flex h-[54px] sm:h-11 items-center justify-end gap-2 px-3 sm:px-5 lg:px-6">
                {activeCount > 0 && primaryTask && <Link to="/vod" className="download-pill flex min-w-0 max-w-52 items-center gap-2 rounded-full px-3 py-2 text-[11px] font-semibold text-ink-muted hover:text-ink" aria-label={`${t("다운로드")} ${activeCount}, ${Math.round(primaryTask.progress)}%`} title={primaryTask.title}>
                    <span className="size-1.5 shrink-0 rounded-full bg-ok" /><span className="truncate"><span className="download-pill-label">{t("다운로드")} </span>{activeCount}</span><span className="download-pill-progress shrink-0 font-mono text-ok">{Math.round(primaryTask.progress)}%</span>
                </Link>}
                <button type="button" onClick={openSearch} className="top-search hidden items-center gap-2 rounded-[10px] px-3 py-2 text-[12px] text-ink-faint hover:text-ink sm:flex" aria-label={t("빠른 이동")}>
                    <Search className="size-4" /><span>{t("빠른 이동")}</span><kbd className="top-search-key ml-2 rounded px-1.5 py-0.5 text-[10px]">Ctrl K</kbd>
                </button>
                <button type="button" onClick={openSearch} className="icon-button grid sm:hidden" aria-label={t("빠른 이동")}><Search className="size-[18px]" /></button>
                <div className="relative" ref={notificationRef}>
                    <button ref={notificationTriggerRef} type="button" aria-controls={notificationId} onClick={() => { setNotificationsOpen((open) => !open); if (!notificationsOpen && unreadCount > 0) markAllRead(); }} className="icon-button relative grid" aria-label={t("알림 센터")} aria-expanded={notificationsOpen}>
                        <Bell className="size-[18px]" />{unreadCount > 0 && <span className="absolute right-1.5 top-1.5 size-2 rounded-full bg-live ring-2 ring-surface-1" />}
                    </button>
                    {notificationsOpen && <div id={notificationId} role="region" aria-label={t("알림 센터")} className="notification-popover ui-popover absolute right-0 top-full z-50 mt-2 w-[min(22rem,calc(100vw-1.5rem))] overflow-hidden rounded-[var(--radius-card)] shadow-[var(--shadow-pop)] animate-slide-in-top">
                        <div className="flex items-center justify-between border-b border-line px-4 py-3"><div><p className="text-sm font-semibold text-ink">{t("알림 센터")}</p><p className="mt-0.5 text-[11px] text-ink-faint">{t("최근 앱 이벤트")}</p></div><button type="button" onClick={clearHistory} disabled={history.length === 0} aria-label={t("모두 지우기")} title={t("모두 지우기")} className="icon-button grid disabled:opacity-40"><Trash2 className="size-4" /></button></div>
                        <div className="max-h-[min(20rem,60dvh)] overflow-y-auto">{history.length === 0 ? <p className="p-8 text-center text-xs text-ink-faint">{t("아직 알림 내역이 없습니다.")}</p> : history.map((item) => { const Icon = item.type === "success" ? CheckCircle2 : item.type === "error" ? AlertCircle : AlertTriangle; return <div key={item.id} className="flex gap-2.5 border-b border-line px-4 py-3 last:border-0 hover:bg-white/[0.04]"><Icon className={clsx("mt-0.5 size-4 shrink-0", item.type === "success" ? "text-ok" : item.type === "error" ? "text-danger" : "text-warn")} /><div className="min-w-0"><p className="[overflow-wrap:anywhere] text-xs leading-relaxed text-ink-muted">{item.message}</p><p className="mt-1 font-mono text-[10px] text-ink-faint">{item.timestamp.toLocaleTimeString()}</p></div></div>; })}</div>
                    </div>}
                </div>
                {updateInfo?.has_update && <NavLink to="/settings" className="icon-button grid text-[var(--primary)]" title={t("업데이트")} aria-label={t("업데이트")}><Gift className="size-[18px]" /></NavLink>}
            </div>
        </header>
    );
}
