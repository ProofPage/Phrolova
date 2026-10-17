import { translate } from "../../i18n";
import { RecordingOutputSettingsCard } from './RecordingOutputSettingsCard';
import { useEffect, useRef, useState } from "react";
import { Film, Radio, Save } from "lucide-react";
import { api, type RecordingOutputSettings, type Settings as SettingsType } from "../../api/client";
import { getErrorMessage } from "../../utils/error";
import { useToast } from "../ui/Toast";
import { Button, Card, CardHeader, Field, Input, Select, SettingRow, Switch } from "../ui/primitives";
import { DirInput } from "../ui/DirInput";
import { useLanguage } from "../../contexts/LanguageContext";
interface Props {
    settings: SettingsType | null;
    /** 저장 후 상위의 설정 상태를 갱신한다. */
    onSaved: () => void;
    /** 변경사항 유무를 상위 탭 전환 경고에 알린다. */
    onDirtyChange?: (dirty: boolean) => void;
}
export function DownloadTab({ settings, onSaved, onDirtyChange }: Props) {
    const { t } = useLanguage();
    const [liveDownloadDir, setLiveDownloadDir] = useState("");
    const [vodDownloadDir, setVodDownloadDir] = useState("");
    const [monitorInterval, setMonitorInterval] = useState(30);
    const [output, setOutput] = useState<RecordingOutputSettings | null>(null);
    const [savedOutput, setSavedOutput] = useState<RecordingOutputSettings | null>(null);
    const [outputLoading, setOutputLoading] = useState(true);
    const [outputLoadError, setOutputLoadError] = useState(false);
    const [saving, setSaving] = useState(false);
    const [saveErrors, setSaveErrors] = useState<Partial<Record<'video' | 'live' | 'processing', unknown>>>({});
    const pending = useRef(false);
    const toast = useToast();
    const [keepParts, setKeepParts] = useState(false);
    const [maxRetries, setMaxRetries] = useState(3);
    const [recordingQuality, setRecordingQuality] = useState("best");
    const [streamMode, setStreamMode] = useState<"standard" | "request-timemachine" | "force-timemachine">("force-timemachine");
    const [timeMachineOffset, setTimeMachineOffset] = useState(0);
    const [saveLivePreview, setSaveLivePreview] = useState(false);
    const [liveFilenameTemplate, setLiveFilenameTemplate] = useState("[{name}] {title} {live_date_year}-{live_date_month}-{live_date_day} {live_date_hour}-{live_date_minute}-{live_date_second}");
    const [vodMaxConcurrent, setVodMaxConcurrent] = useState(5);
    const [vodDefaultQuality, setVodDefaultQuality] = useState("best");
    const [vodMaxSpeed, setVodMaxSpeed] = useState(0);
    const [vodFilenameTemplate, setVodFilenameTemplate] = useState("[{name}] {title} {date_year}-{date_month}-{date_day} {date_hour}-{date_minute}-{date_second}");
    const [vodFormat, setVodFormat] = useState("mp4");
    const [liveCdn, setLiveCdn] = useState<"default" | "akamai">("akamai");
    const [cdn, setCdn] = useState<"default" | "akamai">("akamai");
    const [soopProxy, setSoopProxy] = useState("");
    const initialized = useRef(false);
    useEffect(() => {
        let active = true;
        void api.getRecordingOutputSettings().then(data => {
            if (active) { setOutput(data); setSavedOutput(data); }
        }).catch(() => { if (active) setOutputLoadError(true); })
          .finally(() => { if (active) setOutputLoading(false); });
        return () => { active = false; };
    }, []);
    useEffect(() => {
        // 일부 영역만 저장에 성공해도 실패한 영역의 입력값은 보존한다.
        // 탭을 나갔다 돌아오면 컴포넌트가 다시 마운트되어 최신 값을 읽는다.
        if (!settings || initialized.current) return;
        initialized.current = true;
        setLiveDownloadDir(settings.live_download_dir || settings.download_dir);
        setVodDownloadDir(settings.vod_download_dir || settings.download_dir);
        setMonitorInterval(settings.monitor_interval);
        setKeepParts(settings.keep_download_parts);
        setMaxRetries(settings.max_record_retries);
        setRecordingQuality(settings.recording_quality || "best");
        setStreamMode(settings.chzzk_stream_mode ?? (settings.chzzk_time_machine_enabled === false ? "standard" : "force-timemachine"));
        setTimeMachineOffset(settings.chzzk_time_machine_offset ?? settings.chzzk_time_machine_shift ?? 0);
        setSaveLivePreview(settings.save_live_preview ?? false);
        setLiveFilenameTemplate(settings.live_filename_template || "[{name}] {title} {live_date_year}-{live_date_month}-{live_date_day} {live_date_hour}-{live_date_minute}-{live_date_second}");
        setVodMaxConcurrent(settings.vod_max_concurrent ?? 5);
        setVodDefaultQuality(settings.vod_default_quality);
        setVodMaxSpeed(settings.vod_max_speed);
        setVodFormat(settings.vod_format || "mp4");
        setLiveCdn(settings.chzzk_live_cdn ?? "akamai");
        setCdn(settings.chzzk_vod_cdn ?? "akamai");
        setVodFilenameTemplate(settings.vod_filename_template || "[{name}] {title} {date_year}-{date_month}-{date_day} {date_hour}-{date_minute}-{date_second}");
        setSoopProxy(settings.soop_proxy || "");
    }, [settings]);
    const liveDirty = !!settings && (
        liveDownloadDir !== (settings.live_download_dir || settings.download_dir) ||
        monitorInterval !== settings.monitor_interval ||
        maxRetries !== settings.max_record_retries ||
        recordingQuality !== (settings.recording_quality || "best") ||
        liveCdn !== (settings.chzzk_live_cdn ?? "akamai") ||
        streamMode !== (settings.chzzk_stream_mode ?? (settings.chzzk_time_machine_enabled === false ? "standard" : "force-timemachine")) ||
        timeMachineOffset !== (settings.chzzk_time_machine_offset ?? settings.chzzk_time_machine_shift ?? 0) ||
        saveLivePreview !== (settings.save_live_preview ?? false) ||
        liveFilenameTemplate !== (settings.live_filename_template || "[{name}] {title} {live_date_year}-{live_date_month}-{live_date_day} {live_date_hour}-{live_date_minute}-{live_date_second}") ||
        soopProxy !== (settings.soop_proxy || "")
    );
    const vodDirty = !!settings && (
        vodDownloadDir !== (settings.vod_download_dir || settings.download_dir) ||
        keepParts !== settings.keep_download_parts ||
        vodMaxConcurrent !== (settings.vod_max_concurrent ?? 5) ||
        vodDefaultQuality !== settings.vod_default_quality ||
        vodMaxSpeed !== settings.vod_max_speed ||
        vodFormat !== (settings.vod_format || "mp4") ||
        cdn !== (settings.chzzk_vod_cdn ?? "akamai") ||
        vodFilenameTemplate !== (settings.vod_filename_template || "[{name}] {title} {date_year}-{date_month}-{date_day} {date_hour}-{date_minute}-{date_second}")
    );
    const outputDirty = !!output && JSON.stringify(output) !== JSON.stringify(savedOutput);
    const dirty = outputDirty || liveDirty || vodDirty;
    const validVod = !!vodDownloadDir.trim() && !!vodFilenameTemplate.trim() && vodFilenameTemplate.length <= 240 &&
        Number.isInteger(vodMaxConcurrent) && vodMaxConcurrent >= 1 && vodMaxConcurrent <= 10 &&
        Number.isFinite(vodMaxSpeed) && vodMaxSpeed >= 0 && vodMaxSpeed <= 1000;
    const validLive = !!liveDownloadDir.trim() && !!liveFilenameTemplate.trim() && liveFilenameTemplate.length <= 240 &&
        Number.isInteger(monitorInterval) && monitorInterval >= 5 && monitorInterval <= 300 &&
        Number.isInteger(maxRetries) && maxRetries >= 0 && maxRetries <= 100 &&
        Number.isInteger(timeMachineOffset) && timeMachineOffset >= 0 && timeMachineOffset <= 86400;
    const valid = (!vodDirty || validVod) && (!liveDirty || validLive);
    useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);
    const handleSave = async () => {
        if (pending.current || !dirty || !valid || outputLoading) return;
        pending.current = true;
        setSaving(true);
        setSaveErrors({});
        const errors: typeof saveErrors = {};
        let savedAny = false;
        const requests: { section: 'video' | 'live' | 'processing'; request: () => Promise<unknown> }[] = [];
        if (vodDirty) requests.push({ section: 'video', request: async () => {
            await api.updateVodSettings({
                vod_download_dir: vodDownloadDir.trim(),
                vod_max_concurrent: vodMaxConcurrent,
                vod_default_quality: vodDefaultQuality,
                vod_max_speed: vodMaxSpeed,
                vod_format: vodFormat,
                chzzk_vod_cdn: cdn,
                vod_filename_template: vodFilenameTemplate,
                keep_download_parts: keepParts,
            });
            setVodDownloadDir(vodDownloadDir.trim());
        }});
        if (outputDirty && output) requests.push({ section: 'processing', request: async () => {
            const result = await api.updateRecordingOutputSettings(output);
            setSavedOutput(result); setOutput(result);
        }});
        if (liveDirty) requests.push({ section: 'live', request: async () => {
            await api.updateDownloadSettings(
                maxRetries, streamMode, timeMachineOffset,
                saveLivePreview, liveFilenameTemplate, recordingQuality, liveCdn,
                { live_download_dir: liveDownloadDir.trim(), monitor_interval: monitorInterval },
                soopProxy.trim(),
            );
            setLiveDownloadDir(liveDownloadDir.trim());
        }});
        try {
            // 기존 API가 같은 설정 파일을 갱신하므로 요청을 순서대로 보낸다.
            for (const { section, request } of requests) {
                try { await request(); savedAny = true; }
                catch (error) { errors[section] = error; }
            }
            setSaveErrors(errors);
            if (savedAny) await onSaved();
            if (Object.keys(errors).length) toast.error('settings.couldNotSaveAllChanges');
            else toast.success('settings.allChangesSaved');
        } finally { pending.current = false; setSaving(false); }
    };
    return (
        <div className="download-settings space-y-4">
            <fieldset disabled={saving} className="min-w-0 space-y-4">
            <Card className="settings-section space-y-3" data-settings-section="video" aria-busy={saving}>
                <CardHeader icon={Film} title={translate("settings.videoDownloadSettings")} />
                <Field label={translate("settings.videoDownloadLocation")}>
                    <DirInput value={vodDownloadDir} onChange={setVodDownloadDir} placeholder={translate("settings.eGERecordingsVideo")} />
                </Field>
                <Field label={translate("settings.concurrentDownloads")} hint={translate("settings.appliesWhenSavedReducingThisLimitDoesNotStopActiveDownloads110")}>
                    <Input type="number" value={vodMaxConcurrent} onChange={(event) => setVodMaxConcurrent(Number(event.target.value))} min={1} max={10} />
                </Field>
                <Field label={t("settings.defaultResolution")}>
                    <Select
                        value={vodDefaultQuality}
                        onChange={(event) => setVodDefaultQuality(event.target.value)}
                        options={[
                            { value: "best", label: translate("live.highestQuality") },
                            { value: "1080p", label: "1080p" },
                            { value: "720p", label: "720p" },
                            { value: "480p", label: "480p" },
                        ]}
                    />
                </Field>
                <Field label={translate("settings.chzzkDownloadCDN")} hint={translate("settings.akamaiCDNIsTheDefaultAppliesToCHZZKVideosStartedOrDownloadedAgainAfterSaving")}>
                    <Select
                        aria-label={translate("settings.chzzkDownloadCDN")}
                        value={cdn}
                        onChange={(event) => setCdn(event.target.value as typeof cdn)}
                        options={[
                            { value: "default", label: "Naver CDN" },
                            { value: "akamai", label: "Akamai CDN" },
                        ]}
                    />
                </Field>
                <Field label={t("settings.downloadSpeedLimitMBS")} hint={t("settings.setTo0ForUnlimitedSpeed")}>
                    <Input type="number" value={vodMaxSpeed} onChange={(event) => setVodMaxSpeed(Number(event.target.value))} min={0} max={1000} />
                </Field>
                <Field label={t("settings.videoFileFormat")} hint={t("settings.mp4WorksWithMostDevicesAndMediaPlayers")}>
                    <Select
                        value={vodFormat}
                        onChange={(event) => setVodFormat(event.target.value)}
                        options={[
                            { value: "mp4", label: translate("settings.mp4MPEG4Recommended") },
                            { value: "mkv", label: "MKV — Matroska" },
                            { value: "ts", label: "TS — MPEG Transport Stream" },
                        ]}
                    />
                </Field>
                <SettingRow
                    label={translate("settings.keepIncompleteVideoFilesPart")}
                    hint={keepParts ? translate("settings.keepPartialFilesWhenADownloadIsCanceledOrFails") : translate("settings.deletePartialFilesWhenADownloadIsCanceledOrFails")}
                    control={<Switch checked={keepParts} onChange={setKeepParts} label={translate("settings.keepIncompleteVideoFiles")} />}
                />
                <Field label={translate("settings.videoFilenameFormat")} htmlFor="vod-filename-template">
                    <Input id="vod-filename-template" value={vodFilenameTemplate} maxLength={240} onChange={(event) => setVodFilenameTemplate(event.target.value)} />
                    <details className="settings-field-help">
                        <summary>{t('settings.filenameVariables')}</summary>
                        <p>{t("settings.availableFieldsNameTitleDateYearDateMonthDateDayDateHourDateMinuteDateSecondIdExtractorUploadDateDownloadDateAndQualityDateAndTimeUseTheDownloadStartTimeTheExtensionIsAddedAutomatically")}</p>
                    </details>
                </Field>
                {saveErrors.video != null && <p role="alert" className="text-xs text-danger break-words">{getErrorMessage(saveErrors.video, 'settings.couldNotSaveVideoDownloadSettings')}</p>}
            </Card>
            <RecordingOutputSettingsCard value={output} onChange={setOutput} busy={saving || outputLoading} error={saveErrors.processing != null ? getErrorMessage(saveErrors.processing, 'settings.couldNotSaveFileProcessingSettings') : outputLoadError ? t('settings.couldNotLoadFileProcessingSettings') : ''}/>
            <Card className="settings-section space-y-3" data-settings-section="live" aria-busy={saving}>
                <CardHeader icon={Radio} title={translate("settings.liveRecordingSettings")} />
                <Field label={translate("settings.liveRecordingLocation")}>
                    <DirInput value={liveDownloadDir} onChange={setLiveDownloadDir} placeholder={translate("settings.eGERecordingsLive")} />
                </Field>
                <Field label={translate("settings.liveStatusCheckIntervalSeconds")} hint={translate("settings.howOftenToCheckTheLiveStatusOfAddedChannels5300Seconds")}>
                    <Input type="number" min={5} max={300} value={monitorInterval} onChange={event => setMonitorInterval(Number(event.target.value))} />
                </Field>
                <Field label={translate("settings.chzzkLiveCDN")} hint={translate("settings.akamaiCDNIsTheDefaultAppliesToTheNextRecordingNaverCDNIsUsedWhenUnavailable")}>
                    <Select aria-label={translate("settings.chzzkLiveCDN")} value={liveCdn} onChange={event=>setLiveCdn(event.target.value as typeof liveCdn)} options={[{value:'default',label:'Naver CDN'},{value:'akamai',label:'Akamai CDN'}]}/>
                </Field>
                <Field label={translate("settings.liveRecordingResolution")} hint={translate("settings.chooseARecordingResolutionHigherResolutionsUseMoreStorage")}>
                    <Select
                        value={recordingQuality}
                        onChange={(event) => setRecordingQuality(event.target.value)}
                        options={[
                            { value: "best", label: translate("live.highestQuality") },
                            { value: "1080p", label: "1080p" },
                            { value: "720p", label: "720p" },
                            { value: "480p", label: "480p" },
                        ]}
                    />
                </Field>
                <Field label={t("settings.recordingRetryAttempts")} hint={t("settings.howManyTimesToRetryIfTheConnectionDropsOrRecordingFails")}>
                    <Input type="number" min={0} max={100} value={maxRetries} onChange={(event) => setMaxRetries(parseInt(event.target.value) || 0)} />
                </Field>
                <Field
                    label={translate("settings.recordingMode")}
                    hint={streamMode === "force-timemachine" ? translate("settings.alwaysUseTimeMachineIfUnavailableTheRecordingRequestFails") : streamMode === "request-timemachine" ? translate("settings.tryTheTimeMachineAPIFirstThenFallBackToTheStandardStreamIfUnavailable") : translate("settings.useTheLiveStreamProvidedByTheStandardCHZZKAPI")}
                >
                    <Select
                        value={streamMode}
                        onChange={(event) => setStreamMode(event.target.value as typeof streamMode)}
                        options={[
                            { value: "standard", label: translate("settings.useStandardStream") },
                            { value: "request-timemachine", label: translate("settings.useTimeMachineWhenAvailable") },
                            { value: "force-timemachine", label: translate("settings.alwaysUseTimeMachine") },
                        ]}
                    />
                </Field>
                {streamMode !== "standard" && (
                    <Field label={translate("settings.streamStartOffsetSeconds")} hint={translate("settings.skipThisMuchTimeFromTheStartOfATimeMachineStreamUse0ToStartAtTheEarliestAvailablePoint")}>
                        <Input type="number" min={0} max={86400} value={timeMachineOffset} onChange={(event) => setTimeMachineOffset(Math.max(0, Math.min(86400, Number(event.target.value) || 0)))} />
                    </Field>
                )}
                <SettingRow
                    label={translate("settings.saveLivePreviewImages")}
                    hint={saveLivePreview ? translate("settings.saveTheLiveThumbnailNextToTheRecording") : translate("settings.doNotSavePreviewImagesAsSeparateFiles")}
                    control={<Switch checked={saveLivePreview} onChange={setSaveLivePreview} label={translate("settings.saveLivePreviewImages")} />}
                />
                <Field label={translate("settings.liveRecordingFilenameFormat")}>
                    <Input value={liveFilenameTemplate} onChange={(event) => setLiveFilenameTemplate(event.target.value)} maxLength={240} />
                    <details className="settings-field-help">
                        <summary>{t('settings.filenameVariables')}</summary>
                        <p>{t("settings.availableFieldsNameChannelNameTitleLiveTitleChannelUidCategoryDateYearLiveDateYearDownloadDateYearLiveDateMonthLiveDateDayLiveDateHourLiveDateMinuteLiveDateSecondQualityAndExtensionTheExtensionIsAddedAutomatically")}</p>
                    </details>
                </Field>
                <Field label={t("settings.soopProxyAddress")} hint={t("settings.soopProxyHint")}>
                    <Input value={soopProxy} onChange={(event) => setSoopProxy(event.target.value)} placeholder="http://127.0.0.1:1080 또는 socks5://127.0.0.1:1080" maxLength={1024} />
                </Field>
                {saveErrors.live != null && <p role="alert" className="text-xs text-danger break-words">{getErrorMessage(saveErrors.live, 'settings.couldNotSaveLiveSettings')}</p>}
            </Card>
            </fieldset>
            <div className="settings-save download-settings-save">
                {(saving || dirty) && <p className="text-xs text-ink-faint" role="status">{saving ? t('settings.saving') : !valid ? t('settings.checkInvalidFieldsBeforeSaving') : t('settings.unsavedChangesInSettings')}</p>}
                <Button variant="primary" icon={Save} loading={saving} disabled={!dirty || !valid || outputLoading} onClick={() => void handleSave()}>{t('settings.saveChanges')}</Button>
            </div>
        </div>
    );
}
