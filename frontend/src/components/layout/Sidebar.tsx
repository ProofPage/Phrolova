import { useDialogKeyboard } from "../../hooks/useDialogKeyboard";
import { useEffect, useRef, useState } from "react";
import { Link, NavLink } from "react-router-dom";
import { Menu, Tv, X } from "lucide-react";
import { clsx } from "clsx";
import { NAV_GROUPS } from "../../config/navigation";
import { useTheme } from "../../contexts/ThemeContext";
import { useLanguage } from "../../contexts/LanguageContext";

export function Sidebar() {
    const [mobileOpen, setMobileOpen] = useState(false);
    const drawerRef = useRef<HTMLElement>(null);
    useDialogKeyboard(drawerRef, () => setMobileOpen(false), mobileOpen);
    const { pageTitle, iconUrl } = useTheme();
    const { t } = useLanguage();

    useEffect(() => {
        if (!mobileOpen) return;
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === "Escape") setMobileOpen(false);
        };
        document.addEventListener("keydown", onKeyDown);
        return () => document.removeEventListener("keydown", onKeyDown);
    }, [mobileOpen]);

    const navigation = (
        <>
            <Link to="/" onClick={() => setMobileOpen(false)} className="sidebar-brand" aria-label={pageTitle}>
                <span className="brand-mark grid size-9 shrink-0 place-items-center overflow-hidden rounded-xl">
                    {iconUrl ? <img src={iconUrl} alt="" className="size-full object-cover" /> : <Tv className="size-[18px]" />}
                </span>
                <span className="min-w-0">
                    <span className="block truncate text-[15px] font-bold tracking-[-0.03em] text-ink">{pageTitle}</span>
                </span>
            </Link>

            <nav className="sidebar-navigation" aria-label={t("주 메뉴")}>
                {NAV_GROUPS.map((group) => (
                    <section key={group.title} className="sidebar-nav-group">
                        <h2 className="sidebar-nav-heading">{t(group.title)}</h2>
                        <div className="space-y-1">
                            {group.items.map((item) => (
                                <NavLink
                                    key={item.to}
                                    to={item.to}
                                    end={item.to === "/"}
                                    onClick={() => setMobileOpen(false)}
                                    className={({ isActive }) => clsx("sidebar-nav-link", isActive && "sidebar-nav-link-active")}
                                >
                                    <item.icon className="size-[17px] shrink-0" aria-hidden="true" />
                                    <span className="truncate">{t(item.name)}</span>
                                </NavLink>
                            ))}
                        </div>
                    </section>
                ))}
            </nav>

        </>
    );

    return (
        <>
            <aside className="app-sidebar hidden lg:flex" aria-label={t("주 메뉴")}>{navigation}</aside>
            <button
                type="button"
                onClick={() => setMobileOpen(true)}
                className="sidebar-mobile-trigger icon-button lg:hidden"
                aria-label={t("메뉴 열기")}
                aria-expanded={mobileOpen}
                aria-controls="mobile-sidebar"
            >
                <Menu className="size-[18px]" />
            </button>
            {mobileOpen && (
                <div className="sidebar-mobile-overlay lg:hidden">
                    <button className="sidebar-backdrop" onClick={() => setMobileOpen(false)} aria-label={t("메뉴 닫기")} />
                    <aside ref={drawerRef} role="dialog" aria-modal="true" tabIndex={-1} aria-label={t("주 메뉴")} id="mobile-sidebar" className="app-sidebar app-sidebar-mobile">
                        <button type="button" onClick={() => setMobileOpen(false)} className="sidebar-mobile-close icon-button" aria-label={t("메뉴 닫기")}>
                            <X className="size-[18px]" />
                        </button>
                        {navigation}
                    </aside>
                </div>
            )}
        </>
    );
}
