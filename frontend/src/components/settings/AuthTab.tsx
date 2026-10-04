import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { AlertCircle, CheckCircle2, KeyRound, Save, Shield, Trash2, Upload } from "lucide-react";
import { api, type Settings as SettingsType } from "../../api/client";
import { getErrorMessage } from "../../utils/error";
import { useSettingsSave } from "../../hooks/useSettingsSave";
import { useConfirm } from "../ui/ConfirmModal";
import { useToast } from "../ui/Toast";
import { Badge, Button, Card, CardHeader, Field, Input, StatusDot } from "../ui/primitives";

interface Props {
    settings: SettingsType | null;
    /** 저장 후 상위의 설정 상태를 갱신한다. */
    onSaved: () => void;
    /** 변경사항 유무를 상위 탭 전환 경고에 알린다. */
    onDirtyChange?: (dirty: boolean) => void;
}

type CookieStatus = "valid" | "invalid" | "checking" | "unknown";

export function AuthTab({ settings, onSaved, onDirtyChange }: Props) {
    const toast = useToast();
    const confirm = useConfirm();
    const cookieFileInputRef = useRef<HTMLInputElement>(null);
    const [nidAut, setNidAut] = useState("");
    const [nidSes, setNidSes] = useState("");
    const [cookieStatus, setCookieStatus] = useState<CookieStatus>("unknown");
    const [nickname, setNickname] = useState<string | null>(null);
    const [twitcastingClientId, setTwitcastingClientId] = useState("");
    const [twitcastingClientSecret, setTwitcastingClientSecret] = useState("");
    const { saving: twitcastingSaving, save: saveTwitcasting } = useSettingsSave(onSaved);
    const [xCookieFileSet, setXCookieFileSet] = useState(false);
    const [xCookieUploading, setXCookieUploading] = useState(false);

    useEffect(() => {
        if (settings) setXCookieFileSet(!!settings.x_cookie_file);
    }, [settings]);

    const dirty = nidAut !== "" || nidSes !== "" || twitcastingClientId !== "" || twitcastingClientSecret !== "";
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
        try {
            await api.updateCookies(nidAut, nidSes);
            toast.success("쿠키가 저장되었습니다!");
            setNidAut("");
            setNidSes("");
            onSaved();
        } catch {
            toast.error("쿠키 저장에 실패했습니다.");
        }
    };

    const handleSaveTwitcasting = () => {
        if (!twitcastingClientId || !twitcastingClientSecret) {
            toast.error("Client ID와 Client Secret을 모두 입력하세요.");
            return;
        }
        saveTwitcasting({
            request: () => api.updateTwitcastingSettings({
                client_id: twitcastingClientId,
                client_secret: twitcastingClientSecret,
            }),
            success: "TwitCasting 인증 설정이 저장되었습니다.",
            failure: "TwitCasting 설정 저장에 실패했습니다.",
            // 성공했을 때만 비운다. 실패하면 다시 입력하지 않아도 되도록.
            afterSuccess: () => {
                setTwitcastingClientId("");
                setTwitcastingClientSecret("");
            },
        });
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
        <Badge tone="ok"><Shield className="w-3 h-3" /> 유효함 {nickname && `(${nickname})`}</Badge>
    ) : cookieStatus === "invalid" ? (
        <Badge tone="danger"><AlertCircle className="w-3 h-3" /> 만료/미설정</Badge>
    ) : (
        <Button variant="ghost" onClick={() => checkCookieStatus()}>상태 확인</Button>
    );

    return (
        <div className="space-y-6">
            <Card className="space-y-5">
                <CardHeader icon={KeyRound} title="치지직 (Chzzk)" action={cookieBadge} />
                <Field label="NID_AUT">
                    <Input type="password" value={nidAut} onChange={(event) => setNidAut(event.target.value)} placeholder="NID_AUT 쿠키 값 입력..." />
                </Field>
                <Field label="NID_SES">
                    <Input type="password" value={nidSes} onChange={(event) => setNidSes(event.target.value)} placeholder="NID_SES 쿠키 값 입력..." />
                </Field>
                <div className="flex gap-3">
                    <Button icon={Save} onClick={handleUpdateCookies} className="flex-1">저장</Button>
                    <Button variant="primary" icon={Shield} onClick={() => checkCookieStatus(true)} className="flex-1">검증</Button>
                </div>
            </Card>

            <Card className="space-y-5">
                <CardHeader
                    icon={KeyRound}
                    title="TwitCasting"
                    description={<><a href="https://twitcasting.tv/developer.php" target="_blank" rel="noopener noreferrer" className="text-twitcasting hover:underline">개발자 페이지</a>에서 앱 등록 후 발급받은 API v2 인증 정보를 입력하세요.</>}
                />
                <Field label="Client ID">
                    <Input value={twitcastingClientId} onChange={(event) => setTwitcastingClientId(event.target.value)} placeholder="TwitCasting Client ID..." />
                </Field>
                <Field label="Client Secret">
                    <Input type="password" value={twitcastingClientSecret} onChange={(event) => setTwitcastingClientSecret(event.target.value)} placeholder="TwitCasting Client Secret..." />
                </Field>
                <Button variant="primary" icon={Save} loading={twitcastingSaving} onClick={handleSaveTwitcasting} className="w-full">
                    {twitcastingSaving ? "저장 중..." : "TwitCasting 설정 저장"}
                </Button>
            </Card>

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
