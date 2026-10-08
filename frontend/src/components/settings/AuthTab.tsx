import { YouTubeAuth } from "./YouTubeAuth";
import { useEffect, useRef, useState, type ChangeEvent } from "react";
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

export function AuthTab({ settings, onSaved, onDirtyChange }: Props) {
    const { t } = useLanguage();
    const toast = useToast();
    const confirm = useConfirm();
    const cookieFileInputRef = useRef<HTMLInputElement>(null);
    const [savingCookies, setSavingCookies] = useState(false);
    const [nidAut, setNidAut] = useState("");
    const [nidSes, setNidSes] = useState("");
    const [cookieStatus, setCookieStatus] = useState<CookieStatus>("unknown");
    const [nickname, setNickname] = useState<string | null>(null);
    const [xCookieFileSet, setXCookieFileSet] = useState(false);
    const [xCookieUploading, setXCookieUploading] = useState(false);

    useEffect(() => {
        if (settings) setXCookieFileSet(!!settings.x_cookie_file);
    }, [settings]);

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

    const handleUploadXCookie = async (event: ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (!file) return;
        setXCookieUploading(true);
        try {
            await api.uploadXCookie(file);
            setXCookieFileSet(true);
            toast.success("쿠키 파일이 업로드되었습니다.");
            onSaved();
        } catch (error) {
            toast.error(getErrorMessage(error, "쿠키 파일 업로드에 실패했습니다."));
        } finally {
            setXCookieUploading(false);
            if (cookieFileInputRef.current) cookieFileInputRef.current.value = "";
        }
    };

    const handleDeleteXCookie = async () => {
        const ok = await confirm({
            title: "쿠키 파일 삭제",
            message: "저장된 X 쿠키 파일을 삭제하시겠습니까?",
            confirmText: "삭제",
            variant: "danger",
        });
        if (!ok) return;
        try {
            await api.deleteXCookie();
            setXCookieFileSet(false);
            toast.success("쿠키 파일이 삭제되었습니다.");
            onSaved();
        } catch (error) {
            toast.error(getErrorMessage(error, "쿠키 파일 삭제에 실패했습니다."));
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
                <CardHeader icon={KeyRound} title="Chzzk" action={cookieBadge} />
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

            <Card className="space-y-5">
                <CardHeader icon={KeyRound} title="X Spaces" description="X Spaces 녹화 시 사용할 Netscape 형식 쿠키 파일을 업로드하세요." />
                <div className="flex flex-wrap items-center gap-3">
                    <StatusDot active={xCookieFileSet} label={xCookieFileSet ? "업로드됨" : "없음"} />
                    <input ref={cookieFileInputRef} type="file" accept=".txt" className="hidden" onChange={handleUploadXCookie} />
                    <Button icon={Upload} loading={xCookieUploading} onClick={() => cookieFileInputRef.current?.click()}>
                        {xCookieUploading ? "업로드 중..." : "파일 선택"}
                    </Button>
                    {xCookieFileSet && <Button variant="danger" icon={Trash2} onClick={handleDeleteXCookie}>삭제</Button>}
                </div>
                {xCookieFileSet && <p className="flex items-center gap-2 text-xs text-ok"><CheckCircle2 className="w-4 h-4" /> X Spaces 인증 파일이 준비되었습니다.</p>}
            </Card>
        </div>
    );
}
