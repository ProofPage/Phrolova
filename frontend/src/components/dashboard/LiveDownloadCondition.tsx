import { useEffect, useState } from "react";
import { Save } from "lucide-react";
import { api, type DownloadCondition } from "../../api/client";
import { getErrorMessage } from "../../utils/error";
import { useToast } from "../ui/Toast";
import { Button, Field, Input, Select } from "../ui/primitives";
import { useLanguage } from "../../contexts/LanguageContext";

export const DOWNLOAD_CONDITIONS: { value: DownloadCondition; label: string }[] = [
    { value: "all", label: "live.recordAllLiveStreams" },
    { value: "watchalong", label: "live.recordWatchAlongStreamsOnly" },
    { value: "exclude_watchalong", label: "live.recordStreamsExceptWatchAlongs" },
];

export function LiveDownloadCondition() {
    const { t } = useLanguage();
    const [condition, setCondition] = useState<DownloadCondition>("all");
    const [tags, setTags] = useState("같이보기");
    const [loaded, setLoaded] = useState(false);
    const [loadError, setLoadError] = useState(false);
    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState<{ condition: DownloadCondition; tags: string } | null>(null);
    const dirty = saved !== null && (condition !== saved.condition || (condition === "watchalong" && tags !== saved.tags));
    const toast = useToast();

    const load = async () => {
        setLoadError(false);
        try {
            const settings = await api.getSettings();
            setCondition(settings.live_download_condition);
            setTags(settings.watchalong_tags || "같이보기");
            setSaved({ condition: settings.live_download_condition, tags: settings.watchalong_tags || "같이보기" });
            setLoaded(true);
        } catch {
            setLoadError(true);
        }
    };
    useEffect(() => { void load(); }, []);

    const save = async () => {
        setSaving(true);
        try {
            const result = await api.updateLiveCondition(condition, tags);
            setTags(result.watchalong_tags);
            setSaved({ condition, tags: result.watchalong_tags });
            toast.success(t("live.defaultRecordingConditionSaved"));
        } catch (error) {
            toast.error(getErrorMessage(error, t("live.couldNotSaveTheRecordingCondition")));
        } finally {
            setSaving(false);
        }
    };

    if (loadError) return <div className="flex items-center justify-between gap-3 border-t border-line pt-3 text-xs text-ink-muted">{t("live.couldNotLoadTheRecordingCondition")}<Button onClick={() => void load()}>{t("live.tryAgain")}</Button></div>;
    return (
        <div className="border-t border-line pt-4 space-y-3">
            <div className={`grid grid-cols-1 ${condition === "watchalong" ? "md:grid-cols-2" : ""} gap-3`}>
                <Field label={t("live.defaultRecordingCondition")} htmlFor="dashboard-download-condition">
                    <Select id="dashboard-download-condition" value={condition} disabled={!loaded || saving} onChange={(event) => setCondition(event.target.value as DownloadCondition)} options={DOWNLOAD_CONDITIONS.map((item) => ({ ...item, label: t(item.label) }))} />
                </Field>
                {condition === "watchalong" && <Field label={t("live.watchAlongTags")} htmlFor="dashboard-watchalong-tags" hint={t("live.useWatchAlongToMatchAllWatchAlongStreamsSeparateSpecificContentTagsWithCommas")}>
                    <Input id="dashboard-watchalong-tags" value={tags} maxLength={500} disabled={!loaded || saving} onChange={(event) => setTags(event.target.value)} placeholder={t("live.eGWatchAlong")} />
                </Field>}
            </div>
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="text-xs text-ink-faint leading-relaxed">
                    <p>{t("live.usesWatchAlongDetailsAndStreamTagsChannelSettingsTakePrecedenceOverTheDefault")}</p>
                    {dirty && <p className="text-[var(--primary)] mt-1" role="status">{t("live.youHaveUnsavedChanges")}</p>}
                </div>
                <Button icon={Save} loading={saving} disabled={!loaded || !dirty || (condition === "watchalong" && !tags.trim())} onClick={() => void save()} className="shrink-0">{t("live.saveDefaultCondition")}</Button>
            </div>
        </div>
    );
}
