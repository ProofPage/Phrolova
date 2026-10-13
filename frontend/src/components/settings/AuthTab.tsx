import { useLanguage } from "../../contexts/LanguageContext";
import { useEffect } from "react";
import { type Settings as SettingsType } from "../../api/client";
import { PlatformCookieAuth } from "./PlatformCookieAuth";

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
            <p className="settings-shared-hint">{t("settings.optionalPublicContentWorksWithoutCookiesRegisterANetscapeFormatCookieFileForContentThatRequiresSignIn")}</p>
            {(["chzzk", "youtube", "soop", "cime"] as const).map(platform => (
                <PlatformCookieAuth key={platform} platform={platform} onSaved={onSaved} />
            ))}
        </div>
    );
}
