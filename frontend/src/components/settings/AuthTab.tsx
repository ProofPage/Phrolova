import { useEffect } from "react";
import { type Settings as SettingsType } from "../../api/client";
import { PlatformCookieAuth } from "./PlatformCookieAuth";
import { RplaySessionAuth } from "./RplaySessionAuth";
import { AuthPlatformLayout } from "./AuthPlatformCard";

interface Props {
    settings: SettingsType | null;
    onSaved: () => void;
    onDirtyChange?: (dirty: boolean) => void;
}

export function AuthTab({ onSaved, onDirtyChange }: Props) {
    // File registration saves immediately, so this tab has no unsaved text fields.
    useEffect(() => onDirtyChange?.(false), [onDirtyChange]);
    const cards = [
        ...(["chzzk", "youtube", "cime", "kick", "twitch", "tiktok", "bilibili", "pandalive", "popkontv", "twitcasting", "berriz", "soop", "hearheart", "animaru", "anilife"] as const)
            .map(platform => <PlatformCookieAuth key={platform} platform={platform} onSaved={onSaved} />),
        <RplaySessionAuth key="rplay" onSaved={onSaved} />,
    ];
    return (
        <div className="auth-settings">
            <AuthPlatformLayout>{cards}</AuthPlatformLayout>
        </div>
    );
}
