import { useLanguage } from "../../contexts/LanguageContext";
import { translate } from "../../i18n";
import { useListboxPosition } from "../../hooks/useListboxPosition";
import { useListboxKeyboard } from "../../hooks/useListboxKeyboard";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Lock, Plus } from "lucide-react";
import { PlatformSelectTrigger } from "../ui/PlatformSelectTrigger";
import { api, PLATFORM_LABELS, type ChannelDownloadOptions, type Platform, type PlatformStatus } from "../../api/client";
import { ChannelDownloadModal } from "./ChannelDownloadModal";
import { useToast } from "../ui/Toast";
import { Button, Input } from "../ui/primitives";
import { CHZZK_CHANNEL_INPUT_ERROR } from "../../utils/chzzkChannel";
import { parsePlatformChannelInput } from "../../utils/platformChannels";

const PLATFORM_DOT_STYLES: Record<Platform, string> = {
    chzzk: "bg-chzzk",
    youtube: "bg-youtube",
    soop: "bg-soop",
    cime: "bg-cime",
    kick: "bg-kick",
    twitch: "bg-twitch",
    tiktok: "bg-tiktok",
    bilibili: "bg-bilibili",
    pandalive: "bg-pandalive",
    popkontv: "bg-popkontv",
    rplay: "bg-rplay",
};

interface Props {
    platformStatus: PlatformStatus | null;
    onAdded: () => void;
}

export function AddChannelForm({ platformStatus, onAdded }: Props) {
    const { t } = useLanguage();
    const toast = useToast();
    const [channelId, setChannelId] = useState("");
    const [selectedPlatform, setSelectedPlatform] = useState<Platform>("chzzk");
    const [dropdownOpen, setDropdownOpen] = useState(false);
    const dropdownRef = useRef<HTMLDivElement>(null);
    const [loading, setLoading] = useState(false);
    const [settingsOpen, setSettingsOpen] = useState(false);
    const [inputError, setInputError] = useState<string | null>(null);
    const inputId = useId();
    const normalizedChannelId = parsePlatformChannelInput(selectedPlatform, channelId);
    const validationError = selectedPlatform === 'chzzk' ? CHZZK_CHANNEL_INPUT_ERROR : t("live.channelInvalid",{platform:t(PLATFORM_LABELS[selectedPlatform])});

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
        return platformStatus?.[platform]?.enabled ?? true;
    };

    const sortedPlatforms = (Object.keys(PLATFORM_LABELS) as Platform[])
        .sort((a, b) => Number(isPlatformEnabled(b)) - Number(isPlatformEnabled(a)));

    const listboxPosition = useListboxPosition(dropdownOpen, dropdownRef);
    useListboxKeyboard(dropdownOpen, dropdownRef, () => setDropdownOpen(false));

    const handleSubmit = (event: FormEvent) => {
        event.preventDefault();
        if (!channelId.trim()) return;
        if (!normalizedChannelId) {
            setInputError(validationError);
            return;
        }
        setInputError(null);
        setDropdownOpen(false);
        setSettingsOpen(true);
    };

    const handleAdd = async (options: ChannelDownloadOptions) => {
        if (!normalizedChannelId) {
            setInputError(validationError);
            throw new Error(validationError);
        }
        setLoading(true);
        try {
            if (selectedPlatform === "chzzk") {
                await api.addChannel(normalizedChannelId!, options.auto_record, options);
            } else {
                await api.addPlatformChannel(selectedPlatform, normalizedChannelId, options.auto_record, options);
            }
            setChannelId("");
            toast.success("live.channelAdded");
            onAdded();
        } finally {
            setLoading(false);
        }
    };

    const placeholder = selectedPlatform === "chzzk" ? "live.chzzkChannelIDOrHttpsChzzkNaverCom"
        : selectedPlatform === "youtube" ? "live.handleUsernameOrChannelID"
        : selectedPlatform === "soop" ? "live.soopChannelIDOrHttpsPlaySoopliveCom"
        : selectedPlatform === "cime" ? "live.cimeChannelIDOrHttpsCiMe"
        : selectedPlatform === "kick" ? "live.kickChannelIDOrHttpsKickCom"
        : selectedPlatform === "twitch" ? "live.twitchChannelIDOrHttpsTwitchTv"
        : selectedPlatform === "tiktok" ? "live.tiktokChannelIDOrHttpsTiktokCom"
        : selectedPlatform === "rplay" ? "live.rplayChannelIDOrUrl"
        : selectedPlatform === "popkontv" ? "live.popkontvChannelOrUrl"
        : selectedPlatform === "pandalive" ? "live.pandaliveChannelIDOrUrl"
        : selectedPlatform === "bilibili" ? "live.bilibiliRoomIDOrHttpsLiveBilibiliCom"
        : "live.channelID";

    return (
        <>
        <form onSubmit={handleSubmit} aria-label={translate("live.addMonitoredChannel")} className="dashboard-add-channel media-add-form space-y-2">
            <div className="flex w-full min-w-0 flex-col items-stretch gap-2 sm:flex-row">
            <div className="relative min-w-0 shrink-0 w-full sm:w-[120px]" ref={dropdownRef}>
                <PlatformSelectTrigger
                    label={PLATFORM_LABELS[selectedPlatform]}
                    dotClass={PLATFORM_DOT_STYLES[selectedPlatform]}
                    onClick={() => setDropdownOpen((open) => !open)}
                    className="text-ink hover:bg-surface-3 transition-colors whitespace-nowrap"
                    aria-expanded={dropdownOpen}
                    aria-haspopup="listbox"
                    aria-label={t("live.platformSelection",{platform:t(PLATFORM_LABELS[selectedPlatform])})}
                />

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
                                        setInputError(null);
                                        setDropdownOpen(false);
                                    }}
                                    className={`w-full text-left px-3 py-2 text-sm flex items-center gap-2 transition-colors ${enabled ? "text-ink-muted hover:bg-surface-3" : "text-ink-faint opacity-50 cursor-not-allowed"}`}
                                >
                                    <span className={`inline-block w-2 h-2 rounded-full ${enabled ? PLATFORM_DOT_STYLES[platform] : "bg-line-strong"}`} />
                                    <span className="flex-1">{t(PLATFORM_LABELS[platform])}</span>
                                    {!enabled && <span className="flex items-center gap-1 text-[10px]"><Lock className="w-3 h-3" /> {translate("live.setupRequired")}</span>}
                                </button>
                            );
                        })}
                    </div>
                )}
            </div>

            <div className="flex min-w-0 gap-2 sm:flex-1">
            <Input id={inputId} value={channelId} onChange={(event) => { setChannelId(event.target.value); setInputError(null); }} disabled={loading || settingsOpen} aria-label={['chzzk', 'soop', 'cime'].includes(selectedPlatform) ? t("live.channelInput",{platform:t(PLATFORM_LABELS[selectedPlatform])}) : t("live.channelInput",{platform:t(PLATFORM_LABELS[selectedPlatform])})} aria-invalid={!!inputError} aria-describedby={inputError ? `${inputId}-error` : undefined} placeholder={placeholder} className="min-w-0 flex-1" />
                    <Button type="submit" variant="primary" icon={Plus} loading={loading} disabled={!channelId.trim()} aria-label={translate("live.openChannelSetup")} title={translate("live.openChannelSetup")} className="shrink-0 px-3 sm:px-4">
                {translate("live.addChannel")}</Button>
            </div>
            {inputError && <p id={`${inputId}-error`} role="alert" className="text-xs text-danger">{t(inputError)}</p>}
            </div>
            <p className="text-[11px] text-ink-faint leading-relaxed">{translate("live.afterAddingAChannelChooseAutomaticRecordingAndItsConditions")}</p>
        </form>
        {settingsOpen && <ChannelDownloadModal platform={selectedPlatform} name={normalizedChannelId || channelId.trim()} channelId={normalizedChannelId || channelId.trim()} onClose={() => setSettingsOpen(false)} onSave={handleAdd} />}
        </>
    );
}
