import { useEffect, useState } from "react";
import { Save } from "lucide-react";
import { api, type DownloadCondition } from "../../api/client";
import { getErrorMessage } from "../../utils/error";
import { useToast } from "../ui/Toast";
import { Button, Field, Input, Select } from "../ui/primitives";

export const DOWNLOAD_CONDITIONS: { value: DownloadCondition; label: string }[] = [
    { value: "all", label: "모든 라이브 다운로드" },
    { value: "watchalong", label: "같이보기만 다운로드" },
    { value: "exclude_watchalong", label: "같이보기 제외하고 다운로드" },
];

export function LiveDownloadCondition() {
    const [condition, setCondition] = useState<DownloadCondition>("all");
    const [tags, setTags] = useState("같이보기");
    const [loaded, setLoaded] = useState(false);
    const [loadError, setLoadError] = useState(false);
    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState<{ condition: DownloadCondition; tags: string } | null>(null);
    const dirty = saved !== null && (condition !== saved.condition || tags !== saved.tags);
    const toast = useToast();

    const load = async () => {
        setLoadError(false);
        try {
            const settings = await api.getSettings();
            setCondition(settings.live_download_condition);
            setTags(settings.watchalong_tags);
            setSaved({ condition: settings.live_download_condition, tags: settings.watchalong_tags });
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
            toast.success("기본 다운로드 조건이 저장되었습니다.");
        } catch (error) {
            toast.error(getErrorMessage(error, "다운로드 조건 저장에 실패했습니다."));
        } finally {
            setSaving(false);
        }
    };

    if (loadError) return <div className="flex items-center justify-between gap-3 border-t border-line pt-3 text-xs text-ink-muted">다운로드 조건을 불러오지 못했습니다.<Button onClick={() => void load()}>다시 시도</Button></div>;
    return (
        <div className="border-t border-line pt-4 space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <Field label="기본 다운로드 조건" htmlFor="dashboard-download-condition">
                    <Select id="dashboard-download-condition" value={condition} disabled={!loaded || saving} onChange={(event) => setCondition(event.target.value as DownloadCondition)} options={DOWNLOAD_CONDITIONS} />
                </Field>
                <Field label="같이보기 태그" htmlFor="dashboard-watchalong-tags" hint="쉼표로 구분하며, 방송 태그 중 하나만 일치해도 같이보기로 판단합니다.">
                    <Input id="dashboard-watchalong-tags" value={tags} maxLength={500} disabled={!loaded || saving} onChange={(event) => setTags(event.target.value)} placeholder="예: 같이보기" />
                </Field>
            </div>
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="text-xs text-ink-faint leading-relaxed">
                    <p>치지직 자동 다운로드의 기본값입니다. 스트리머별 설정이 우선합니다.</p>
                    {dirty && <p className="text-[var(--primary)] mt-1" role="status">저장하지 않은 변경사항이 있습니다.</p>}
                </div>
                <Button icon={Save} loading={saving} disabled={!loaded || !dirty || !tags.trim()} onClick={() => void save()} className="shrink-0">기본 조건 저장</Button>
            </div>
        </div>
    );
}
