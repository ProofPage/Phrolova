import { useListboxPosition } from "../../hooks/useListboxPosition";
import { useListboxKeyboard } from "../../hooks/useListboxKeyboard";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { ChevronDown, Lock, Plus } from "lucide-react";
import { api, PLATFORM_LABELS, type ChannelDownloadOptions, type Platform, type PlatformStatus } from "../../api/client";
import { ChannelDownloadModal } from "./ChannelDownloadModal";
import { useToast } from "../ui/Toast";
import { Button, Input } from "../ui/primitives";

const PLATFORM_DOT_STYLES: Record<Platform, string> = {
    chzzk: "bg-chzzk",
    x_spaces: "bg-xspaces",
    youtube: "bg-youtube",
};

interface Props {
    platformStatus: PlatformStatus | null;
    onAdded: () => void;
}

export function AddChannelForm({ platformStatus, onAdded }: Props) {
    const toast = useToast();
    const [channelId, setChannelId] = useState("");
    const [selectedPlatform, setSelectedPlatform] = useState<Platform>("chzzk");
    const [dropdownOpen, setDropdownOpen] = useState(false);
    const dropdownRef = useRef<HTMLDivElement>(null);
    const [loading, setLoading] = useState(false);
    const [settingsOpen, setSettingsOpen] = useState(false);

    useEffect(() => {
        if (!dropdownOpen) return;
        const closeOutside = (event: MouseEvent) => {
            if (!dropdownRef.current?.contains(event.target as Node)) setDropdownOpen(false);
        };
        const closeEscape = (event: KeyboardEvent) => { if (event.key === "Escape") setDropdownOpen(false); };
        document.addEventListener("mousedown", closeOutside);
        document.addEventListener("keydown", closeEscape);
        return () => { document.removeEventListener("mousedown", closeOutside); document.removeEventListener("keydown", closeEscape); };
    }, [dropdownOpen]);

    const isPlatformEnabled = (platform: Platform): boolean => {
        if (platform === "chzzk" || platform === "youtube") return true;
        if (!platformStatus) return false;
        return platformStatus.x_spaces.authenticated;
    };

    const sortedPlatforms = (Object.keys(PLATFORM_LABELS) as Platform[])
        .sort((a, b) => Number(isPlatformEnabled(b)) - Number(isPlatformEnabled(a)));

    const listboxPosition = useListboxPosition(dropdownOpen, dropdownRef);
    useListboxKeyboard(dropdownOpen, dropdownRef, () => setDropdownOpen(false));

    const handleSubmit = (event: FormEvent) => {
        event.preventDefault();
        if (!channelId.trim()) return;
        setDropdownOpen(false);
        setSettingsOpen(true);
    };

    const handleAdd = async (options: ChannelDownloadOptions) => {
        setLoading(true);
        try {
            if (selectedPlatform === "chzzk") {
                await api.addChannel(channelId.trim(), options.auto_record, options);
            } else {
                await api.addPlatformChannel(selectedPlatform, channelId.trim(), options.auto_record);
            }
            setChannelId("");
            toast.success("채널이 추가되었습니다.");
            onAdded();
        } finally {
            setLoading(false);
        }
    };

    const placeholder = selectedPlatform === "chzzk" ? "Chzzk 채널 ID"
        : selectedPlatform === "youtube" ? "핸들(@username) 또는 채널 ID"
        : selectedPlatform === "x_spaces" ? "X 유저네임 입력"
        : "채널 ID";

    return (
        <>
        <form onSubmit={handleSubmit} aria-label="감시 채널 추가" className="dashboard-add-channel space-y-2">
            <div className="flex w-full min-w-0 flex-col items-stretch gap-2 sm:flex-row">
            <div className="relative shrink-0" ref={dropdownRef}>
                <button
                    type="button"
                    onClick={() => setDropdownOpen((open) => !open)}
                    className="ui-input w-auto px-3 text-ink text-sm flex items-center gap-1.5 hover:bg-surface-3 transition-colors whitespace-nowrap"
                    aria-expanded={dropdownOpen}
                    aria-haspopup="listbox"
                    aria-label={`플랫폼 선택: ${PLATFORM_LABELS[selectedPlatform]}`}
                >
                    <span className={`inline-block w-2 h-2 rounded-full ${PLATFORM_DOT_STYLES[selectedPlatform]}`} />
                    <span>{PLATFORM_LABELS[selectedPlatform]}</span>
                    <ChevronDown className="w-3 h-3 text-ink-faint" />
                </button>

                {dropdownOpen && (
                    <div style={listboxPosition} className="ui-popover absolute top-full mt-2 left-0 z-20 rounded-[var(--radius-control)] min-w-[180px] max-h-[50dvh] overflow-y-auto" role="listbox">
                        {sortedPlatforms.map((platform) => {
                            const enabled = isPlatformEnabled(platform);
                            return (
                                <button
                                    key={platform}
                                    type="button"
                                    role="option"
                                    aria-selected={selectedPlatform === platform}
                                    disabled={!enabled}
                                    onClick={() => {
                                        setSelectedPlatform(platform);
                                        setDropdownOpen(false);
                                    }}
                                    className={`w-full text-left px-3 py-2 text-sm flex items-center gap-2 transition-colors ${enabled ? "text-ink-muted hover:bg-surface-3" : "text-ink-faint opacity-50 cursor-not-allowed"}`}
                                >
                                    <span className={`inline-block w-2 h-2 rounded-full ${enabled ? PLATFORM_DOT_STYLES[platform] : "bg-line-strong"}`} />
                                    <span className="flex-1">{PLATFORM_LABELS[platform]}</span>
                                    {!enabled && <span className="flex items-center gap-1 text-[10px]"><Lock className="w-3 h-3" /> 설정 필요</span>}
                                </button>
                            );
                        })}
                    </div>
                )}
            </div>

            <div className="flex min-w-0 gap-2 sm:flex-1">
            <Input value={channelId} onChange={(event) => setChannelId(event.target.value)} aria-label={`${PLATFORM_LABELS[selectedPlatform]} 채널 ID`} placeholder={placeholder} className="min-w-0 flex-1" />
                    <Button type="submit" variant="primary" icon={Plus} loading={loading} disabled={!channelId.trim()} aria-label="채널 추가 설정 열기" title="채널 추가 설정 열기" className="shrink-0 px-3 sm:px-4">
                채널 추가
            </Button>
            </div>
            </div>
            <p className="text-[11px] text-ink-faint leading-relaxed">채널을 추가한 뒤 자동 녹화 여부와 조건을 선택할 수 있습니다.</p>
        </form>
        {settingsOpen && <ChannelDownloadModal platform={selectedPlatform} name={channelId.trim()} onClose={() => setSettingsOpen(false)} onSave={handleAdd} />}
        </>
    );
}
