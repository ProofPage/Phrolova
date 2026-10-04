/**
 * 공용 UI 프리미티브.
 *
 * 페이지마다 같은 카드/입력/토글 마크업을 복사해 쓰던 것을 한곳으로 모았다.
 * 색상은 index.css의 의미 토큰(surface/ink/line)과 --primary만 사용한다.
 */
import {
    createElement,
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

/* ── PageHeader ──────────────────────────────────────── */

/**
 * 페이지마다 제각각이던 제목 영역을 하나의 시각적 진입점으로 묶는다.
 * 핵심 상태와 주요 액션을 첫 화면에서 함께 읽을 수 있게 한다.
 */
export function PageHeader({
    icon,
    eyebrow,
    title,
    description,
    meta,
    actions,
}: {
    icon: LucideIcon;
    eyebrow?: string;
    title: string;
    description: ReactNode;
    meta?: ReactNode;
    actions?: ReactNode;
}) {
    return (
        <header className="page-hero relative border border-line rounded-[calc(var(--radius-card)+4px)] p-5 sm:p-6">
            <div aria-hidden="true" className="page-hero-decoration pointer-events-none absolute inset-0 overflow-hidden rounded-[inherit]" />
            <div className="relative z-10 flex flex-col xl:flex-row xl:items-center justify-between gap-5">
                <div className="flex items-start gap-4 min-w-0">
                    <span className="page-hero-icon grid place-items-center w-11 h-11 rounded-[var(--radius-card)] shrink-0">
                        {createElement(icon, { className: "w-5 h-5" })}
                    </span>
                    <div className="min-w-0">
                        {eyebrow && <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-ink-faint mb-1.5">{eyebrow}</p>}
                        <h1 className="text-[24px] sm:text-[28px] font-bold tracking-[-0.035em] text-ink leading-none">{title}</h1>
                        <p className="text-[13px] sm:text-[14px] text-ink-faint mt-2 max-w-2xl leading-relaxed">{description}</p>
                        {meta && <div className="flex flex-wrap items-center gap-2 mt-3">{meta}</div>}
                    </div>
                </div>
                {actions && <div className="shrink-0 xl:max-w-[52%]">{actions}</div>}
            </div>
        </header>
    );
}

/* ── MetricCard ──────────────────────────────────────── */

export function MetricCard({
    icon,
    label,
    value,
    detail,
    tone = "primary",
}: {
    icon: LucideIcon;
    label: string;
    value: ReactNode;
    detail?: ReactNode;
    tone?: "primary" | "live" | "ok" | "warn" | "info";
}) {
    const color = tone === "live" ? "var(--color-live)"
        : tone === "ok" ? "var(--color-ok)"
        : tone === "warn" ? "var(--color-warn)"
        : tone === "info" ? "var(--color-info)"
        : "var(--primary)";

    return (
        <Card className="relative overflow-hidden group">
            <span className="absolute inset-x-0 top-0 h-px opacity-70" style={{ background: `linear-gradient(90deg, transparent, ${color}, transparent)` }} />
            <div className="flex items-start justify-between gap-4">
                <div>
                    <p className="text-[11px] font-medium text-ink-faint uppercase tracking-[0.08em]">{label}</p>
                    <p className="text-2xl font-bold tracking-tight text-ink mt-2">{value}</p>
                    {detail && <p className="text-xs text-ink-faint mt-1.5">{detail}</p>}
                </div>
                <span className="w-9 h-9 rounded-[var(--radius-control)] grid place-items-center" style={{ color, backgroundColor: `color-mix(in srgb, ${color} 12%, transparent)` }}>
                    {createElement(icon, { className: "w-[18px] h-[18px]" })}
                </span>
            </div>
        </Card>
    );
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
                "bg-surface-2 border border-line rounded-[var(--radius-card)] surface-raise",
                padded && "p-5 sm:p-6",
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
export function CardHeader({
    icon,
    title,
    description,
    action,
    tone,
}: {
    icon?: LucideIcon;
    title: string;
    description?: ReactNode;
    action?: ReactNode;
    tone?: "primary" | "danger" | "warn" | "ok";
}) {
    const toneColor =
        tone === "danger" ? "var(--color-danger)"
        : tone === "warn" ? "var(--color-warn)"
        : tone === "ok" ? "var(--color-ok)"
        : "var(--primary)";

    return (
        <header className="flex items-start justify-between gap-4 mb-5">
            <div className="flex items-start gap-3 min-w-0">
                {icon && (
                    <span
                        className="mt-0.5 w-9 h-9 rounded-[var(--radius-control)] grid place-items-center shrink-0"
                        style={{
                            backgroundColor: "color-mix(in srgb, " + toneColor + " 14%, transparent)",
                            color: toneColor,
                        }}
                    >
                        {createElement(icon, { className: "w-[18px] h-[18px]" })}
                    </span>
                )}
                <div className="min-w-0">
                    <h3 className="text-[15px] font-semibold text-ink leading-tight">{title}</h3>
                    {description && (
                        <p className="text-[13px] text-ink-faint mt-1 leading-relaxed">{description}</p>
                    )}
                </div>
            </div>
            {action && <div className="shrink-0">{action}</div>}
        </header>
    );
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
            <div className={clsx("flex items-start justify-between gap-4", open && "mb-5")}>
                {/* 헤더 전체가 토글이다. action은 버튼 밖에 둬야 중첩 클릭이 꼬이지 않는다. */}
                <button
                    type="button"
                    onClick={() => setOpen((v) => !v)}
                    aria-expanded={open}
                    aria-controls={bodyId}
                    className="flex items-start gap-3 min-w-0 flex-1 text-left group"
                >
                    {icon && (
                        <span
                            className="mt-0.5 w-9 h-9 rounded-[var(--radius-control)] grid place-items-center shrink-0"
                            style={{
                                backgroundColor: "color-mix(in srgb, " + toneColor + " 14%, transparent)",
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
    return (
        <div className="space-y-2">
            <label
                htmlFor={htmlFor}
                className="block text-[13px] font-medium text-ink-muted"
            >
                {label}
            </label>
            {children}
            {error ? (
                <p className="text-xs text-danger">{error}</p>
            ) : (
                hint && <p className="text-xs text-ink-faint leading-relaxed">{hint}</p>
            )}
        </div>
    );
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
    return (
        <div
            className={clsx(
                "flex items-center justify-between gap-4 py-3",
                className,
            )}
        >
            <div className="min-w-0">
                <p className="text-[13px] font-medium text-ink-muted">{label}</p>
                {hint && <p className="text-xs text-ink-faint mt-0.5 leading-relaxed">{hint}</p>}
            </div>
            <div className="shrink-0">{control}</div>
        </div>
    );
}

/* ── Input ──────────────────────────────────────────── */

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
    function Input({ className, ...props }, ref) {
        return (
            <input
                ref={ref}
                className={clsx(
                    "w-full bg-surface-3 border border-line-strong rounded-[var(--radius-control)]",
                    "px-3 py-2.5 text-[14px] text-ink placeholder:text-ink-faint",
                    "transition-colors input-focus",
                    "disabled:opacity-50 disabled:cursor-not-allowed",
                    className,
                )}
                {...props}
            />
        );
    },
);

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement> & {
    options: { value: string; label: string }[];
}>(function Select({ className, options, ...props }, ref) {
    return (
        <div className="relative">
            <select
                ref={ref}
                className={clsx(
                    "w-full appearance-none cursor-pointer",
                    "bg-surface-3 border border-line-strong rounded-[var(--radius-control)]",
                    "px-3 py-2.5 pr-9 text-[14px] text-ink",
                    "transition-colors input-focus",
                    "disabled:opacity-50 disabled:cursor-not-allowed",
                    className,
                )}
                {...props}
            >
                {options.map((o) => (
                    <option key={o.value} value={o.value}>
                        {o.label}
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
    return (
        <button
            type="button"
            role="switch"
            aria-checked={checked}
            aria-label={label}
            disabled={disabled}
            onClick={() => onChange(!checked)}
            className={clsx(
                "relative inline-flex h-[26px] w-[46px] items-center rounded-full",
                "transition-colors duration-200 shrink-0",
                "disabled:opacity-40 disabled:cursor-not-allowed",
                !checked && "bg-surface-4",
            )}
            style={checked ? { backgroundColor: "var(--primary)" } : undefined}
        >
            <span
                className={clsx(
                    "inline-block h-[20px] w-[20px] rounded-full bg-white shadow-sm",
                    "transition-transform duration-200",
                    checked ? "translate-x-[23px]" : "translate-x-[3px]",
                )}
            />
        </button>
    );
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
    const base =
        "inline-flex items-center justify-center gap-2 rounded-[var(--radius-control)] " +
        "px-4 py-2.5 text-[14px] font-medium transition-colors " +
        "disabled:opacity-45 disabled:cursor-not-allowed";

    const variants: Record<ButtonVariant, string> = {
        primary: "btn-primary",
        secondary: "bg-surface-3 text-ink hover:bg-surface-4 border border-line-strong",
        ghost: "text-ink-muted hover:text-ink hover:bg-surface-3",
        danger: "bg-danger/12 text-danger hover:bg-danger/20 border border-danger/25",
    };

    return (
        <button
            ref={ref}
            className={clsx(base, variants[variant], className)}
            disabled={disabled || loading}
            {...props}
        >
            {loading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
                icon && createElement(icon, { className: "w-4 h-4" })
            )}
            {children}
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
    const tones: Record<string, string> = {
        neutral: "bg-surface-4 text-ink-muted border-line-strong",
        ok: "bg-ok/12 text-ok border-ok/25",
        warn: "bg-warn/12 text-warn border-warn/25",
        danger: "bg-danger/12 text-danger border-danger/25",
        info: "bg-info/12 text-info border-info/25",
        primary: "btn-ghost-primary border-transparent",
    };

    return (
        <span
            className={clsx(
                "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full",
                "text-[11px] font-medium border whitespace-nowrap",
                tones[tone],
                className,
            )}
        >
            {children}
        </span>
    );
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
            {label}
        </span>
    );
}

/* ── EmptyState ─────────────────────────────────────── */

export function EmptyState({
    icon,
    title,
    description,
    action,
}: {
    icon?: LucideIcon;
    title: string;
    description?: ReactNode;
    action?: ReactNode;
}) {
    return (
        <div className="py-12 px-6 text-center">
            {icon && (
                <span className="inline-grid place-items-center w-12 h-12 rounded-full bg-surface-3 text-ink-faint mb-4">
                    {createElement(icon, { className: "w-5 h-5" })}
                </span>
            )}
            <p className="text-[14px] font-medium text-ink-muted">{title}</p>
            {description && (
                <p className="text-[13px] text-ink-faint mt-1.5 max-w-sm mx-auto leading-relaxed">
                    {description}
                </p>
            )}
            {action && <div className="mt-5">{action}</div>}
        </div>
    );
}

/* ── Divider ────────────────────────────────────────── */

export function Divider({ className }: { className?: string }) {
    return <hr className={clsx("border-0 border-t border-line", className)} />;
}
