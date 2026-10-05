import { useEffect, useState } from "react";
import { Save, Settings } from "lucide-react";
import { api, type Settings as SettingsType } from "../../api/client";
import { useSettingsSave } from "../../hooks/useSettingsSave";
import { DirInput } from "../ui/DirInput";
import { Button, Card, CardHeader, Field, Input, Select } from "../ui/primitives";

interface Props {
    settings: SettingsType | null;
    /** 저장 후 상위의 설정 상태를 갱신한다. */
    onSaved: () => void;
    /** 변경사항 유무를 상위 탭 전환 경고에 알린다. */
    onDirtyChange?: (dirty: boolean) => void;
}

export function GeneralTab({ settings, onSaved, onDirtyChange }: Props) {
    const [liveDownloadDir, setLiveDownloadDir] = useState("");
    const [vodDownloadDir, setVodDownloadDir] = useState("");
    const [monitorInterval, setMonitorInterval] = useState(30);
    const [liveFormat, setLiveFormat] = useState("ts");
    const [recordingQuality, setRecordingQuality] = useState("best");
    const { saving, save } = useSettingsSave(onSaved);

    useEffect(() => {
        if (!settings) return;
        setLiveDownloadDir(settings.live_download_dir || settings.download_dir);
        setVodDownloadDir(settings.vod_download_dir || settings.download_dir);
        setMonitorInterval(settings.monitor_interval);
        setLiveFormat(settings.live_format || "ts");
        setRecordingQuality(settings.recording_quality || "best");
    }, [settings]);

    const dirty = !!settings && (
        liveDownloadDir !== (settings.live_download_dir || settings.download_dir) ||
        vodDownloadDir !== (settings.vod_download_dir || settings.download_dir) ||
        monitorInterval !== settings.monitor_interval ||
        liveFormat !== (settings.live_format || "ts") ||
        recordingQuality !== (settings.recording_quality || "best")
    );

    useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

    const handleSave = () => save({
        request: () => api.updateGeneralSettings({
            live_download_dir: liveDownloadDir,
            vod_download_dir: vodDownloadDir,
            monitor_interval: monitorInterval,
            live_format: liveFormat,
            recording_quality: recordingQuality,
        }),
        success: "일반 설정이 저장되었습니다.",
        failure: "일반 설정 저장에 실패했습니다.",
    });

    return (
        <Card className="space-y-5">
            <CardHeader icon={Settings} title="일반 설정" />

            <Field
                label="라이브 저장 경로"
                hint="라이브 녹화 파일과 해당 방송의 채팅 로그가 저장됩니다."
            >
                <DirInput value={liveDownloadDir} onChange={setLiveDownloadDir} placeholder="예: E:\\recordings\\Live" />
            </Field>

            <Field
                label="다시보기 저장 경로"
                hint="치지직 다시보기·클립과 외부 영상 다운로드가 저장됩니다."
            >
                <DirInput value={vodDownloadDir} onChange={setVodDownloadDir} placeholder="예: E:\\recordings\\Video" />
            </Field>

            <Field label="감시 주기 (초)" hint="채널 라이브 상태를 확인하는 간격 (5~300초).">
                <Input type="number" min={5} max={300} value={monitorInterval} onChange={(event) => setMonitorInterval(parseInt(event.target.value) || 30)} />
            </Field>

            <Field label="라이브 녹화 포맷" hint="TS/MKV는 녹화 중단 시에도 파일이 유지됩니다. MP4는 라이브 녹화에 적합하지 않습니다.">
                <Select
                    value={liveFormat}
                    onChange={(event) => setLiveFormat(event.target.value)}
                    options={[
                        { value: "ts", label: "TS — MPEG Transport Stream (권장)" },
                        { value: "mkv", label: "MKV — Matroska" },
                        { value: "mp4", label: "MP4 (권장하지 않음 — 라이브 중단 시 파일 손상 가능)" },
                    ]}
                />
            </Field>

            <Field label="라이브 품질">
                <Select
                    value={recordingQuality}
                    onChange={(event) => setRecordingQuality(event.target.value)}
                    options={[
                        { value: "best", label: "최고 (Best)" },
                        { value: "1080p", label: "1080p" },
                        { value: "720p", label: "720p" },
                        { value: "480p", label: "480p" },
                    ]}
                />
            </Field>

            <Button variant="primary" icon={Save} loading={saving} onClick={handleSave} className="w-full">
                {saving ? "저장 중..." : "일반 설정 저장"}
            </Button>
        </Card>
    );
}
