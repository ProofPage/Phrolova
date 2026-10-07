import { useEffect, useRef, useState } from "react";
import { Film, MessageSquare, Radio, RefreshCcw, Save } from "lucide-react";
import { useSettingsSave } from "../../hooks/useSettingsSave";
import { api, type Settings as SettingsType } from "../../api/client";
import { Button, Card, CardHeader, Field, Input, Select, SettingRow, Switch } from "../ui/primitives";
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
    const [keepParts, setKeepParts] = useState(false);
    const [maxRetries, setMaxRetries] = useState(3);
    const [recordingQuality, setRecordingQuality] = useState("best");
    const [streamMode, setStreamMode] = useState<"standard" | "request-timemachine" | "force-timemachine">("request-timemachine");
    const [timeMachineOffset, setTimeMachineOffset] = useState(0);
    const [saveLivePreview, setSaveLivePreview] = useState(false);
    const [liveFilenameTemplate, setLiveFilenameTemplate] = useState("[{name}] {title} {live_date_year}-{live_date_month}-{live_date_day} {live_date_hour}-{live_date_minute}-{live_date_second}");
    const [vodMaxConcurrent, setVodMaxConcurrent] = useState(3);
    const [vodDefaultQuality, setVodDefaultQuality] = useState("best");
    const [vodMaxSpeed, setVodMaxSpeed] = useState(0);
    const [vodFilenameTemplate, setVodFilenameTemplate] = useState("[{name}] {title} {date_year}-{date_month}-{date_day} {date_hour}-{date_minute}-{date_second}");
    const [vodFormat, setVodFormat] = useState("mp4");
    const [chatArchiveEnabled, setChatArchiveEnabled] = useState(false);
    const initialized = useRef(false);
    // 세 영역이 각각 따로 저장되므로 훅도 따로 둔다 — 저장 중 표시가 서로 섞이지 않는다.
    const { saving: liveSaving, save: saveLive } = useSettingsSave(onSaved);
    const { saving: vodSaving, save: saveVod } = useSettingsSave(onSaved);
    const { saving: chatSaving, save: saveChat } = useSettingsSave(onSaved);

    useEffect(() => {
        // Save 후 부모가 설정을 새로 불러와도 다른 섹션의 미저장값은 보존한다.
        // 탭을 나갔다 돌아오면 컴포넌트가 다시 마운트되어 최신 값을 읽는다.
        if (!settings || initialized.current) return;
        initialized.current = true;
        setKeepParts(settings.keep_download_parts);
        setMaxRetries(settings.max_record_retries);
        setRecordingQuality(settings.recording_quality || "best");
        setStreamMode(settings.chzzk_stream_mode ?? (settings.chzzk_time_machine_enabled ? "force-timemachine" : "standard"));
        setTimeMachineOffset(settings.chzzk_time_machine_offset ?? settings.chzzk_time_machine_shift ?? 0);
        setSaveLivePreview(settings.save_live_preview ?? false);
        setLiveFilenameTemplate(settings.live_filename_template || "[{name}] {title} {live_date_year}-{live_date_month}-{live_date_day} {live_date_hour}-{live_date_minute}-{live_date_second}");
        setVodMaxConcurrent(settings.vod_max_concurrent);
        setVodDefaultQuality(settings.vod_default_quality);
        setVodMaxSpeed(settings.vod_max_speed);
        setVodFormat(settings.vod_format || "mp4");
        setVodFilenameTemplate(settings.vod_filename_template || "[{name}] {title} {date_year}-{date_month}-{date_day} {date_hour}-{date_minute}-{date_second}");
        setChatArchiveEnabled(settings.chat_archive_enabled);
    }, [settings]);

    const dirty = !!settings && (
        keepParts !== settings.keep_download_parts ||
        maxRetries !== settings.max_record_retries ||
        recordingQuality !== (settings.recording_quality || "best") ||
        streamMode !== (settings.chzzk_stream_mode ?? (settings.chzzk_time_machine_enabled ? "force-timemachine" : "standard")) ||
        timeMachineOffset !== (settings.chzzk_time_machine_offset ?? settings.chzzk_time_machine_shift ?? 0) ||
        saveLivePreview !== (settings.save_live_preview ?? false) ||
        liveFilenameTemplate !== (settings.live_filename_template || "[{name}] {title} {live_date_year}-{live_date_month}-{live_date_day} {live_date_hour}-{live_date_minute}-{live_date_second}") ||
        vodMaxConcurrent !== settings.vod_max_concurrent ||
        vodDefaultQuality !== settings.vod_default_quality ||
        vodMaxSpeed !== settings.vod_max_speed ||
        vodFormat !== (settings.vod_format || "mp4") ||
        vodFilenameTemplate !== (settings.vod_filename_template || "[{name}] {title} {date_year}-{date_month}-{date_day} {date_hour}-{date_minute}-{date_second}") ||
        chatArchiveEnabled !== settings.chat_archive_enabled
    );

    useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

    const handleSaveVod = () => saveVod({
        request: () => api.updateVodSettings({
            vod_max_concurrent: vodMaxConcurrent,
            vod_default_quality: vodDefaultQuality,
            vod_max_speed: vodMaxSpeed,
            vod_format: vodFormat,
            vod_filename_template: vodFilenameTemplate,
            keep_download_parts: keepParts,
        }),
        success: t("영상 다운로드 설정을 저장했습니다."),
        failure: t("영상 다운로드 설정 저장에 실패했습니다."),
    });

    const handleSaveLive = () => saveLive({
        request: () => api.updateDownloadSettings(
            maxRetries, streamMode, timeMachineOffset,
            saveLivePreview, liveFilenameTemplate, recordingQuality,
        ),
        success: t("라이브 설정이 저장되었습니다."),
        failure: t("라이브 설정 저장에 실패했습니다."),
    });

    const handleSaveChat = () => saveChat({
        request: () => api.updateChatSettings({ chat_archive_enabled: chatArchiveEnabled }),
        success: t("채팅 설정이 저장되었습니다."),
        failure: t("채팅 설정 저장에 실패했습니다."),
    });

    return (
        <div className="space-y-6">
            <Card className="space-y-5">
                <CardHeader icon={Film} title="영상 다운로드 설정" />
                <Field label="동시 다운로드 개수" hint="한 번에 다운로드할 수 있는 최대 영상 개수 (1~10개)">
                    <Input type="number" value={vodMaxConcurrent} onChange={(event) => setVodMaxConcurrent(Number(event.target.value))} min={1} max={10} />
                </Field>
                <Field label={t("기본 화질")} hint={t("영상 다운로드에 사용할 기본 해상도입니다.")}>
                    <Select
                        value={vodDefaultQuality}
                        onChange={(event) => setVodDefaultQuality(event.target.value)}
                        options={[
                            { value: "best", label: "최고 화질" },
                            { value: "1080p", label: "1080p" },
                            { value: "720p", label: "720p" },
                            { value: "480p", label: "480p" },
                        ]}
                    />
                </Field>
                <Field label={t("다운로드 속도 제한 (MB/s)")} hint={t("0으로 설정하면 속도 제한 없이 다운로드합니다.")}>
                    <Input type="number" value={vodMaxSpeed} onChange={(event) => setVodMaxSpeed(Number(event.target.value))} min={0} max={1000} />
                </Field>
                <Field label={t("영상 파일 형식")} hint={t("MP4는 대부분의 기기와 플레이어에서 재생할 수 있습니다.")}>
                    <Select
                        value={vodFormat}
                        onChange={(event) => setVodFormat(event.target.value)}
                        options={[
                            { value: "mp4", label: "MP4 — MPEG-4 (권장)" },
                            { value: "mkv", label: "MKV — Matroska" },
                            { value: "ts", label: "TS — MPEG Transport Stream" },
                        ]}
                    />
                </Field>
                <SettingRow
                    label="미완료 영상 파일 보관 (.part)"
                    hint={keepParts ? "취소 또는 오류가 발생해도 미완료 파일을 보관합니다." : "취소하거나 오류가 발생하면 미완료 파일을 삭제합니다."}
                    control={<Switch checked={keepParts} onChange={setKeepParts} label="미완료 영상 파일 보관" />}
                />
                <Field label="영상 파일명 형식" htmlFor="vod-filename-template" hint="{name}, {title}, {date_year}, {date_month}, {date_day}, {date_hour}, {date_minute}, {date_second}, {id}, {extractor}, {upload_date}, {download_date}, {quality}를 사용할 수 있습니다. 날짜와 시각은 다운로드 시작 기준이며 확장자는 자동으로 붙습니다.">
                    <Input id="vod-filename-template" value={vodFilenameTemplate} maxLength={240} onChange={(event) => setVodFilenameTemplate(event.target.value)} />
                </Field>
                <Button variant="primary" icon={Save} loading={vodSaving} disabled={!vodFilenameTemplate.trim()} onClick={handleSaveVod} className="w-full">
                    {vodSaving ? "저장 중..." : "영상 다운로드 설정 저장"}
                </Button>
            </Card>

            <Card className="space-y-5">
                <CardHeader icon={Radio} title="라이브 녹화 설정" />
                <Field label="라이브 녹화 화질" hint="녹화할 해상도를 선택합니다. 높은 해상도일수록 저장 공간을 더 사용합니다.">
                    <Select
                        value={recordingQuality}
                        onChange={(event) => setRecordingQuality(event.target.value)}
                        options={[
                            { value: "best", label: "최고 화질" },
                            { value: "1080p", label: "1080p" },
                            { value: "720p", label: "720p" },
                            { value: "480p", label: "480p" },
                        ]}
                    />
                </Field>
                <Field label={t("녹화 자동 재시도 횟수")} hint={t("연결이 끊기거나 녹화에 실패했을 때 다시 시도할 횟수입니다.")}>
                    <Input type="number" min={0} max={100} value={maxRetries} onChange={(event) => setMaxRetries(parseInt(event.target.value) || 0)} />
                </Field>
                <Field
                    label="Chzzk 녹화 방식"
                    hint={streamMode === "force-timemachine" ? "타임머신을 강제 사용하며, 사용할 수 없으면 녹화 요청을 실패 처리합니다." : streamMode === "request-timemachine" ? "타임머신 API를 먼저 요청하고, 사용할 수 없으면 기본 스트림으로 자동 전환합니다." : "Chzzk 기본 API에서 yt-dlp가 선택한 라이브 스트림을 사용합니다."}
                >
                    <Select
                        value={streamMode}
                        onChange={(event) => setStreamMode(event.target.value as typeof streamMode)}
                        options={[
                            { value: "standard", label: "기본 스트림 사용" },
                            { value: "request-timemachine", label: "가능하면 타임머신 사용" },
                            { value: "force-timemachine", label: "강제로 타임머신 사용" },
                        ]}
                    />
                </Field>
                {streamMode !== "standard" && (
                    <Field label="스트림 시작 오프셋 (초)" hint="타임머신이 제공하는 스트림의 시작점에서 건너뛸 시간입니다. 0이면 사용 가능한 가장 앞부분부터 받습니다.">
                        <Input type="number" min={0} max={86400} value={timeMachineOffset} onChange={(event) => setTimeMachineOffset(Math.max(0, Math.min(86400, Number(event.target.value) || 0)))} />
                    </Field>
                )}
                <SettingRow
                    label="라이브 미리보기 이미지 저장"
                    hint={saveLivePreview ? "Chzzk 라이브 썸네일을 녹화 파일 옆에 저장합니다." : "미리보기 이미지를 별도 파일로 저장하지 않습니다."}
                    control={<Switch checked={saveLivePreview} onChange={setSaveLivePreview} label="라이브 미리보기 이미지 저장" />}
                />
                <Field label="라이브 파일명 형식" hint="{name}/{channel_name}, {title}/{live_title}, {channel_uid}, {category}, {date_year}, {live_date_year}, {download_date_year}, {live_date_month}, {live_date_day}, {live_date_hour}, {live_date_minute}, {live_date_second}, {quality}, {extension} 사용 가능. 확장자는 자동 추가됩니다.">
                    <Input value={liveFilenameTemplate} onChange={(event) => setLiveFilenameTemplate(event.target.value)} maxLength={240} />
                </Field>
                <Button icon={liveSaving ? RefreshCcw : Save} loading={liveSaving} onClick={handleSaveLive} className="w-full">
                    {liveSaving ? "저장 중..." : "라이브 설정 저장"}
                </Button>
            </Card>

            <Card className="space-y-5">
                <CardHeader icon={MessageSquare} title="실시간 채팅 설정" />
                <SettingRow
                    label="라이브 채팅 저장"
                    hint={chatArchiveEnabled ? "녹화 중 채팅을 JSONL 파일로 자동 저장합니다." : "라이브 채팅을 저장하지 않습니다."}
                    control={<Switch checked={chatArchiveEnabled} onChange={setChatArchiveEnabled} label="라이브 채팅 저장" />}
                />
                <Button icon={chatSaving ? RefreshCcw : Save} loading={chatSaving} onClick={handleSaveChat} className="w-full">
                    {chatSaving ? "저장 중..." : "채팅 설정 저장"}
                </Button>
            </Card>
        </div>
    );
}
