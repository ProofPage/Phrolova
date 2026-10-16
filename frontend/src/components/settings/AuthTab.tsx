import { useLanguage } from "../../contexts/LanguageContext";
import { useEffect } from "react";
import { type Settings as SettingsType } from "../../api/client";
import { PlatformCookieAuth } from "./PlatformCookieAuth";
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
    return (
        <div className="auth-settings">
            {(["chzzk", "youtube", "soop", "cime", "kick", "twitch", "tiktok", "bilibili", "pandalive", "popkontv", "tvchak"] as const).map(platform => (
                <PlatformCookieAuth key={platform} platform={platform} onSaved={onSaved} />
            ))}
            <Card className="auth-guidance">
                <p className="settings-shared-hint">{t("settings.optionalPublicContentWorksWithoutCookiesRegisterANetscapeFormatCookieFileForContentThatRequiresSignIn")}</p>
            </Card>
        </div>
    );
}
