import { useEffect, useState } from "react";
import { Save, Settings } from "lucide-react";
import { api, type Settings as SettingsType } from "../../api/client";
import { useSettingsSave } from "../../hooks/useSettingsSave";
import { DirInput } from "../ui/DirInput";
import { Button, Card, CardHeader, Field, Input, Select, SettingRow, Switch } from "../ui/primitives";

interface Props {
    settings: SettingsType | null;
    /** 저장 후 상위의 설정 상태를 갱신한다. */
    onSaved: () => void;
    /** 변경사항 유무를 상위 탭 전환 경고에 알린다. */
    onDirtyChange?: (dirty: boolean) => void;
}

export function GeneralTab({ settings, onSaved, onDirtyChange }: Props) {
    const [downloadDir, setDownloadDir] = useState("");
    const [monitorInterval, setMonitorInterval] = useState(30);
    const [liveFormat, setLiveFormat] = useState("ts");
    const [recordingQuality, setRecordingQuality] = useState("best");
    const [splitDownloadDirs, setSplitDownloadDirs] = useState(false);
    const [vodChzzkDir, setVodChzzkDir] = useState("");
    const [vodExternalDir, setVodExternalDir] = useState("");
    const { saving, save } = useSettingsSave(onSaved);

    useEffect(() => {
        if (!settings) return;
        setDownloadDir(settings.download_dir);
        setMonitorInterval(settings.monitor_interval);
        setLiveFormat(settings.live_format || "ts");
        setRecordingQuality(settings.recording_quality || "best");
        setSplitDownloadDirs(settings.split_download_dirs ?? false);
        setVodChzzkDir(settings.vod_chzzk_dir ?? "");
        setVodExternalDir(settings.vod_external_dir ?? "");
    }, [settings]);

    const dirty = !!settings && (
        downloadDir !== settings.download_dir ||
        monitorInterval !== settings.monitor_interval ||
        liveFormat !== (settings.live_format || "ts") ||
        recordingQuality !== (settings.recording_quality || "best") ||
        splitDownloadDirs !== (settings.split_download_dirs ?? false) ||
        vodChzzkDir !== (settings.vod_chzzk_dir ?? "") ||
        vodExternalDir !== (settings.vod_external_dir ?? "")
    );

    useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

    const handleSave = () => save({
        request: () => api.updateGeneralSettings({
            download_dir: downloadDir,
            monitor_interval: monitorInterval,
            live_format: liveFormat,
            recording_quality: recordingQuality,
            split_download_dirs: splitDownloadDirs,
            vod_chzzk_dir: vodChzzkDir,
            vod_external_dir: vodExternalDir,
        }),
        success: "일반 설정이 저장되었습니다.",
        failure: "일반 설정 저장에 실패했습니다.",
    });

    return (
        <Card className="space-y-5">
            <CardHeader icon={Settings} title="일반 설정" />

            <Field
                label="저장 경로"
                hint="라이브 녹화 + 채팅 로그가 저장되는 기본 경로입니다."
            >
                <DirInput value={downloadDir} onChange={setDownloadDir} placeholder="예: E:\recordings" />
            </Field>

            <SettingRow
                label="분할 저장 경로 사용"
                hint="활성화 시 콘텐츠 종류별로 저장 경로를 분리할 수 있습니다."
                control={<Switch checked={splitDownloadDirs} onChange={setSplitDownloadDirs} label="분할 저장 경로 사용" />}
            />

            {splitDownloadDirs && (
                <div className="space-y-4 pl-4 border-l-2 border-line-strong pt-1">
                    <Field label="치지직 VOD / 클립 저장 경로" hint="chzzk.naver.com URL 다운로드에 적용됩니다.">
                        <DirInput value={vodChzzkDir} onChange={setVodChzzkDir} placeholder="비어있으면 기본 저장 경로 사용" />
                    </Field>
                    <Field label="외부 다운로드 저장 경로 (유튜브 등)" hint="유튜브 등 외부 URL(yt-dlp) 다운로드에 적용됩니다.">
                        <DirInput value={vodExternalDir} onChange={setVodExternalDir} placeholder="비어있으면 기본 저장 경로 사용" />
                    </Field>
                </div>
            )}

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

            <Field label="녹화 품질" hint="yt-dlp가 지원하는 화질 중 선택됩니다.">
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
