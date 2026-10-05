import { useEffect, useRef, useState } from "react";
import { NavLink } from "react-router-dom";
import {
    AlertCircle,
    AlertTriangle,
    Bell,
    CheckCircle2,
    Gift,
    Menu,
    Search,
    Trash2,
    Tv,
    X,
} from "lucide-react";
import { clsx } from "clsx";
import { api, type UpdateInfo } from "../../api/client";
import { NAV_GROUPS } from "../../config/navigation";
import { useTheme } from "../../contexts/ThemeContext";
import { useLanguage } from "../../contexts/LanguageContext";
import { useVod } from "../../contexts/VodContext";
import { useToastHistory } from "../ui/Toast";

export function Sidebar() {
    const [mobileOpen, setMobileOpen] = useState(false);
    const [showNotifications, setShowNotifications] = useState(false);
    const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
    const notificationRef = useRef<HTMLDivElement>(null);
    const { pageTitle, iconUrl } = useTheme();
    const { t } = useLanguage();
    const { activeCount, tasks } = useVod();
    const { history, markAllRead, clearHistory } = useToastHistory();
    const unreadCount = history.filter((item) => !item.read).length;
    const primaryTask = tasks.find((task) => task.state === "downloading");

    useEffect(() => {
        api.getUpdateStatus().then(setUpdateInfo).catch((error) => console.error("업데이트 정보 로드 실패:", error));
    }, []);

    useEffect(() => {
        const closeOutside = (event: MouseEvent) => {
            if (notificationRef.current && !notificationRef.current.contains(event.target as Node)) setShowNotifications(false);
        };
        document.addEventListener("mousedown", closeOutside);
        return () => document.removeEventListener("mousedown", closeOutside);
    }, []);

    const navigation = (
        <>
            <header className="px-4 py-4 border-b border-line relative z-50">
                <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-3 min-w-0">
                        <div className="brand-mark w-10 h-10 rounded-[var(--radius-card)] grid place-items-center shrink-0 overflow-hidden">
                            {iconUrl ? <img src={iconUrl} alt="" className="w-full h-full object-cover" /> : <Tv className="w-5 h-5" />}
                        </div>
                        <div className="min-w-0">
                            <p className="text-[10px] uppercase tracking-[0.18em] text-ink-faint font-bold">Recorder</p>
                            <h1 className="text-[15px] font-bold text-ink truncate leading-tight" title={pageTitle}>{pageTitle}</h1>
                        </div>
                    </div>

                    <div className="flex items-center gap-1">
                        <div className="relative" ref={notificationRef}>
                            <button
                                onClick={() => {
                                    setShowNotifications((open) => !open);
                                    if (!showNotifications && unreadCount > 0) markAllRead();
                                }}
                                className="icon-button inline-grid relative"
                                aria-label={t("알림 센터")}
                            >
                                <Bell className="w-[18px] h-[18px]" />
                                {unreadCount > 0 && <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-live rounded-full ring-2 ring-surface-1" />}
                            </button>

                            {showNotifications && (
                                <div className="absolute top-full -left-24 sm:left-0 mt-2 w-80 bg-surface-2/95 backdrop-blur-xl border border-line-strong rounded-[var(--radius-card)] shadow-[var(--shadow-pop)] overflow-hidden animate-slide-in-top">
                                    <div className="px-4 py-3 border-b border-line flex items-center justify-between">
                                        <div><p className="text-sm font-semibold text-ink">{t("알림 센터")}</p><p className="text-[10px] text-ink-faint mt-0.5">{t("최근 앱 이벤트")}</p></div>
                                        <div className="flex items-center gap-2">
                                            <span className="text-[10px] text-ink-faint font-mono" aria-label={`알림 ${history.length}개`}>{history.length}</span>
                                            <button type="button" onClick={clearHistory} disabled={history.length === 0}
                                                aria-label={t("모두 지우기")} title={t("모두 지우기")}
                                                className="inline-flex items-center gap-1.5 rounded-md border border-line px-2 py-1.5 text-[11px] text-ink-muted hover:bg-surface-3 hover:text-danger transition-colors disabled:opacity-40 disabled:cursor-not-allowed">
                                                <Trash2 className="w-3 h-3" />{t("모두 지우기")}
                                            </button>
                                        </div>
                                    </div>
                                    <div className="max-h-80 overflow-y-auto">
                                        {history.length === 0 ? (
                                            <div className="p-8 text-center text-xs text-ink-faint">{t("아직 알림 내역이 없습니다.")}</div>
                                        ) : history.map((item) => {
                                            const Icon = item.type === "success" ? CheckCircle2 : item.type === "error" ? AlertCircle : AlertTriangle;
                                            return (
                                                <div key={item.id} className="px-4 py-3 border-b border-line last:border-0 hover:bg-surface-3 transition-colors">
                                                    <div className="flex gap-2.5">
                                                        <Icon className={clsx("w-4 h-4 mt-0.5 shrink-0", item.type === "success" ? "text-ok" : item.type === "error" ? "text-danger" : "text-warn")} />
                                                        <div className="min-w-0"><p className="text-xs text-ink-muted leading-relaxed wrap-break-word">{item.message}</p><p className="text-[10px] text-ink-faint mt-1 font-mono">{item.timestamp.toLocaleTimeString()}</p></div>
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                </div>
                            )}
                        </div>
                        <button onClick={() => setMobileOpen(false)} className="icon-button inline-grid lg:hidden" aria-label={t("메뉴 닫기")}><X className="w-[18px] h-[18px]" /></button>
                    </div>
                </div>

                <div className="mt-4 flex items-center gap-2 px-3 py-2 bg-surface-2 border border-line rounded-[var(--radius-control)] text-ink-faint">
                    <Search className="w-3.5 h-3.5" />
                    <span className="text-[11px] flex-1">{t("빠른 이동")}</span>
                    <kbd className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-surface-3 border border-line-strong text-ink-muted">Ctrl K</kbd>
                </div>
            </header>

            <nav className="flex-1 px-3 py-4 space-y-5 overflow-y-auto">
                {NAV_GROUPS.map((group) => (
                    <div key={group.title}>
                        <p className="px-3 mb-1.5 text-[9px] font-bold text-ink-faint uppercase tracking-[0.18em]">{t(group.title)}</p>
                        <div className="space-y-1">
                            {group.items.map((item) => (
                                <NavLink
                                    key={item.to}
                                    to={item.to}
                                    end={item.to === "/"}
                                    onClick={() => setMobileOpen(false)}
                                    className={({ isActive }) => clsx("nav-item group", isActive ? "nav-active" : "text-ink-faint hover:text-ink hover:bg-surface-3")}
                                >
                                    {({ isActive }) => <><span className={clsx("nav-icon", isActive && "nav-icon-active")}><item.icon className="w-[17px] h-[17px]" /></span><span className="truncate">{t(item.name)}</span></>}
                                </NavLink>
                            ))}
                        </div>
                    </div>
                ))}
            </nav>

            {activeCount > 0 && primaryTask && (
                <div className="px-3 pb-3">
                    <NavLink to="/vod" onClick={() => setMobileOpen(false)} className="block p-3 bg-surface-2 border border-line rounded-[var(--radius-card)] hover:bg-surface-3 transition-colors surface-raise">
                        <div className="flex items-center justify-between gap-2"><span className="text-[11px] font-semibold text-ink">{t("다운로드")} {activeCount}</span><span className="text-[10px] text-ok font-mono">{primaryTask.download_speed.toFixed(1)} MB/s</span></div>
                        <p className="text-[10px] text-ink-faint truncate mt-1.5" title={primaryTask.title}>{primaryTask.title}</p>
                        <div className="mt-2 h-1 bg-surface-4 rounded-full overflow-hidden"><div className="h-full rounded-full bg-[var(--primary)] transition-all" style={{ width: `${primaryTask.progress}%` }} /></div>
                    </NavLink>
                </div>
            )}

            <footer className="px-4 py-3 border-t border-line flex items-center justify-between">
                <div><p className="text-[10px] text-ink-faint">Phrolova</p><p className="text-[10px] font-mono text-ink-muted mt-0.5">v{updateInfo?.current_version || "..."}</p></div>
                {updateInfo?.has_update && <NavLink to="/settings" className="inline-flex items-center gap-1.5 px-2 py-1 btn-ghost-primary rounded-full text-[10px] font-bold"><Gift className="w-3 h-3" /> 업데이트</NavLink>}
            </footer>
        </>
    );

    return (
        <>
            <button onClick={() => setMobileOpen(true)} className="fixed top-4 left-4 z-100 grid lg:hidden icon-button bg-surface-1 border border-line shadow-[var(--shadow-raise)]" aria-label={t("메뉴 열기")}><Menu className="w-5 h-5" /></button>
            <aside className="hidden lg:flex relative z-30 w-[248px] bg-surface-1/95 backdrop-blur-xl border-r border-line flex-col h-screen shrink-0">{navigation}</aside>
            {mobileOpen && (
                <div className="fixed inset-0 z-99 lg:hidden">
                    <button className="absolute inset-0 bg-surface-0/80 backdrop-blur-sm animate-backdrop w-full" onClick={() => setMobileOpen(false)} aria-label={t("메뉴 닫기")} />
                    <aside className="relative w-[280px] bg-surface-1 border-r border-line flex flex-col h-screen animate-slide-in-sidebar">{navigation}</aside>
                </div>
            )}
        </>
    );
}
