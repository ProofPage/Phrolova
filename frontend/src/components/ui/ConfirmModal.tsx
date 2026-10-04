import { useEffect, useRef, createContext, useContext, useState, useCallback } from "react";
import { AlertTriangle } from "lucide-react";
import { Button, Input } from "./primitives";

// ── Types ────────────────────────────────────────────

interface ConfirmOptions {
    title: string;
    message: string;
    confirmText?: string;
    cancelText?: string;
    variant?: "danger" | "default";
    requireTyping?: string;
}

interface ConfirmContextValue {
    confirm: (options: ConfirmOptions) => Promise<boolean>;
}

// ── Context ──────────────────────────────────────────

const ConfirmContext = createContext<ConfirmContextValue | null>(null);

export function useConfirm(): (options: ConfirmOptions) => Promise<boolean> {
    const ctx = useContext(ConfirmContext);
    if (!ctx) throw new Error("useConfirm must be used within ConfirmProvider");
    return ctx.confirm;
}

// ── Provider ─────────────────────────────────────────

interface PendingConfirm {
    options: ConfirmOptions;
    resolve: (value: boolean) => void;
}

export function ConfirmProvider({ children }: { children: React.ReactNode }) {
    const [pending, setPending] = useState<PendingConfirm | null>(null);

    const handleConfirm = useCallback((options: ConfirmOptions): Promise<boolean> => {
        return new Promise<boolean>((resolve) => {
            setPending({ options, resolve });
        });
    }, []);

    const handleResult = useCallback(
        (result: boolean) => {
            pending?.resolve(result);
            setPending(null);
        },
        [pending],
    );

    return (
        <ConfirmContext.Provider value={{ confirm: handleConfirm }}>
            {children}
            {pending && (
                <ConfirmModal
                    {...pending.options}
                    onConfirm={() => handleResult(true)}
                    onCancel={() => handleResult(false)}
                />
            )}
        </ConfirmContext.Provider>
    );
}

// ── Modal Component ──────────────────────────────────

interface ConfirmModalProps extends ConfirmOptions {
    onConfirm: () => void;
    onCancel: () => void;
}

function ConfirmModal({
    title,
    message,
    confirmText = "확인",
    cancelText = "취소",
    variant = "default",
    requireTyping,
    onConfirm,
    onCancel,
}: ConfirmModalProps) {
    const [inputValue, setInputValue] = useState("");
    const confirmBtnRef = useRef<HTMLButtonElement>(null);

    useEffect(() => {
        confirmBtnRef.current?.focus();

        const handleKeyDown = (e: KeyboardEvent) => {
            if (e.key === "Escape") onCancel();
        };
        window.addEventListener("keydown", handleKeyDown);
        return () => window.removeEventListener("keydown", handleKeyDown);
    }, [onCancel]);

    const isDanger = variant === "danger";
    const isMatch = requireTyping ? inputValue === requireTyping : true;

    return (
        <div
            className="fixed inset-0 z-[9998] flex items-center justify-center animate-backdrop"
            onClick={onCancel}
        >
            {/* Backdrop */}
            <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />

            {/* Modal */}
            <div
                className="relative bg-surface-2/95 backdrop-blur-xl border border-line-strong rounded-[calc(var(--radius-card)+4px)] shadow-2xl p-6 w-full max-w-sm mx-4 animate-modal-in surface-raise"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex items-start gap-4 mb-5">
                    {isDanger && (
                        <div className="shrink-0 w-10 h-10 rounded-[var(--radius-control)] bg-danger/10 border border-danger/20 flex items-center justify-center">
                            <AlertTriangle className="w-5 h-5 text-danger" />
                        </div>
                    )}
                    <div>
                        <h3 className="text-ink font-bold text-lg">{title}</h3>
                        <p className="text-ink-muted text-sm mt-1 whitespace-pre-line">{message}</p>
                    </div>
                </div>

                {requireTyping && (
                    <div className="mb-5">
                        <label className="block text-xs text-ink-muted mb-2">
                            계속하려면 <strong className="text-ink">'{requireTyping}'</strong>을(를) 입력하세요.
                        </label>
                        <Input
                            type="text"
                            value={inputValue}
                            onChange={(e) => setInputValue(e.target.value)}
                            className="text-sm"
                            placeholder={requireTyping}
                            autoFocus
                        />
                    </div>
                )}

                <div className="flex gap-3 justify-end">
                    <Button onClick={onCancel}>{cancelText}</Button>
                    <Button
                        ref={confirmBtnRef}
                        onClick={onConfirm}
                        disabled={!isMatch}
                        variant={isDanger ? "danger" : "primary"}
                    >
                        {confirmText}
                    </Button>
                </div>
            </div>
        </div>
    );
}
