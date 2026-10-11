import { useEffect } from "react";
import { type Settings as SettingsType } from "../../api/client";
import { PlatformCookieAuth } from "./PlatformCookieAuth";

interface Props {
    settings: SettingsType | null;
    onSaved: () => void;
    onDirtyChange?: (dirty: boolean) => void;
}

export function AuthTab({ onSaved, onDirtyChange }: Props) {
    // File registration saves immediately, so this tab has no unsaved text fields.
    useEffect(() => onDirtyChange?.(false), [onDirtyChange]);
    return (
        <div className="space-y-6">
            {(["chzzk", "youtube", "soop", "cime"] as const).map(platform => (
                <PlatformCookieAuth key={platform} platform={platform} onSaved={onSaved} />
            ))}
        </div>
    );
}
