import { createElement, useEffect, useState } from "react";
import { Command } from "cmdk";
import { useNavigate } from "react-router-dom";
import { NAV_ITEMS } from "../../config/navigation";
import { useLanguage } from "../../contexts/LanguageContext";

export function CommandPalette() {
    const { t } = useLanguage();
    const [open, setOpen] = useState(false);
    const navigate = useNavigate();

    // 토글 단축키: Ctrl+K 또는 Cmd+K
    useEffect(() => {
        const down = (e: KeyboardEvent) => {
            if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                setOpen((open) => !open);
            }
        };

        document.addEventListener("keydown", down);
        return () => document.removeEventListener("keydown", down);
    }, []);

    const runCommand = (command: () => void) => {
        setOpen(false);
        command();
    };

    if (!open) return null;

    return (
        <Command.Dialog
            open={open}
            onOpenChange={setOpen}
            className="command-palette fixed inset-0 z-[100] flex items-start justify-center pt-[18vh] bg-surface-0/75 "
            label={t("빠른 이동")}
        >
            <div className="ui-popover w-[calc(100vw_-_2rem)] max-w-lg shadow-[var(--shadow-pop)] rounded-[var(--radius-card)] overflow-hidden pointer-events-auto">
                <Command.Input
                    placeholder={t("페이지 검색...")}
                    className="w-full px-5 py-4 bg-transparent text-ink placeholder:text-ink-faint border-b border-line focus:outline-none focus:ring-0"
                />
                
                <Command.List className="max-h-[320px] overflow-y-auto p-2">
                    <Command.Empty className="py-6 text-center text-sm text-ink-faint">
                        {t("검색 결과가 없습니다.")}
                    </Command.Empty>
                    
                    <Command.Group heading={t("페이지 이동")} className="px-2 py-1.5 text-xs font-semibold text-ink-faint">
                        {NAV_ITEMS.map((item) => (
                            <Command.Item
                                key={item.to}
                                value={t(item.name)}
                                onSelect={() => runCommand(() => navigate(item.to))}
                                className="flex items-center gap-2 px-3 py-2.5 mt-1 text-sm text-ink-muted rounded-[var(--radius-control)] cursor-pointer hover:bg-surface-3 aria-selected:bg-surface-3 aria-selected:text-ink transition-colors"
                            >
                                {createElement(item.icon, { className: "w-4 h-4" })} {t(item.name)}
                            </Command.Item>
                        ))}
                    </Command.Group>
                </Command.List>
            </div>
        </Command.Dialog>
    );
}
