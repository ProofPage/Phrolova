import { translate } from "../../i18n";
import { RECORDING_OUTPUT_FORMATS } from '../../utils/recordingFormats';
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { RefreshCw, SlidersHorizontal, X } from "lucide-react";
import { api, PLATFORM_LABELS, type Channel, type ChannelDownloadOptions, type DownloadCondition, type LiveQuality, type Platform } from "../../api/client";
import { getErrorMessage, localizedStatus } from "../../utils/error";
import { useToast } from "../ui/Toast";
import { Button, Field, Input, Select, SettingRow, Switch } from "../ui/primitives";
import { DOWNLOAD_CONDITIONS } from "./LiveDownloadCondition";
import { useLanguage } from "../../contexts/LanguageContext";
import { RecordingSourceFormatField } from '../settings/RecordingSourceFormatField';

interface Props {
    platform: Platform;
    name: string;
    channel?: Channel;
    channelId?: string;
    onClose: () => void;
    onSave: (options: ChannelDownloadOptions) => Promise<void>;
}

export function ChannelDownloadModal({ platform, name, channel, channelId, onClose, onSave }: Props) {
    const { t } = useLanguage();
    const dialog = useRef<HTMLDialogElement>(null);
    const editedTags = useRef(false);
    const [autoRecord, setAutoRecord] = useState(channel?.auto_record ?? true);
    const [condition, setCondition] = useState<DownloadCondition | "inherit">(channel?.download_condition ?? "inherit");
    const [tags, setTags] = useState(channel?.watchalong_tags ?? "같이보기");
    const [initialTags, setInitialTags] = useState(channel?.watchalong_tags ?? "같이보기");
    const [defaultLabel, setDefaultLabel] = useState("live.checking");
    const [saving, setSaving] = useState(false);
    const [outputFormat,setOutputFormat] = useState(channel?.output_format || 'inherit');
    const [saveError, setSaveError] = useState<string | null>(null);
    const dynamicQuality = platform === 'soop' || platform === 'cime' || platform === 'kick' || platform === 'twitch' || platform === 'tiktok' || platform === 'bilibili' || platform === 'pandalive' || platform === 'popkontv';
    const [quality, setQuality] = useState(channel?.recording_quality || 'best');
    const [qualities, setQualities] = useState<LiveQuality[]>([]);
    const [qualityLoading, setQualityLoading] = useState(false);
    const [qualityMessage, setQualityMessage] = useState('');
    const [qualityRefresh, setQualityRefresh] = useState(0);
    const dirty = !channel || autoRecord !== channel.auto_record ||
        condition !== (channel.download_condition ?? "inherit") ||
        (condition === "watchalong" && tags !== initialTags) ||
        quality !== (channel?.recording_quality || 'best') || outputFormat !== (channel?.output_format || 'inherit');
    const toast = useToast();

    useEffect(() => {
        dialog.current?.showModal();
        let active = true;
        void api.getSettings().then((settings) => {
            if (!active) return;
            const label = DOWNLOAD_CONDITIONS.find((item) => item.value === settings.live_download_condition)?.label;
            setDefaultLabel(label || "live.recordAllLiveStreams");
            if (!channel?.watchalong_tags && !editedTags.current) {
                setTags(settings.watchalong_tags || "같이보기");
                setInitialTags(settings.watchalong_tags || "같이보기");
            }
        }).catch(() => { if (active) setDefaultLabel("live.unknown"); });
        return () => { active = false; };
    }, [channel]);

    useEffect(() => {
        if (platform !== 'soop' && platform !== 'cime' && platform !== 'kick' && platform !== 'twitch' && platform !== 'tiktok' && platform !== 'bilibili' && platform !== 'pandalive' && platform !== 'popkontv') return;
        const controller = new AbortController();
        setQualityLoading(true);
        setQualityMessage('');
        void api.getPlatformQualities(platform, channelId || channel?.channel_id || name, controller.signal).then(data => {
            if (controller.signal.aborted) return;
            setQualities(data.qualities.filter(item => !!item.value && item.value !== 'best'));
            setQualityMessage(data.qualities.length ? "live.qualityOptionsProvidedByThisLiveStreamChangesApplyToTheNextRecording" : data.message || "live.availableQualityOptionsCanBeCheckedWhileTheChannelIsLive");
        }).catch(error => {
            if (!controller.signal.aborted) setQualityMessage(getErrorMessage(error, "live.couldNotFetchQualityOptionsUseTheHighestQualityOrTryAgain"));
        }).finally(() => { if (!controller.signal.aborted) setQualityLoading(false); });
        return () => controller.abort();
    }, [platform, channelId, channel?.channel_id, name, qualityRefresh]);

    const save = async () => {
        if (saving) return;
        setSaving(true);
        setSaveError(null);
        try {
            await onSave({
                auto_record: autoRecord,
                download_condition: platform === "chzzk" && condition !== "inherit" ? condition : null,
                watchalong_tags: platform === "chzzk" && condition === "watchalong" ? tags : null,
                recording_quality: quality,
                output_format: outputFormat === 'inherit' ? null : outputFormat as 'mp4'|'mkv',
            });
            onClose();
        } catch (error) {
            const message = getErrorMessage(error, t("live.couldNotSaveChannelSettings"));
            setSaveError(message);
            toast.error(message);
        } finally {
            setSaving(false);
        }
    };

    return createPortal(
        <dialog ref={dialog} aria-labelledby="channel-download-title" onCancel={(event) => { event.preventDefault(); if (!saving) onClose(); }}
            className="ui-dialog m-auto w-[calc(100%_-_2rem)] max-w-lg max-h-[90dvh] overflow-y-auto rounded-[var(--radius-card)] border border-line bg-surface-2 text-ink p-0 shadow-2xl backdrop:bg-black/70">
            <form onSubmit={(event) => { event.preventDefault(); void save(); }} className="p-5 sm:p-6 space-y-5 max-sm:p-3 max-sm:space-y-3">
                <div className="flex items-start gap-3">
                    <SlidersHorizontal className="w-5 h-5 text-[var(--primary)] shrink-0 mt-1" />
                    <div className="flex-1 min-w-0">
                        <h2 id="channel-download-title" className="font-bold text-lg">{channel ? t("live.channelRecordingSettings") : t("live.addLiveChannel")}</h2>
                        <p className="text-xs text-ink-muted mt-1 truncate" title={name}>{t(PLATFORM_LABELS[platform])} · {name}</p>
                    </div>
                    <button type="button" onClick={onClose} disabled={saving} aria-label={translate("live.closeSettings")} className="channel-settings-close icon-button p-1 text-ink-faint hover:text-ink"><X className="w-5 h-5" /></button>
                </div>
                <SettingRow label={t("live.autoRecord")} hint={t("live.automaticallyRecordWhenAStreamStartsAndMatchesTheRecordingCondition")}
                    control={<Switch checked={autoRecord} disabled={saving} onChange={setAutoRecord} label={`${name} ${t("live.autoRecord")}`} />} />
                {dynamicQuality && <Field label={t("live.recordingQuality")} htmlFor="channel-recording-quality" hint={localizedStatus(qualityMessage, qualityLoading ? 'live.checkingStreamQualityOptions' : 'live.availableQualityOptionsCanBeCheckedWhileTheChannelIsLive')}>
                    <div className="flex items-center gap-2 min-w-0">
                        <Select id="channel-recording-quality" className="flex-1 min-w-0" value={quality} disabled={saving || qualityLoading} onChange={event => setQuality(event.target.value)}
                            options={[{ value: 'best', label: t("live.highestQuality") }, ...qualities.map(item => ({ value: item.value, label: item.label })),
                                ...(quality !== 'best' && !qualities.some(item => item.value === quality) ? [{ value: quality, label: `${t("live.currentSetting")} · ${quality} (${t("live.availabilityNotConfirmed")})` }] : [])]} />
                        <Button type="button" icon={RefreshCw} loading={qualityLoading} disabled={saving} aria-label={t("live.refreshQualityOptions")} title={t("live.refreshQualityOptions")} onClick={() => setQualityRefresh(value => value + 1)}>{t("live.refresh")}</Button>
                    </div>
                </Field>}
                {platform === 'kick' && <p className="text-xs text-ink-muted">{t('live.kickQualityAuthentication')}</p>}
                {!dynamicQuality && <Field label={translate("live.recordingQuality")} htmlFor="channel-recording-quality" hint={translate("live.changesApplyToTheNextRecording")}><Select id="channel-recording-quality" value={quality} disabled={saving} onChange={e=>setQuality(e.target.value)} options={['best','1080p','720p','480p'].map(value=>({value,label:value==='best'?translate("live.highestQuality"):value}))}/></Field>}
                <RecordingSourceFormatField label={translate("live.recordingSourceFormat")} />
                <Field label={translate("live.outputFormatAfterRecording")} htmlFor="channel-output-format" hint={translate("live.changesApplyToTheNextRecording")}>
                    <Select id="channel-output-format" value={outputFormat} disabled={saving} onChange={e=>setOutputFormat(e.target.value)} options={[{value:'inherit',label:translate("live.useGlobalSettings")},...RECORDING_OUTPUT_FORMATS]} />
                </Field>
                {platform === "chzzk" && <>
                    <Field label={t("live.recordingCondition")} htmlFor="channel-download-condition" hint={condition === "inherit" ? `${t("live.currentDefault")}: ${t(defaultLabel)}` : t("live.appliesToThisChannelOnly")}>
                        <Select id="channel-download-condition" value={condition} autoFocus disabled={saving} onChange={(event) => setCondition(event.target.value as typeof condition)}
                            options={[{ value: "inherit", label: t("live.useDefaultCondition") }, ...DOWNLOAD_CONDITIONS.map((item) => ({ ...item, label: t(item.label) }))]} />
                    </Field>
                    {channel && <div className="text-xs text-ink-muted flex flex-wrap gap-x-2 gap-y-1"><span className="font-medium">{t("live.currentStreamTags")}</span><span className="text-ink-faint">{channel.broadcast_tags == null ? t("live.awaitingCheck") : channel.broadcast_tags.length ? channel.broadcast_tags.join(" · ") : t("live.none")}</span></div>}
                    {channel?.is_watchalong === true && <p className="text-xs text-[var(--primary)]">{t("live.watchAlongStream")}{channel.watchalong_tag ? ` · ${channel.watchalong_tag}` : ""}</p>}
                    {condition === "watchalong" && <Field label={t("live.watchAlongTags")} htmlFor="channel-watchalong-tags" hint={t("live.useWatchAlongToMatchAllWatchAlongStreamsSeparateSpecificContentTagsWithCommas")}>
                        <Input id="channel-watchalong-tags" value={tags} maxLength={500} disabled={saving} onChange={(event) => { editedTags.current = true; setTags(event.target.value); }} placeholder={t("live.eGWatchAlong")} />
                    </Field>}
                    <p className="text-xs text-ink-faint leading-relaxed">{t("live.usesWatchAlongDetailsAndStreamTagsChangesApplyToTheNextAutomaticRecordingAndDoNotAffectOngoingOrManualRecordings")}</p>
                </>}
                {saveError && <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">{t(saveError)}</p>}
                <div className="dialog-actions flex flex-wrap justify-end gap-2 border-t border-line pt-4">
                    <Button type="button" disabled={saving} onClick={onClose}>{translate("common.cancel")}</Button>
                    <Button type="submit" variant="primary" loading={saving} disabled={!dirty || (platform === "chzzk" && condition === "watchalong" && !tags.trim())}>{channel ? translate("live.saveSettings") : translate("live.addChannel")}</Button>
                </div>
            </form>
        </dialog>, document.body,
    );
}
