import { translate } from "../../i18n";
import { RecordingOutputSettingsCard } from './RecordingOutputSettingsCard';
import { useEffect, useRef, useState } from "react";
import { Film, Radio, RefreshCcw, Save } from "lucide-react";
import { useSettingsSave } from "../../hooks/useSettingsSave";
import { api, type Settings as SettingsType } from "../../api/client";
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
    const [outputDirty,setOutputDirty] = useState(false);
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
    const initialized = useRef(false);
    // 세 영역이 각각 따로 저장되므로 훅도 따로 둔다 — 저장 중 표시가 서로 섞이지 않는다.
    const { saving: liveSaving, save: saveLive } = useSettingsSave(onSaved);
    const { saving: vodSaving, save: saveVod } = useSettingsSave(onSaved);
    useEffect(() => {
        // Save 후 부모가 설정을 새로 불러와도 다른 섹션의 미저장값은 보존한다.
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
        liveFilenameTemplate !== (settings.live_filename_template || "[{name}] {title} {live_date_year}-{live_date_month}-{live_date_day} {live_date_hour}-{live_date_minute}-{live_date_second}")
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
    const dirty = outputDirty || liveDirty || vodDirty;
    useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);
    const handleSaveVod = () => saveVod({
        request: () => api.updateVodSettings({
            vod_download_dir: vodDownloadDir.trim(),
            vod_max_concurrent: vodMaxConcurrent,
            vod_default_quality: vodDefaultQuality,
            vod_max_speed: vodMaxSpeed,
            vod_format: vodFormat,
            chzzk_vod_cdn: cdn,
            vod_filename_template: vodFilenameTemplate,
            keep_download_parts: keepParts,
        }),
        success: t("settings.videoDownloadSettingsSaved"),
        failure: t("settings.couldNotSaveVideoDownloadSettings"),
    });
    const handleSaveLive = () => saveLive({
        request: () => api.updateDownloadSettings(
            maxRetries, streamMode, timeMachineOffset,
            saveLivePreview, liveFilenameTemplate, recordingQuality, liveCdn,
            { live_download_dir: liveDownloadDir.trim(), monitor_interval: monitorInterval },
        ),
        success: t("settings.liveSettingsSaved"),
        failure: t("settings.couldNotSaveLiveSettings"),
    });
    return (
        <div className="download-settings space-y-4">
            <Card className="settings-section space-y-3" data-settings-section="video" aria-busy={vodSaving}>
                <CardHeader icon={Film} title={translate("settings.videoDownloadSettings")} />
                <Field label={translate("settings.videoDownloadLocation")} hint={translate("settings.downloadedVODsClipsAndVideosAreSavedHere")}>
                    <DirInput value={vodDownloadDir} onChange={setVodDownloadDir} placeholder={translate("settings.eGERecordingsVideo")} />
                </Field>
                <Field label={translate("settings.concurrentDownloads")} hint={translate("settings.appliesWhenSavedReducingThisLimitDoesNotStopActiveDownloads110")}>
                    <Input type="number" value={vodMaxConcurrent} onChange={(event) => setVodMaxConcurrent(Number(event.target.value))} min={1} max={10} />
                </Field>
                <Field label={t("settings.defaultResolution")} hint={t("settings.defaultResolutionForVideoDownloads")}>
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
                <Field label={translate("settings.videoFilenameFormat")} htmlFor="vod-filename-template" hint={translate("settings.availableFieldsNameTitleDateYearDateMonthDateDayDateHourDateMinuteDateSecondIdExtractorUploadDateDownloadDateAndQualityDateAndTimeUseTheDownloadStartTimeTheExtensionIsAddedAutomatically")}>
                    <Input id="vod-filename-template" value={vodFilenameTemplate} maxLength={240} onChange={(event) => setVodFilenameTemplate(event.target.value)} />
                </Field>
                <div className="settings-save-row flex justify-start border-t border-line pt-3">
                <Button variant="primary" icon={Save} loading={vodSaving} disabled={!vodDirty || !vodDownloadDir.trim() || !vodFilenameTemplate.trim() || !Number.isInteger(vodMaxConcurrent) || vodMaxConcurrent < 1 || vodMaxConcurrent > 10} onClick={handleSaveVod}>
                    {vodSaving ? translate("settings.saving") : translate("settings.saveVideoDownloadSettings")}
                </Button>
                </div>
            </Card>
            <RecordingOutputSettingsCard onSaved={onSaved} onDirtyChange={setOutputDirty}/>
            <Card className="settings-section space-y-3" data-settings-section="live" aria-busy={liveSaving}>
                <CardHeader icon={Radio} title={translate("settings.liveRecordingSettings")} />
                <Field label={translate("settings.liveRecordingLocation")} hint={translate("settings.liveRecordingsAreSavedHere")}>
                    <DirInput value={liveDownloadDir} onChange={setLiveDownloadDir} placeholder={translate("settings.eGERecordingsLive")} />
                </Field>
                <Field label={translate("settings.liveStatusCheckIntervalSeconds")} hint={translate("settings.howOftenToCheckTheLiveStatusOfAddedChannels5300Seconds")}>
                    <Input type="number" min={5} max={300} value={monitorInterval} onChange={event => setMonitorInterval(Number(event.target.value))} />
                </Field>
                <Field label={translate("settings.chzzkLiveCDN")} hint={translate("settings.akamaiCDNIsTheDefaultAppliesToTheNextRecordingNaverCDNIsUsedWhenUnavailable")}>
                    <Select aria-label={translate("settings.chzzkLiveCDN")} value={liveCdn} disabled={liveSaving} onChange={event=>setLiveCdn(event.target.value as typeof liveCdn)} options={[{value:'default',label:'Naver CDN'},{value:'akamai',label:'Akamai CDN'}]}/>
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
                <Field label={translate("settings.liveRecordingFilenameFormat")} hint={translate("settings.availableFieldsNameChannelNameTitleLiveTitleChannelUidCategoryDateYearLiveDateYearDownloadDateYearLiveDateMonthLiveDateDayLiveDateHourLiveDateMinuteLiveDateSecondQualityAndExtensionTheExtensionIsAddedAutomatically")}>
                    <Input value={liveFilenameTemplate} onChange={(event) => setLiveFilenameTemplate(event.target.value)} maxLength={240} />
                </Field>
                <div className="settings-save-row flex justify-start border-t border-line pt-3">
                <Button variant="primary" icon={liveSaving ? RefreshCcw : Save} loading={liveSaving} disabled={!liveDirty || !liveDownloadDir.trim() || !Number.isInteger(monitorInterval) || monitorInterval < 5 || monitorInterval > 300 || !liveFilenameTemplate.trim()} onClick={handleSaveLive}>
                    {liveSaving ? translate("settings.saving") : translate("settings.saveLiveSettings")}
                </Button>
                </div>
            </Card>
        </div>
    );
}
