import { useEffect, useState } from "react";
import { Download, Film, MessageSquare, RefreshCcw, Save } from "lucide-react";
import { useSettingsSave } from "../../hooks/useSettingsSave";
import { api, type Settings as SettingsType } from "../../api/client";
import { Button, Card, CardHeader, Field, Input, Select, SettingRow, Switch } from "../ui/primitives";

interface Props {
    settings: SettingsType | null;
    /** 저장 후 상위의 설정 상태를 갱신한다. */
    onSaved: () => void;
    /** 변경사항 유무를 상위 탭 전환 경고에 알린다. */
    onDirtyChange?: (dirty: boolean) => void;
}

export function DownloadTab({ settings, onSaved, onDirtyChange }: Props) {
    const [keepParts, setKeepParts] = useState(false);
    const [maxRetries, setMaxRetries] = useState(3);
    const [vodMaxConcurrent, setVodMaxConcurrent] = useState(3);
    const [vodDefaultQuality, setVodDefaultQuality] = useState("best");
    const [vodMaxSpeed, setVodMaxSpeed] = useState(0);
    const [vodFormat, setVodFormat] = useState("mp4");
    const [chatArchiveEnabled, setChatArchiveEnabled] = useState(false);
    // 세 영역이 각각 따로 저장되므로 훅도 따로 둔다 — 저장 중 표시가 서로 섞이지 않는다.
    const { saving: downloadSaving, save: saveDownload } = useSettingsSave(onSaved);
    const { saving: vodSaving, save: saveVod } = useSettingsSave(onSaved);
    const { saving: chatSaving, save: saveChat } = useSettingsSave(onSaved);

    useEffect(() => {
        if (!settings) return;
        setKeepParts(settings.keep_download_parts);
        setMaxRetries(settings.max_record_retries);
        setVodMaxConcurrent(settings.vod_max_concurrent);
        setVodDefaultQuality(settings.vod_default_quality);
        setVodMaxSpeed(settings.vod_max_speed);
        setVodFormat(settings.vod_format || "mp4");
        setChatArchiveEnabled(settings.chat_archive_enabled);
    }, [settings]);

    const dirty = !!settings && (
        keepParts !== settings.keep_download_parts ||
        maxRetries !== settings.max_record_retries ||
        vodMaxConcurrent !== settings.vod_max_concurrent ||
        vodDefaultQuality !== settings.vod_default_quality ||
        vodMaxSpeed !== settings.vod_max_speed ||
        vodFormat !== (settings.vod_format || "mp4") ||
        chatArchiveEnabled !== settings.chat_archive_enabled
    );

    useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

    const handleSaveVod = () => saveVod({
        request: () => api.updateVodSettings({
            vod_max_concurrent: vodMaxConcurrent,
            vod_default_quality: vodDefaultQuality,
            vod_max_speed: vodMaxSpeed,
            vod_format: vodFormat,
        }),
        success: "VOD 설정이 저장되었습니다.",
        failure: "VOD 설정 저장에 실패했습니다.",
    });

    const handleSaveDownload = () => saveDownload({
        request: () => api.updateDownloadSettings(keepParts, maxRetries),
        success: "다운로드 설정이 저장되었습니다.",
        failure: "다운로드 설정 저장에 실패했습니다.",
    });

    const handleSaveChat = () => saveChat({
        request: () => api.updateChatSettings({ chat_archive_enabled: chatArchiveEnabled }),
        success: "채팅 설정이 저장되었습니다.",
        failure: "채팅 설정 저장에 실패했습니다.",
    });

    return (
        <div className="space-y-6">
            <Card className="space-y-5">
                <CardHeader icon={Film} title="VOD 다운로드 설정" />
                <Field label="동시 다운로드 개수" hint="한 번에 다운로드할 수 있는 최대 영상 개수 (1~10개)">
                    <Input type="number" value={vodMaxConcurrent} onChange={(event) => setVodMaxConcurrent(Number(event.target.value))} min={1} max={10} />
                </Field>
                <Field label="기본 화질" hint="VOD 다운로드 시 기본으로 사용할 화질">
                    <Select
                        value={vodDefaultQuality}
                        onChange={(event) => setVodDefaultQuality(event.target.value)}
                        options={[
                            { value: "best", label: "최고 화질 (Best)" },
                            { value: "1080p", label: "1080p" },
                            { value: "720p", label: "720p" },
                            { value: "480p", label: "480p" },
                        ]}
                    />
                </Field>
                <Field label="최대 다운로드 속도 (MB/s)" hint="0 = 무제한, 네트워크 대역폭 제한 시 사용">
                    <Input type="number" value={vodMaxSpeed} onChange={(event) => setVodMaxSpeed(Number(event.target.value))} min={0} max={1000} />
                </Field>
                <Field label="VOD 다운로드 포맷" hint="VOD/클립은 MP4가 가장 호환성이 좋습니다. 오디오·비디오 병합이 필요한 경우 ffmpeg를 사용합니다.">
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
                <Button variant="primary" icon={Save} loading={vodSaving} onClick={handleSaveVod} className="w-full">
                    {vodSaving ? "저장 중..." : "VOD 설정 저장"}
                </Button>
            </Card>

            <Card className="space-y-5">
                <CardHeader icon={Download} title="다운로드 설정" />
                <SettingRow
                    label="미완료 파일 보관 (.part)"
                    hint={keepParts ? "취소/오류 시 보관" : "취소 시 삭제"}
                    control={<Switch checked={keepParts} onChange={setKeepParts} label="미완료 파일 보관" />}
                />
                <Field label="자동 재시도 횟수" hint="라이브 녹화 중단 시 자동 재시도 횟수.">
                    <Input type="number" min={0} max={100} value={maxRetries} onChange={(event) => setMaxRetries(parseInt(event.target.value) || 0)} />
                </Field>
                <SettingRow
                    label="실시간 채팅 저장"
                    hint={chatArchiveEnabled ? "녹화 시 채팅을 JSONL 파일로 자동 저장합니다." : "채팅을 저장하지 않습니다."}
                    control={<Switch checked={chatArchiveEnabled} onChange={setChatArchiveEnabled} label="실시간 채팅 저장" />}
                />
                <div className="flex flex-col sm:flex-row gap-3">
                    <Button icon={downloadSaving ? RefreshCcw : Save} loading={downloadSaving} onClick={handleSaveDownload} className="flex-1">
                        {downloadSaving ? "저장 중..." : "다운로드 설정 저장"}
                    </Button>
                    <Button icon={MessageSquare} loading={chatSaving} onClick={handleSaveChat} className="flex-1">
                        {chatSaving ? "저장 중..." : "채팅 설정 저장"}
                    </Button>
                </div>
            </Card>
        </div>
    );
}
