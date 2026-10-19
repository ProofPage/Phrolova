import { createContext, useContext, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ChevronDown, KeyRound } from "lucide-react";
import { Card } from "../ui/primitives";

const AuthSelection = createContext<{
    selected: string | null;
    select: (id: string | null) => void;
    panel: HTMLDivElement | null;
} | null>(null);

export function AuthPlatformLayout({ children }: { children: ReactNode }) {
    const [selected, select] = useState<string | null>(null);
    const [panel, setPanel] = useState<HTMLDivElement | null>(null);
    return <AuthSelection.Provider value={{ selected, select, panel }}>
        <div className="auth-platform-grid">{children}</div>
        <div ref={setPanel} className="auth-detail-panel" hidden={!selected} />
    </AuthSelection.Provider>;
}

export function AuthPlatformCard({ platform, title, description, action, onClose, children }: {
    platform: string;
    title: string;
    description: string;
    action: ReactNode;
    onClose: () => void;
    children: ReactNode;
}) {
    const selection = useContext(AuthSelection)!;
    const active = selection.selected === platform;
    const id = useId();
    const detail = useRef<HTMLElement>(null);
    const close = useRef(onClose);
    close.current = onClose;
    useEffect(() => {
        if (!active) close.current();
        else if (selection.panel) {
            detail.current?.focus({ preventScroll: true });
            detail.current?.scrollIntoView({ block: "nearest" });
        }
    }, [active, selection.panel]);
    return <>
        <Card className={`auth-selector ${active ? "auth-selector-active" : ""}`}>
            <button type="button" className="ui-disclosure auth-selector-button"
                aria-expanded={active} aria-controls={active ? id : undefined}
                onClick={() => selection.select(active ? null : platform)}>
                <KeyRound size={18} className="shrink-0" style={{ color: "var(--primary)" }} aria-hidden="true" />
                <span className="min-w-0">
                    <span className="auth-selector-title">{title}<ChevronDown size={16} className={active ? "rotate-180" : ""} aria-hidden="true" /></span>
                    <span className="auth-selector-description">{description}</span>
                </span>
                <span className="auth-selector-status">{action}</span>
            </button>
        </Card>
        {active && selection.panel && createPortal(
            <section ref={detail} id={id} tabIndex={-1} aria-labelledby={`${id}-title`}
                data-auth-detail={platform} className="ui-panel auth-detail">
                <h3 id={`${id}-title`} className="font-semibold text-ink mb-4">{title}</h3>
                {children}
            </section>, selection.panel)}
    </>;
}
