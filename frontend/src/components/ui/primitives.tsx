/**
 * 공용 UI 프리미티브.
 *
 * 페이지마다 같은 카드/입력/토글 마크업을 복사해 쓰던 것을 한곳으로 모았다.
 * 색상은 index.css의 의미 토큰(surface/ink/line)과 --primary만 사용한다.
 */
import {
    createElement,
    createContext,
    useContext,
    forwardRef,
    useId,
    useState,
    type ButtonHTMLAttributes,
    type HTMLAttributes,
    type InputHTMLAttributes,
    type ReactNode,
    type SelectHTMLAttributes,
} from "react";
import { clsx } from "clsx";
import { ChevronDown, Loader2, type LucideIcon } from "lucide-react";
import { useLanguage } from "../../contexts/LanguageContext";

/* ── PageHeader ──────────────────────────────────────── */

/**
 * 페이지마다 제각각이던 제목 영역을 하나의 시각적 진입점으로 묶는다.
 * 핵심 상태와 주요 액션을 첫 화면에서 함께 읽을 수 있게 한다.
 */
export function PageHeader({ title, description, meta, actions, actionsPlacement = "inline" }: {
    icon: LucideIcon;
    eyebrow?: string;
    title: string;
    description: ReactNode;
    meta?: ReactNode;
    actions?: ReactNode;
    actionsPlacement?: "inline" | "inline-top" | "below";
    variant?: "default" | "plain";
}) {
    const { t } = useLanguage();
    return (
        <header className="page-header">
            <div className="page-heading">
                <div className="page-heading-copy">
                    <h1 className="page-title">{t(title)}</h1>
                    <p className="page-description">{typeof description === "string" ? t(description) : description}</p>
                </div>
                {meta && <div className="page-summary">{meta}</div>}
                {actions && actionsPlacement !== "below" && <div className="page-actions">{actions}</div>}
            </div>
            {actions && actionsPlacement === "below" && <div className="page-actions">{actions}</div>}
        </header>
    );
}

/* ── MetricCard ──────────────────────────────────────── */

export function MetricCard({ label, value, detail }: {
    icon: LucideIcon;
    label: string;
    value: ReactNode;
    detail?: ReactNode;
    tone?: "primary" | "live" | "ok" | "warn" | "info";
}) {
    const { t } = useLanguage();
    return <div className="ui-metric">
        <p className="ui-metric-label">{t(label)}</p>
        <p className="ui-metric-value">{value}</p>
        {detail && <p className="ui-metric-detail">{typeof detail === "string" ? t(detail) : detail}</p>}
    </div>;
}

/* ── Card ───────────────────────────────────────────── */

export function Card({
    children,
    className,
    padded = true,
    ...props
}: HTMLAttributes<HTMLElement> & {
    padded?: boolean;
}) {
    return (
        <section
            className={clsx(
                "ui-panel",
                padded && "p-4",
                className,
            )}
            {...props}
        >
            {children}
        </section>
    );
}

/**
 * 카드 상단 제목 줄. 아이콘은 강조색을 따르되,
 * tone을 주면 상태 색(위험/경고 등)으로 바꿀 수 있다.
 */
export function CardHeader({ title, description, action }: {
    icon?: LucideIcon;
    title: string;
    description?: ReactNode;
    action?: ReactNode;
    tone?: "primary" | "danger" | "warn" | "ok";
}) {
    const { t } = useLanguage();
    return <header className="ui-section-header">
        <div className="min-w-0"><h3>{t(title)}</h3>{description && <p>{typeof description === "string" ? t(description) : description}</p>}</div>
        {action && <div className="shrink-0">{action}</div>}
    </header>;
}

/* ── CollapsibleCard ────────────────────────────────── */

/**
 * 헤더를 눌러 본문을 여닫는 카드.
 *
 * 대부분의 사용자에게 필요 없지만 일부에게는 꼭 필요한 설정을 접어두어,
 * 기본 경로가 무엇인지 화면만 보고 알 수 있게 한다.
 * 접힌 상태에서도 action(상태 배지 등)은 계속 보인다.
 */
export function CollapsibleCard({
    icon,
    title,
    description,
    action,
    tone,
    defaultOpen = false,
    children,
}: {
    icon?: LucideIcon;
    title: string;
    description?: ReactNode;
    action?: ReactNode;
    tone?: "primary" | "danger" | "warn" | "ok";
    defaultOpen?: boolean;
    children: ReactNode;
}) {
    const [open, setOpen] = useState(defaultOpen);
    const bodyId = useId();

    const toneColor =
        tone === "danger" ? "var(--color-danger)"
        : tone === "warn" ? "var(--color-warn)"
        : tone === "ok" ? "var(--color-ok)"
        : "var(--primary)";

    return (
        <Card>
            <div className={clsx("flex items-center justify-between gap-4", open && "mb-5")}>
                {/* 헤더 전체가 토글이다. action은 버튼 밖에 둬야 중첩 클릭이 꼬이지 않는다. */}
                <button
                    type="button"
                    onClick={() => setOpen((v) => !v)}
                    aria-expanded={open}
                    aria-controls={bodyId}
                    className="flex items-center gap-3 min-w-0 flex-1 text-left group"
                >
                    {icon && (
                        <span
                            className="grid size-5 place-items-center shrink-0"
                            style={{
                                backgroundColor: "transparent",
                                color: toneColor,
                            }}
                        >
                            {createElement(icon, { className: "w-[18px] h-[18px]" })}
                        </span>
                    )}
                    <div className="min-w-0">
                        <h3 className="text-[15px] font-semibold text-ink leading-tight flex items-center gap-1.5">
                            {title}
                            <ChevronDown
                                className={clsx(
                                    "w-4 h-4 text-ink-faint transition-transform group-hover:text-ink-muted",
                                    open && "rotate-180",
                                )}
                            />
                        </h3>
                        {description && (
                            <p className="text-[13px] text-ink-faint mt-1 leading-relaxed">{description}</p>
                        )}
                    </div>
                </button>
                {action && <div className="shrink-0">{action}</div>}
            </div>

            {open && <div id={bodyId}>{children}</div>}
        </Card>
    );
}

const FieldContext = createContext<string | undefined>(undefined);

/* ── Field ──────────────────────────────────────────── */

/** 라벨 + 설명 + 컨트롤을 세로로 묶는 기본 폼 행. */
export function Field({
    label,
    hint,
    htmlFor,
    children,
    error,
}: {
    label: string;
    hint?: ReactNode;
    htmlFor?: string;
    children: ReactNode;
    error?: string;
}) {
    const { t } = useLanguage();
    const fieldId = useId();
    const inputId = htmlFor || fieldId;
    return <FieldContext.Provider value={inputId}><div className="ui-field">
        <div className="ui-field-copy">
            <label htmlFor={inputId} className="ui-field-label">{t(label)}</label>
            {hint && !error && <p className="ui-field-hint">{typeof hint === "string" ? t(hint) : hint}</p>}
        </div>
        <div className="ui-field-control">{children}{error && <p role="alert" className="mt-1 text-xs text-danger">{t(error)}</p>}</div>
    </div></FieldContext.Provider>;
}

/** 라벨과 컨트롤을 좌우로 배치하는 행 (토글용). */
export function SettingRow({
    label,
    hint,
    control,
    className,
}: {
    label: string;
    hint?: ReactNode;
    control: ReactNode;
    className?: string;
}) {
    const { t } = useLanguage();
    return (
        <div
            className={clsx(
                "flex items-center justify-between gap-4 py-3 border-b border-line last:border-0",
                className,
            )}
        >
            <div className="min-w-0">
                <p className="text-[13px] font-medium text-ink-muted">{t(label)}</p>
                {hint && <p className="text-xs text-ink-faint mt-0.5 leading-relaxed">{typeof hint === "string" ? t(hint) : hint}</p>}
            </div>
            <div className="shrink-0">{control}</div>
        </div>
    );
}

/* ── Input ──────────────────────────────────────────── */

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
    function Input({ className, placeholder, id, ...props }, ref) {
        const fieldId = useContext(FieldContext);
        const { t } = useLanguage();
        return (
            <input
                ref={ref}
                id={id || fieldId}
                className={clsx(
                    "ui-input input-focus w-full",
                    className,
                )}
                placeholder={placeholder ? t(placeholder) : placeholder}
                {...props}
            />
        );
    },
);

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement> & {
    options: { value: string; label: string }[];
}>(function Select({ className, options, id, ...props }, ref) {
    const fieldId = useContext(FieldContext);
    const { t } = useLanguage();
    return (
        <div className="relative">
            <select
                ref={ref}
                id={id || fieldId}
                className={clsx(
                    "ui-input ui-select input-focus w-full",
                    className,
                )}
                {...props}
            >
                {options.map((o) => (
                    <option key={o.value} value={o.value}>
                        {t(o.label)}
                    </option>
                ))}
            </select>
            <svg
                className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-faint"
                viewBox="0 0 20 20"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.6"
                aria-hidden="true"
            >
                <path d="M6 8l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
        </div>
    );
});

/* ── Switch ─────────────────────────────────────────── */

export function Switch({
    checked,
    onChange,
    disabled,
    label,
}: {
    checked: boolean;
    onChange: (v: boolean) => void;
    disabled?: boolean;
    /** 시각적 라벨이 따로 없을 때 스크린 리더용 이름. */
    label?: string;
}) {
    const { t } = useLanguage();
    return <button type="button" role="switch" aria-checked={checked} aria-label={label ? t(label) : undefined} disabled={disabled} onClick={() => onChange(!checked)} className="ui-switch">
        <span aria-hidden="true" className="ui-switch-track" /><span aria-hidden="true" className="ui-switch-thumb" />
    </button>;
}

/* ── Button ─────────────────────────────────────────── */

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: ButtonVariant;
    icon?: LucideIcon;
    loading?: boolean;
}>(function Button({
    children,
    variant = "secondary",
    icon,
    loading,
    className,
    disabled,
    ...props
}, ref) {
    const { t } = useLanguage();
    const variants: Record<ButtonVariant, string> = { primary: "btn-primary", secondary: "btn-secondary", ghost: "btn-ghost", danger: "btn-danger" };
    return (
        <button
            ref={ref}
            className={clsx("ui-button", variants[variant], className)}
            aria-busy={loading || undefined}
            disabled={disabled || loading}
            {...props}
        >
            {loading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
                icon && createElement(icon, { className: "w-4 h-4" })
            )}
            {typeof children === "string" ? t(children) : children}
        </button>
    );
});

/* ── Badge ──────────────────────────────────────────── */

export function Badge({
    children,
    tone = "neutral",
    className,
}: {
    children: ReactNode;
    tone?: "neutral" | "ok" | "warn" | "danger" | "info" | "primary";
    className?: string;
}) {
    const { t } = useLanguage();
    return <span className={clsx("ui-badge", `ui-badge-${tone}`, className)}>{typeof children === "string" ? t(children) : children}</span>;
}

/** 연결/설정 상태를 나타내는 점 + 텍스트. */
export function StatusDot({
    active,
    label,
    tone = "ok",
}: {
    active: boolean;
    label: string;
    tone?: "ok" | "warn" | "danger";
}) {
    const { t } = useLanguage();
    const color =
        tone === "danger" ? "var(--color-danger)"
        : tone === "warn" ? "var(--color-warn)"
        : "var(--color-ok)";

    return (
        <span className="inline-flex items-center gap-2 text-[13px] text-ink-muted">
            <span
                className="w-2 h-2 rounded-full shrink-0"
                style={{ backgroundColor: active ? color : "var(--color-line-strong)" }}
            />
            {t(label)}
        </span>
    );
}

/* ── EmptyState ─────────────────────────────────────── */

export function EmptyState({
    icon,
    title,
    description,
    action,
    compact = false,
}: {
    icon?: LucideIcon;
    title: string;
    description?: ReactNode;
    action?: ReactNode;
    compact?: boolean;
}) {
    const { t } = useLanguage();
    return <div className={clsx("ui-empty", compact && "py-6")}>
        {icon && <span className="ui-empty-icon">{createElement(icon, { className: "size-5" })}</span>}
        <p className="ui-empty-title">{t(title)}</p>
        {description && <p className="ui-empty-description">{typeof description === "string" ? t(description) : description}</p>}
        {action && <div className="ui-empty-action">{action}</div>}
    </div>;
}

/* ── Divider ────────────────────────────────────────── */

export function Divider({ className }: { className?: string }) {
    return <hr className={clsx("border-0 border-t border-line", className)} />;
}

/** A stable list-shaped placeholder for initial data loads. */
export function LoadingState({ label, rows = 3 }: { label: string; rows?: number }) {
    const { t } = useLanguage();
    return <div className="space-y-3 py-3" role="status" aria-busy="true" aria-label={t(label)}><span className="sr-only">{t(label)}</span>{Array.from({length: rows}, (_,index) => <div key={index} className="flex items-center gap-3 border-b border-line pb-3"><span className="skeleton size-8 shrink-0 rounded" /><div className="flex-1 space-y-2"><div className="skeleton h-3 w-2/5" /><div className="skeleton h-3 w-3/5" /></div></div>)}</div>;
}
