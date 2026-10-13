import { translate } from "../../i18n";
import { useEffect, useState } from "react";
import { Gift, RefreshCcw, Terminal } from "lucide-react";
import { api, type UpdateInfo } from "../../api/client";
import { getErrorMessage } from "../../utils/error";
import { UpdateModal } from "../ui/UpdateModal";
import { useToast } from "../ui/Toast";
import { Button, Card, CardHeader } from "../ui/primitives";
import { useLanguage } from "../../contexts/LanguageContext";

interface Props {
    onUpdateAvailabilityChange?: (available: boolean) => void;
}

export function ProgramUpdateCard({ onUpdateAvailabilityChange }: Props) {
    const toast = useToast();
    const { t } = useLanguage();
    const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
    const [loadError, setLoadError] = useState(false);
    const [loading, setLoading] = useState(true);
    const [checkingUpdate, setCheckingUpdate] = useState(false);
    const [showUpdateModal, setShowUpdateModal] = useState(false);

    useEffect(() => {
        api.getUpdateStatus()
            .then((info) => {
                setUpdateInfo(info);
                onUpdateAvailabilityChange?.(info.has_update);
            })
            .catch(() => setLoadError(true))
            .finally(() => setLoading(false));
    }, [onUpdateAvailabilityChange]);

    const handleCheckUpdate = async () => {
        setCheckingUpdate(true);
        setLoadError(false);
        try {
            const info = await api.checkUpdateNow();
            setUpdateInfo(info);
            onUpdateAvailabilityChange?.(info.has_update);
            if (info.checked_at || info.has_update) toast.success(info.has_update ? t("settings.aNewVersionIsAvailable") : t("settings.youAreUsingTheLatestVersion"));
        } catch (error) {
            setLoadError(true);
            toast.error(getErrorMessage(error, t("settings.couldNotCheckForUpdates")));
        } finally {
            setCheckingUpdate(false);
        }
    };

    return (
        <>
            <Card className="space-y-5">
                <CardHeader icon={Terminal} title={translate("settings.appUpdates")} />
                <div className="bg-surface-3 p-4 rounded-[var(--radius-control)] border border-line flex flex-col items-start sm:flex-row sm:items-center justify-between gap-4 [overflow-wrap:anywhere]">
                    <div className="min-w-0">
                        <h4 className="text-sm font-medium text-ink mb-1">{t("settings.currentVersion")}</h4>
                        <p className="text-xs text-ink-faint font-mono">v{updateInfo?.current_version || "..."}</p>
                    </div>
                    <div className="min-w-0 sm:text-right">
                        <h4 className="text-sm font-medium text-ink mb-1">{t("settings.latestRelease")}</h4>
                        <p className="text-xs text-ink-faint font-mono">{updateInfo?.latest_version && (updateInfo.checked_at || updateInfo.has_update) ? `v${updateInfo.latest_version}` : t(loading ? translate("live.checking") : loadError ? translate("settings.lookupFailed") : translate("settings.notCheckedYet"))}</p>
                    </div>
                </div>

                {loadError && <p role="status" className="text-xs text-warn">{t("settings.couldNotLoadUpdateInformationCheckAgain")}</p>}
                <div className="flex flex-col sm:flex-row gap-3">
                    <Button icon={RefreshCcw} loading={checkingUpdate} onClick={handleCheckUpdate} className="flex-1">
                        {checkingUpdate ? t("live.checking") : t("settings.checkForUpdates")}
                    </Button>
                    {updateInfo?.has_update && (
                        <Button variant="primary" icon={Gift} onClick={() => setShowUpdateModal(true)} className="flex-1">
                            {t("settings.updateToVVersion", {version: updateInfo.latest_version})}
                        </Button>
                    )}
                </div>

                {updateInfo?.has_update && updateInfo.release_notes && (
                    <div className="mt-6">
                        <h4 className="text-sm font-medium text-ok mb-2 flex items-center gap-2"><Gift className="w-4 h-4" /> {t("settings.releaseNotes")}</h4>
                        <div className="bg-surface-3 border border-line p-4 rounded-[var(--radius-control)] overflow-y-auto max-h-60 whitespace-pre-wrap [overflow-wrap:anywhere] text-sm text-ink-muted font-mono leading-relaxed">
                            {updateInfo.release_notes}
                        </div>
                    </div>
                )}
            </Card>

            {showUpdateModal && updateInfo && <UpdateModal info={updateInfo} onClose={() => setShowUpdateModal(false)} />}
        </>
    );
}
