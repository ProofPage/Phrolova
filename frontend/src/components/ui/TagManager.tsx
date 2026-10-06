import { createPortal } from "react-dom";
import { useDialogKeyboard } from "../../hooks/useDialogKeyboard";
import { useState, useRef, useEffect } from "react";
import { Tag, X, Plus, Check, Trash2 } from "lucide-react";
import { clsx } from "clsx";

interface TagManagerProps {
    availableTags: string[];
    selectedTags: string[];
    onAddTag: (tag: string) => void;
    onRemoveTag: (tag: string) => void;
    onCreateTag: (tag: string) => void;
    /**
     * 태그를 전역에서 지운다.
     *
     * 넘기지 않으면 삭제 버튼이 아예 그려지지 않는다. 채널 카드에서는 일부러 넘기지
     * 않는다 — "이 채널에서 떼기"와 "전역에서 지우기"가 나란히 놓이면 잘못 누르기 쉽다.
     */
    onDeleteTag?: (tag: string) => void;
    disabled?: boolean;
}

export function TagManager({
    availableTags,
    selectedTags,
    onAddTag,
    onRemoveTag,
    onCreateTag,
    onDeleteTag,
    disabled = false,
}: TagManagerProps) {
    const [isOpen, setIsOpen] = useState(false);
    const [inputValue, setInputValue] = useState("");
    const popupRef = useRef<HTMLDivElement>(null);
    const [position, setPosition] = useState({top:0,left:0});
    useDialogKeyboard(popupRef, () => setIsOpen(false), isOpen);
    const containerRef = useRef<HTMLDivElement>(null);

    // 내부 클릭 이외 시 닫기
    useEffect(() => {
        function handleClickOutside(event: MouseEvent) {
            if (containerRef.current && !containerRef.current.contains(event.target as Node) && !popupRef.current?.contains(event.target as Node)) {
                setIsOpen(false);
                setInputValue("");
            }
        }
        if (isOpen) {
            document.addEventListener("mousedown", handleClickOutside);
        }
        return () => {
            document.removeEventListener("mousedown", handleClickOutside);
        };
    }, [isOpen]);

    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === "Enter" && inputValue.trim()) {
            e.preventDefault();
            const newTag = inputValue.trim();
            if (!availableTags.includes(newTag)) {
                onCreateTag(newTag);
            }
            if (!selectedTags.includes(newTag)) {
                onAddTag(newTag);
            }
            setInputValue("");
        }
        if (e.key === "Escape") {
            setIsOpen(false);
            setInputValue("");
        }
    };

    const toggleTag = (tag: string) => {
        if (selectedTags.includes(tag)) {
            onRemoveTag(tag);
        } else {
            onAddTag(tag);
        }
    };

    const unselectedTags = availableTags.filter((t) => !selectedTags.includes(t));
    const filteredAvailable = unselectedTags.filter((t) =>
        t.toLowerCase().includes(inputValue.toLowerCase())
    );

    const isExactMatchFree =
        inputValue.trim() !== "" && !availableTags.includes(inputValue.trim());

    return (
        <div className="relative inline-flex items-center gap-1.5 flex-wrap" ref={containerRef}>
            {/* 선택된 태그 목록 */}
            {selectedTags.map((tag) => (
                <span
                    key={tag}
                    className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium btn-ghost-primary border border-transparent"
                >
                    {tag}
                    {!disabled && (
                        <button
                            onClick={() => onRemoveTag(tag)}
                            aria-label={`${tag} 태그 제거`} title={`${tag} 태그 제거`} className="icon-button !size-6"
                        >
                            <X className="w-2.5 h-2.5" />
                        </button>
                    )}
                </span>
            ))}

            {/* 태그 추가 버튼 */}
            {!disabled && (
                <button
                    onClick={(event) => { const rect = event.currentTarget.getBoundingClientRect(); setPosition({left: Math.max(8,Math.min(rect.left,window.innerWidth - 216)), top: Math.max(8,Math.min(rect.bottom + 6,window.innerHeight - 270))}); setIsOpen(true); }}
                    aria-label="태그 관리" aria-expanded={isOpen}
                    className="icon-button"
                    title="태그 관리"
                >
                    <Plus className="w-3 h-3" />
                </button>
            )}

            {/* 드롭다운 */}
            {isOpen && !disabled && createPortal(
                <div ref={popupRef} role="dialog" aria-modal="true" aria-label="태그 관리" tabIndex={-1} style={position} className="ui-popover fixed z-[100] w-52 max-h-[80dvh] overflow-y-auto text-sm">
                    <div className="p-2 border-b border-line bg-surface-1/70">
                        <div className="relative flex items-center">
                            <Tag className="absolute left-2 w-3.5 h-3.5 text-ink-faint" />
                            <input
                                type="text"
                                autoFocus
                                value={inputValue}
                                onChange={(e) => setInputValue(e.target.value)}
                                onKeyDown={handleKeyDown}
                                aria-label="태그 검색 또는 생성" placeholder="태그 검색 또는 생성..."
                                className="w-full bg-transparent text-ink placeholder:text-ink-faint pl-7 pr-2 py-1 text-xs focus:outline-none"
                            />
                        </div>
                    </div>
                    <div className="max-h-40 overflow-y-auto scrollbar-thin py-1">
                        {isExactMatchFree && (
                            <button
                                onClick={() => {
                                    const newTag = inputValue.trim();
                                    onCreateTag(newTag);
                                    onAddTag(newTag);
                                    setInputValue("");
                                }}
                                className="w-full text-left min-h-9 px-3 py-2 text-xs text-[var(--primary)] hover:bg-surface-3 transition-colors flex items-center gap-2"
                            >
                                <Plus className="w-3.5 h-3.5" />
                                <span>"{inputValue.trim()}" 생성</span>
                            </button>
                        )}
                        {filteredAvailable.map((tag) => (
                            // 버튼 안에 버튼을 넣을 수 없어 행을 감싼다.
                            <div key={tag} className="flex items-center group/tag">
                                <button
                                    onClick={() => toggleTag(tag)}
                                    className={clsx(
                                        "flex-1 min-w-0 text-left min-h-9 px-3 py-2 text-xs transition-colors flex items-center justify-between",
                                        selectedTags.includes(tag)
                                            ? "text-[var(--primary)] bg-[var(--primary-dim)]"
                                            : "text-ink-muted hover:bg-surface-3 hover:text-ink"
                                    )}
                                >
                                    <span className="truncate mr-2">{tag}</span>
                                    {selectedTags.includes(tag) && <Check className="w-3 h-3 shrink-0" />}
                                </button>
                                {onDeleteTag && (
                                    <button
                                        onClick={() => onDeleteTag(tag)}
                                        title={`'${tag}' 태그를 전역에서 삭제`}
                                        aria-label={`${tag} 태그를 전역에서 삭제`}
                                        className="shrink-0 px-2 py-1.5 text-ink-faint opacity-0 group-hover/tag:opacity-100 focus-visible:opacity-100 hover:text-danger transition-opacity focus:outline-none"
                                    >
                                        <Trash2 className="w-3 h-3" />
                                    </button>
                                )}
                            </div>
                        ))}
                        {filteredAvailable.length === 0 && !isExactMatchFree && (
                            <div className="px-3 py-2 text-xs text-ink-faint text-center">
                                결과 없음
                            </div>
                        )}
                    </div>
                </div>, document.body
            )}
        </div>
    );
}
