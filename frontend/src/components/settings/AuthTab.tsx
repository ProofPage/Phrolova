import { YouTubeAuth } from "./YouTubeAuth";
import { PlatformCookieAuth } from "./PlatformCookieAuth";
import { useEffect, useState, type ChangeEvent } from "react";
import { AlertCircle, CheckCircle2, KeyRound, Save, Shield, Trash2, Upload } from "lucide-react";
import { api, type Settings as SettingsType } from "../../api/client";
import { getErrorMessage } from "../../utils/error";
import { useConfirm } from "../ui/ConfirmModal";
import { useToast } from "../ui/Toast";
import { Badge, Button, Card, CardHeader, Field, Input, StatusDot } from "../ui/primitives";
import { useLanguage } from "../../contexts/LanguageContext";

interface Props {
    settings: SettingsType | null;
    /** 저장 후 상위의 설정 상태를 갱신한다. */
    onSaved: () => void;
    /** 변경사항 유무를 상위 탭 전환 경고에 알린다. */
    onDirtyChange?: (dirty: boolean) => void;
}

type CookieStatus = "valid" | "invalid" | "checking" | "unknown";

export function AuthTab({ onSaved, onDirtyChange }: Props) {
    const { t } = useLanguage();
    const toast = useToast();
    const [savingCookies, setSavingCookies] = useState(false);
    const [nidAut, setNidAut] = useState("");
    const [nidSes, setNidSes] = useState("");
    const [cookieStatus, setCookieStatus] = useState<CookieStatus>("unknown");
    const [nickname, setNickname] = useState<string | null>(null);


    const dirty = nidAut !== "" || nidSes !== "";
    useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

    const checkCookieStatus = async (showToast = false) => {
        setCookieStatus("checking");
        try {
            const response = await api.testCookies();
            if (response.valid) {
                setCookieStatus("valid");
                setNickname(response.user_status?.nickname || null);
                if (showToast) toast.success(`인증 성공! 닉네임: ${response.user_status?.nickname || "User"}`);
            } else {
                setCookieStatus("invalid");
                if (showToast) toast.error("쿠키가 유효하지 않습니다.");
            }
        } catch (error) {
            setCookieStatus("invalid");
            if (showToast) toast.error(getErrorMessage(error, "검증에 실패했습니다."));
        }
    };

    useEffect(() => {
        checkCookieStatus();
    }, []);

    const handleUpdateCookies = async () => {
        if (savingCookies) return;
        setSavingCookies(true);
        try {
            await api.updateCookies(nidAut, nidSes);
            toast.success("쿠키가 저장되었습니다!");
            setNidAut("");
            setNidSes("");
            onSaved();
        } catch {
            toast.error("쿠키 저장에 실패했습니다.");
        } finally {
            setSavingCookies(false);
        }
    };

    const cookieBadge = cookieStatus === "checking" ? (
        <Badge>확인 중...</Badge>
    ) : cookieStatus === "valid" ? (
        <Badge tone="ok"><Shield className="w-3 h-3" /> {t("유효함")} {nickname && `(${nickname})`}</Badge>
    ) : cookieStatus === "invalid" ? (
        <Badge tone="danger"><AlertCircle className="w-3 h-3" /> {t("만료/미설정")}</Badge>
    ) : (
        <Button variant="ghost" onClick={() => checkCookieStatus()}>상태 확인</Button>
    );

    return (
        <div className="space-y-6">
            <Card className="space-y-5">
                <CardHeader icon={KeyRound} title="치지직" action={cookieBadge} />
                <Field label="NID_AUT">
                    <Input type="password" value={nidAut} onChange={(event) => setNidAut(event.target.value)} placeholder="NID_AUT 쿠키 값 입력..." />
                </Field>
                <Field label="NID_SES">
                    <Input type="password" value={nidSes} onChange={(event) => setNidSes(event.target.value)} placeholder="NID_SES 쿠키 값 입력..." />
                </Field>
                <div className="flex gap-3">
                    <Button icon={Save} loading={savingCookies} onClick={handleUpdateCookies} className="flex-1">저장</Button>
                    <Button variant="primary" icon={Shield} loading={cookieStatus === "checking"} onClick={() => checkCookieStatus(true)} className="flex-1">검증</Button>
                </div>
            </Card>



            <YouTubeAuth />
            <PlatformCookieAuth platform="soop" onSaved={onSaved} />
            <PlatformCookieAuth platform="cime" onSaved={onSaved} />


        </div>
    );
}
