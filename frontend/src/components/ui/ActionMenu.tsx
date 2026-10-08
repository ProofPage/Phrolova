import { useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { MoreHorizontal, X } from "lucide-react";
import { useDialogKeyboard } from "../../hooks/useDialogKeyboard";
import { useLanguage } from "../../contexts/LanguageContext";

export function ActionMenu({ label, children, className, onKeyDown }: {
    label: string;
    children: (close: () => void) => ReactNode;
    className?: string;
    onKeyDown?: React.KeyboardEventHandler<HTMLButtonElement>;
}) {
    const { t } = useLanguage();
    const [open, setOpen] = useState(false);
    const dialog = useRef<HTMLDivElement>(null);
    const id = useId();
    const close = () => setOpen(false);
    useDialogKeyboard(dialog, close, open);
    return <>
        <button type="button" className={`icon-button ${className || ""}`} aria-label={label} title={label} aria-haspopup="dialog" aria-expanded={open} aria-keyshortcuts={onKeyDown ? "ArrowUp ArrowDown ArrowLeft ArrowRight" : undefined} onKeyDown={onKeyDown} onClick={() => setOpen(true)}><MoreHorizontal className="size-4" /></button>
        {open && createPortal(<div className="ui-overlay fixed inset-0 z-[100] flex items-center justify-center bg-surface-0/75" onClick={event => { if (event.target === event.currentTarget) close(); }}>
            <div ref={dialog} role="dialog" aria-modal="true" aria-labelledby={id} className="ui-dialog ui-popover action-menu" tabIndex={-1}>
                <div className="flex min-w-0 items-center gap-2 border-b border-line p-3">
                    <h3 id={id} className="min-w-0 flex-1 line-clamp-2 text-sm font-semibold [overflow-wrap:anywhere]" title={label}>{label}</h3>
                    <button type="button" className="icon-button shrink-0" aria-label={t("닫기")} onClick={close}><X className="size-4" /></button>
                </div>
                <div className="action-menu-items p-2">{children(close)}</div>
            </div>
        </div>, document.body)}
    </>;
}
