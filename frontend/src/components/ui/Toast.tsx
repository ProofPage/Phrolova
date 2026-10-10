import { createContext, useContext, useState, useCallback, useMemo, useRef } from "react";
import { CheckCircle, AlertCircle, AlertTriangle, X } from "lucide-react";
import { clsx } from "clsx";
import { localizePlatformNames } from '../../utils/platformNames';

// ── Types ────────────────────────────────────

export type ToastType = "success" | "error" | "warning";

export interface ToastHistoryItem {
    id: string;
    type: ToastType;
    message: string;
    timestamp: Date;
    read: boolean;
}

interface Toast {
    id: string;
    type: ToastType;
    message: string;
}

/** 토스트를 띄우는 동작만 모은 값. 참조가 앱 수명 동안 고정된다. */
export interface ToastActions {
    toast: (type: ToastType, message: string) => void;
    success: (message: string) => void;
    error: (message: string) => void;
    warning: (message: string) => void;
}

/** 알림 센터가 읽는 누적 내역. 토스트가 뜨고 질 때마다 바뀐다. */
export interface ToastHistoryValue {
    history: ToastHistoryItem[];
    markAllRead: () => void;
    clearHistory: () => void;
}

// ── Context ────────────────────────────────

/**
 * 동작과 내역을 다른 컨텍스트로 나눈다.
 *
 * 하나로 묶어 두면 토스트가 뜨거나 4초 뒤 사라질 때마다 컨텍스트 값이
 * 새 객체가 된다. 그 값을 useCallback/useEffect 의존성에 넣은 화면은
 * 토스트 하나마다 데이터를 통째로 다시 불렀고, 조회가 실패해 error 토스트를
 * 띄우는 화면에서는 실패 → 토스트 → 재조회 → 실패로 요청이 무한히 반복됐다.
 */
const ToastActionsContext = createContext<ToastActions | null>(null);
const ToastHistoryContext = createContext<ToastHistoryValue | null>(null);

export function useToast(): ToastActions {
    const ctx = useContext(ToastActionsContext);
    if (!ctx) throw new Error("useToast must be used within ToastProvider");
    return ctx;
}

/** 알림 센터처럼 누적 내역이 필요한 곳에서만 쓴다. */
export function useToastHistory(): ToastHistoryValue {
    const ctx = useContext(ToastHistoryContext);
    if (!ctx) throw new Error("useToastHistory must be used within ToastProvider");
    return ctx;
}

// ── Provider ──────────────────────────────

export function ToastProvider({ children }: { children: React.ReactNode }) {
    const [toasts, setToasts] = useState<Toast[]>([]);
    const [history, setHistory] = useState<ToastHistoryItem[]>([]);
    const counterRef = useRef(0);

    const removeToast = useCallback((id: string) => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
    }, []);

    const addToast = useCallback(
        (type: ToastType, message: string) => {
            message = localizePlatformNames(message);
            const id = `toast-${++counterRef.current}`;
            setToasts((prev) => [...prev, { id, type, message }]);

            setHistory((prev) => {
                const newHistory = [{ id, type, message, timestamp: new Date(), read: false }, ...prev];
                return newHistory.slice(0, 50);
            });

            setTimeout(() => removeToast(id), 4000);
        },
        [removeToast],
    );

    const markAllRead = useCallback(() => {
        setHistory((prev) => prev.map((item) => ({ ...item, read: true })));
    }, []);

    const clearHistory = useCallback(() => {
        setHistory([]);
        setToasts([]);
    }, []);

    // addToast가 고정이므로 이 객체도 마운트 이후 바뀌지 않는다.
    const actions = useMemo<ToastActions>(
        () => ({
            toast: addToast,
            success: (message: string) => addToast("success", message),
            error: (message: string) => addToast("error", message),
            warning: (message: string) => addToast("warning", message),
        }),
        [addToast],
    );

    const historyValue = useMemo<ToastHistoryValue>(
        () => ({ history, markAllRead, clearHistory }),
        [history, markAllRead, clearHistory],
    );

    return (
        <ToastActionsContext.Provider value={actions}>
            <ToastHistoryContext.Provider value={historyValue}>
                {children}
                {/* 토스트 컨테이너 */}
                <div className="toast-stack fixed bottom-4 max-sm:bottom-[max(1rem,env(safe-area-inset-bottom))] right-3 left-3 sm:left-auto sm:right-4 z-[9999] flex flex-col gap-2 pointer-events-none">
                    {toasts.slice(-3).map((t) => (
                        <ToastItem key={t.id} toast={t} onClose={() => removeToast(t.id)} />
                    ))}
                </div>
            </ToastHistoryContext.Provider>
        </ToastActionsContext.Provider>
    );
}

// ── Toast Item ────────────────────────────

const iconMap = {
    success: CheckCircle,
    error: AlertCircle,
    warning: AlertTriangle,
};

const colorMap = {
    success: "border-line-strong bg-surface-2 text-ok",
    error: "border-line-strong bg-surface-2 text-danger",
    warning: "border-line-strong bg-surface-2 text-warn",
};

function ToastItem({ toast, onClose }: { toast: Toast; onClose: () => void }) {
    const Icon = iconMap[toast.type];

    return (
        <div
            role={toast.type === "error" ? "alert" : "status"}
            className={clsx(
                "pointer-events-auto flex items-center gap-3 px-4 py-3 rounded-[var(--radius-card)] border shadow-lg",
                "w-full sm:w-[360px] max-w-full animate-slide-in",
                colorMap[toast.type],
            )}
        >
            <Icon className="w-5 h-5 shrink-0" />
            <span className="min-w-0 flex-1 [overflow-wrap:anywhere] text-[13px] text-ink-muted">{toast.message}</span>
            <button
                onClick={onClose}
                className="icon-button" aria-label="알림 닫기"
            >
                <X className="w-4 h-4" />
            </button>
        </div>
    );
}
