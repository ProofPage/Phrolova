import { useLanguage } from "../../contexts/LanguageContext";
import { useEffect } from "react";
import { type Settings as SettingsType } from "../../api/client";
import { PlatformCookieAuth } from "./PlatformCookieAuth";
import { RplaySessionAuth } from "./RplaySessionAuth";
import { Card } from "../ui/primitives";

interface Props {
    settings: SettingsType | null;
    onSaved: () => void;
    onDirtyChange?: (dirty: boolean) => void;
}

export function AuthTab({ onSaved, onDirtyChange }: Props) {
    const { t } = useLanguage();
    // File registration saves immediately, so this tab has no unsaved text fields.
    useEffect(() => onDirtyChange?.(false), [onDirtyChange]);
    const cards = [
        ...(["chzzk", "youtube", "cime", "kick", "twitch", "tiktok", "bilibili", "pandalive", "popkontv", "tvchak", "hearheart"] as const)
            .map(platform => <PlatformCookieAuth key={platform} platform={platform} onSaved={onSaved} />),
        <RplaySessionAuth key="rplay" onSaved={onSaved} />,
    ];
    return (
        <div className="auth-settings">
            <Card className="auth-guidance">
                <h3 className="font-semibold text-ink">{t("settings.authGuideTitle")}</h3>
                <p className="settings-shared-hint">{t("settings.authGuide")}</p>
                <p className="settings-shared-hint">{t("settings.authPermissionHelp")}</p>
            </Card>
            <div className="auth-platform-grid">
                <div className="auth-platform-column">{cards.slice(0, 6)}</div>
                <div className="auth-platform-column">{cards.slice(6)}</div>
            </div>
        </div>
    );
}
