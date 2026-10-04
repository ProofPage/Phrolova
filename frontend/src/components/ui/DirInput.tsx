import { useState, useEffect, useCallback } from "react";
import { Folder, FolderOpen, HardDrive, ArrowLeft, ChevronRight, X, Loader2 } from "lucide-react";
import { api, BrowseDirsResponse, DirEntry } from "../../api/client";
import { Button, Input } from "./primitives";

// ── DirBrowserModal ──────────────────────────────────────

interface DirBrowserModalProps {
    initialPath?: string;
    onSelect: (path: string) => void;
    onClose: () => void;
}

function DirBrowserModal({ initialPath, onSelect, onClose }: DirBrowserModalProps) {
    const [data, setData] = useState<BrowseDirsResponse | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const navigate = useCallback(async (path?: string) => {
        setLoading(true);
        setError(null);
        try {
            const res = await api.browseDirs(path);
            setData(res);
        } catch {
            setError("디렉토리를 불러올 수 없습니다.");
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        navigate(initialPath || undefined);
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        const handler = (e: KeyboardEvent) => {
            if (e.key === "Escape") onClose();
        };
        window.addEventListener("keydown", handler);
        return () => window.removeEventListener("keydown", handler);
    }, [onClose]);

    const isDrive = (path: string) => /^[A-Z]:\\$/.test(path);

    return (
        <div
            className="fixed inset-0 z-[9998] flex items-center justify-center"
            onClick={onClose}
        >
            <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />

            <div
                className="relative bg-surface-2 border border-line-strong rounded-[calc(var(--radius-card)+4px)] shadow-2xl surface-raise animate-modal-in
                           w-full max-w-lg mx-4 flex flex-col"
                style={{ maxHeight: "70vh" }}
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div className="flex items-center justify-between px-5 py-4 border-b border-line">
                    <h3 className="text-ink font-semibold text-base flex items-center gap-2">
                        <Folder className="w-4 h-4 text-[var(--primary)]" />
                        폴더 선택
                    </h3>
                    <div className="flex items-center gap-1">
                        {/* 드라이브 리스트로 이동 버튼 */}
                        <button
                            onClick={() => navigate(undefined)}
                            title="드라이브 목록으로"
                            className="p-1.5 rounded-lg text-ink-faint hover:text-[var(--primary)] hover:bg-surface-3 transition-colors"
                        >
                            <HardDrive className="w-4 h-4" />
                        </button>
                        <button
                            onClick={onClose}
                            className="p-1.5 rounded-lg text-ink-faint hover:text-ink hover:bg-surface-3 transition-colors"
                        >
                            <X className="w-4 h-4" />
                        </button>
                    </div>
                </div>

                {/* Current Path */}
                <div className="px-5 py-2 bg-surface-1 border-b border-line">
                    <p className="text-xs text-ink-faint font-mono truncate">
                        {data?.current || "드라이브 선택"}
                    </p>
                </div>

                {/* Dir List */}
                <div className="flex-1 overflow-y-auto py-1 min-h-0">
                    {loading && (
                        <div className="flex items-center justify-center py-10">
                            <Loader2 className="w-5 h-5 animate-spin text-[var(--primary)]" />
                        </div>
                    )}

                    {error && (
                        <p className="text-danger text-sm text-center py-8">{error}</p>
                    )}

                    {!loading && !error && data && (
                        <>
                            {/* 상위 폴더로 */}
                            {data.parent !== null && (
                                <button
                                    onClick={() => navigate(data.parent ?? undefined)}
                                    className="w-full flex items-center gap-3 px-5 py-2.5 text-left
                                               text-ink-faint hover:bg-surface-3 hover:text-ink
                                               transition-colors text-sm"
                                >
                                    <ArrowLeft className="w-4 h-4 shrink-0" />
                                    <span className="font-mono">..</span>
                                </button>
                            )}

                            {data.dirs.length === 0 && (
                                <p className="text-ink-faint text-sm text-center py-8">
                                    하위 폴더 없음
                                </p>
                            )}

                            {data.dirs.map((dir: DirEntry) => (
                                <button
                                    key={dir.path}
                                    onClick={() => navigate(dir.path)}
                                    className="w-full flex items-center gap-3 px-5 py-2.5 text-left
                                               text-ink-muted hover:bg-surface-3 hover:text-ink
                                               transition-colors text-sm group"
                                >
                                    {isDrive(dir.path) ? (
                                        <HardDrive className="w-4 h-4 shrink-0 text-ink-faint group-hover:text-[var(--primary)] transition-colors" />
                                    ) : (
                                        <Folder className="w-4 h-4 shrink-0 text-ink-faint group-hover:text-[var(--primary)] transition-colors" />
                                    )}
                                    <span className="flex-1 truncate">{dir.name}</span>
                                    <ChevronRight className="w-3 h-3 text-ink-faint group-hover:text-ink-muted shrink-0" />
                                </button>
                            ))}
                        </>
                    )}
                </div>

                {/* Footer */}
                <div className="px-5 py-4 border-t border-line flex gap-3">
                    <Button onClick={onClose} className="flex-1">취소</Button>
                    <Button
                        onClick={() => {
                            if (data?.current) {
                                onSelect(data.current);
                                onClose();
                            }
                        }}
                        disabled={!data?.current}
                        variant="primary"
                        className="flex-1"
                    >
                        이 폴더 선택
                    </Button>
                </div>
            </div>
        </div>
    );
}

// ── DirInput ─────────────────────────────────────────────

interface DirInputProps {
    value: string;
    onChange: (v: string) => void;
    placeholder?: string;
    focusBorderColor?: string;
}

export function DirInput({
    value,
    onChange,
    placeholder = "경로 입력...",
    focusBorderColor = "focus:border-[#00FFA3]",
}: DirInputProps) {
    const [showBrowser, setShowBrowser] = useState(false);

    return (
        <>
            <div className="flex gap-2">
                <Input
                    type="text"
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    className={`flex-1 font-mono text-sm ${focusBorderColor}`}
                    placeholder={placeholder}
                />
                <Button type="button" icon={FolderOpen} onClick={() => setShowBrowser(true)} className="px-3 shrink-0" title="폴더 찾아보기">
                    <span className="hidden sm:inline">찾아보기</span>
                </Button>
            </div>

            {showBrowser && (
                <DirBrowserModal
                    initialPath={value || undefined}
                    onSelect={onChange}
                    onClose={() => setShowBrowser(false)}
                />
            )}
        </>
    );
}
