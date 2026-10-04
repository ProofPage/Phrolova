import { useEffect, useState } from "react";
import { Gift, RefreshCcw, Terminal } from "lucide-react";
import { api, type Settings as SettingsType, type UpdateInfo } from "../../api/client";
import { getErrorMessage } from "../../utils/error";
import { UpdateModal } from "../ui/UpdateModal";
import { useToast } from "../ui/Toast";
import { Button, Card, CardHeader } from "../ui/primitives";

interface Props {
    settings: SettingsType | null;
    /** 시스템 탭은 서버 설정을 바꾸지 않지만 탭 props 형태를 통일한다. */
    onSaved: () => void;
    /** 시스템 탭에는 편집 폼이 없음을 상위에 알린다. */
    onDirtyChange?: (dirty: boolean) => void;
    onUpdateAvailabilityChange?: (available: boolean) => void;
}

export function SystemTab({ onDirtyChange, onUpdateAvailabilityChange }: Props) {
    const toast = useToast();
    const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
    const [checkingUpdate, setCheckingUpdate] = useState(false);
    const [showUpdateModal, setShowUpdateModal] = useState(false);

    useEffect(() => onDirtyChange?.(false), [onDirtyChange]);

    useEffect(() => {
        api.getUpdateStatus()
            .then((info) => {
                setUpdateInfo(info);
                onUpdateAvailabilityChange?.(info.has_update);
            })
            .catch((error) => console.error("업데이트 정보 로드 실패", error));
    }, [onUpdateAvailabilityChange]);

    const handleCheckUpdate = async () => {
        setCheckingUpdate(true);
        try {
            const info = await api.checkUpdateNow();
            setUpdateInfo(info);
            onUpdateAvailabilityChange?.(info.has_update);
            toast.success(info.has_update ? "새로운 버전이 있습니다!" : "최신 버전을 사용 중입니다.");
        } catch (error) {
            toast.error(getErrorMessage(error, "업데이트 확인에 실패했습니다."));
        } finally {
            setCheckingUpdate(false);
        }
    };

    return (
        <>
            <Card className="space-y-5">
                <CardHeader icon={Terminal} title="시스템 관리 및 업데이트" />
                <div className="bg-surface-3 p-4 rounded-[var(--radius-control)] border border-line flex items-center justify-between">
                    <div>
                        <h4 className="text-sm font-medium text-ink mb-1">현재 버전</h4>
                        <p className="text-xs text-ink-faint font-mono">v{updateInfo?.current_version || "..."}</p>
                    </div>
                    <div className="text-right">
                        <h4 className="text-sm font-medium text-ink mb-1">최신 릴리즈</h4>
                        <p className="text-xs text-ink-faint font-mono">{updateInfo?.latest_version ? `v${updateInfo.latest_version}` : "확인 중..."}</p>
                    </div>
                </div>

                <div className="flex flex-col sm:flex-row gap-3">
                    <Button icon={RefreshCcw} loading={checkingUpdate} onClick={handleCheckUpdate} className="flex-1">
                        {checkingUpdate ? "확인 중..." : "업데이트 확인"}
                    </Button>
                    {updateInfo?.has_update && (
                        <Button variant="primary" icon={Gift} onClick={() => setShowUpdateModal(true)} className="flex-1">
                            v{updateInfo.latest_version} 업데이트 하기
                        </Button>
                    )}
                </div>

                {updateInfo?.has_update && updateInfo.release_notes && (
                    <div className="mt-6">
                        <h4 className="text-sm font-medium text-ok mb-2 flex items-center gap-2"><Gift className="w-4 h-4" /> 릴리즈 노트</h4>
                        <div className="bg-surface-3 border border-line p-4 rounded-[var(--radius-control)] overflow-y-auto max-h-60 whitespace-pre-wrap text-sm text-ink-muted font-mono leading-relaxed">
                            {updateInfo.release_notes}
                        </div>
                    </div>
                )}
            </Card>

            {showUpdateModal && updateInfo && <UpdateModal info={updateInfo} onClose={() => setShowUpdateModal(false)} />}
        </>
    );
}
