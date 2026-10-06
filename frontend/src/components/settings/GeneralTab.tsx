import { useEffect, useState } from "react";
import { Save, Settings } from "lucide-react";
import { api, type Settings as SettingsType } from "../../api/client";
import { useSettingsSave } from "../../hooks/useSettingsSave";
import { DirInput } from "../ui/DirInput";
import { Button, Card, CardHeader, Field, Input, Select } from "../ui/primitives";
import { useLanguage } from "../../contexts/LanguageContext";

interface Props {
    settings: SettingsType | null;
    /** 저장 후 상위의 설정 상태를 갱신한다. */
    onSaved: () => void;
    /** 변경사항 유무를 상위 탭 전환 경고에 알린다. */
    onDirtyChange?: (dirty: boolean) => void;
}

export function GeneralTab({ settings, onSaved, onDirtyChange }: Props) {
    const { t } = useLanguage();
    const [liveDownloadDir, setLiveDownloadDir] = useState("");
    const [vodDownloadDir, setVodDownloadDir] = useState("");
    const [monitorInterval, setMonitorInterval] = useState(30);
    const [liveFormat, setLiveFormat] = useState("ts");
    const { saving, save } = useSettingsSave(onSaved);

    useEffect(() => {
        if (!settings) return;
        setLiveDownloadDir(settings.live_download_dir || settings.download_dir);
        setVodDownloadDir(settings.vod_download_dir || settings.download_dir);
        setMonitorInterval(settings.monitor_interval);
        setLiveFormat(settings.live_format || "ts");
    }, [settings]);

    const dirty = !!settings && (
        liveDownloadDir !== (settings.live_download_dir || settings.download_dir) ||
        vodDownloadDir !== (settings.vod_download_dir || settings.download_dir) ||
        monitorInterval !== settings.monitor_interval ||
        liveFormat !== (settings.live_format || "ts")
    );

    useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

    const handleSave = () => save({
        request: () => api.updateGeneralSettings({
            live_download_dir: liveDownloadDir,
            vod_download_dir: vodDownloadDir,
            monitor_interval: monitorInterval,
            live_format: liveFormat,
        }),
        success: t("일반 설정이 저장되었습니다."),
        failure: t("일반 설정 저장에 실패했습니다."),
    });

    return (
        <Card className="space-y-5">
            <CardHeader icon={Settings} title={t("일반 설정")} />

            <Field
                label={t("라이브 저장 위치")}
                hint={t("라이브 녹화 파일과 해당 방송의 채팅 로그가 저장됩니다.")}
            >
                <DirInput value={liveDownloadDir} onChange={setLiveDownloadDir} placeholder="예: E:\\recordings\\Live" />
            </Field>

            <Field
                label={t("영상 저장 위치")}
                hint={t("다운로드한 다시보기, 클립 및 영상이 저장됩니다.")}
            >
                <DirInput value={vodDownloadDir} onChange={setVodDownloadDir} placeholder="예: E:\\recordings\\Video" />
            </Field>

            <Field label={t("라이브 확인 주기 (초)")} hint={t("등록한 채널의 방송 상태를 확인하는 간격입니다 (5~300초).") }>
                <Input type="number" min={5} max={300} value={monitorInterval} onChange={(event) => setMonitorInterval(parseInt(event.target.value) || 30)} />
            </Field>

            <Field label={t("라이브 녹화 파일 형식")} hint={t("TS와 MKV는 녹화가 중단되어도 재생할 수 있습니다. MP4는 중단 시 파일이 손상될 수 있습니다.")}>
                <Select
                    value={liveFormat}
                    onChange={(event) => setLiveFormat(event.target.value)}
                    options={[
                        { value: "ts", label: t("TS — MPEG Transport Stream (권장)") },
                        { value: "mkv", label: "MKV — Matroska" },
                        { value: "mp4", label: t("MP4 (권장하지 않음 — 라이브 중단 시 파일 손상 가능)") },
                    ]}
                />
            </Field>

            <Button variant="primary" icon={Save} loading={saving} disabled={!dirty} onClick={handleSave} className="w-full">
                {saving ? t("저장 중...") : t("일반 설정 저장")}
            </Button>
        </Card>
    );
}
