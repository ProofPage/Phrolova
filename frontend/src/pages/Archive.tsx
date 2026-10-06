import { useState } from "react";
import { Cookie, Download, FileAudio, Link2, Radio, TimerReset } from "lucide-react";
import { useVod } from "../contexts/VodContext";
import { useToast } from "../components/ui/Toast";
import { Button, Card, Field, Input, PageHeader } from "../components/ui/primitives";
import { getErrorMessage } from "../utils/error";
import { useLanguage } from "../contexts/LanguageContext";

export default function ArchivePage() {
    const { t } = useLanguage();
    const [url, setUrl] = useState("");
    const [loading, setLoading] = useState(false);
    const { addTask } = useVod();
    const toast = useToast();

    const handleDownload = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!url.trim()) return;
        setLoading(true);
        try {
            await addTask(url.trim());
            setUrl("");
            toast.success("X Spaces 다운로드가 시작되었습니다.");
        } catch (err: unknown) {
            toast.error(getErrorMessage(err, "다운로드 시작에 실패했습니다."));
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="product-page  space-y-4">
            <PageHeader
                icon={Radio}
                eyebrow={t("오디오 보관함")}
                title={t("X Spaces")}
                description={t("캡처한 X Spaces 스트림을 오래 보관할 수 있는 오디오 파일로 변환합니다.")}
            />

            <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.5fr)_minmax(300px,0.7fr)] gap-4">
                <Card className="relative overflow-hidden">

                    <div className="flex items-start gap-3 mb-6">
                        <span className="w-9 h-9 rounded-[var(--radius-control)] grid place-items-center bg-xspaces/10 text-xspaces"><Link2 className="w-4 h-4" /></span>
                        <div>
                            <h2 className="text-sm font-semibold text-ink">{t("다운로드 소스")}</h2>
                            <p className="text-xs text-ink-faint mt-1">{t("X Spaces 주소 또는 라이브 대시보드에서 저장한 재생 목록 주소를 붙여넣으세요.")}</p>
                        </div>
                    </div>
                    <form onSubmit={handleDownload} className="space-y-4">
                        <Field label={t("X Spaces 주소")} htmlFor="spaces-url" hint={t("라이브 대시보드에서 자동 저장한 재생 목록 주소도 사용할 수 있습니다.")}>
                            <Input
                                id="spaces-url"
                                type="url"
                                placeholder="https://x.com/i/spaces/..."
                                value={url}
                                onChange={(event) => setUrl(event.target.value)}
                                autoComplete="off"
                            />
                        </Field>
                        <div className="flex justify-end">
                            <Button type="submit" icon={Download} loading={loading} disabled={!url.trim()} variant="primary">
                                {t("다운로드 시작")}
                            </Button>
                        </div>
                    </form>
                </Card>

                <Card>
                    <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-ink-faint mb-4">{t("시작 전에")}</p>
                    <div className="space-y-4">
                        <div className="flex gap-3">
                            <span className="w-8 h-8 rounded-[var(--radius-control)] bg-info/10 text-info grid place-items-center shrink-0"><FileAudio className="w-4 h-4" /></span>
                            <div><p className="text-sm font-medium text-ink">{t("M4A 오디오")}</p><p className="text-xs text-ink-faint mt-0.5">{t("영상 없이 효율적인 오디오 형식으로 저장됩니다.")}</p></div>
                        </div>
                        <div className="flex gap-3">
                            <span className="w-8 h-8 rounded-[var(--radius-control)] bg-warn/10 text-warn grid place-items-center shrink-0"><TimerReset className="w-4 h-4" /></span>
                            <div><p className="text-sm font-medium text-ink">{t("링크 유효 기간")}</p><p className="text-xs text-ink-faint mt-0.5">{t("master playlist는 Space 종료 후 약 30일간 유효합니다.")}</p></div>
                        </div>
                        <div className="flex gap-3">
                            <span className="w-8 h-8 rounded-[var(--radius-control)] bg-surface-4 text-ink-muted grid place-items-center shrink-0"><Cookie className="w-4 h-4" /></span>
                            <div><p className="text-sm font-medium text-ink">{t("비공개 Space")}</p><p className="text-xs text-ink-faint mt-0.5">{t("설정에서 X 쿠키 파일을 먼저 지정해 주세요.")}</p></div>
                        </div>
                    </div>
                    <p className="mt-5 pt-4 border-t border-line text-xs text-ink-faint">{t("진행 상황과 저장한 파일은 영상 다운로드 화면에서 확인할 수 있습니다.")}</p>
                </Card>
            </div>
        </div>
    );
}
