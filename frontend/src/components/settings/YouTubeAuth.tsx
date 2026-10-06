import { useEffect, useRef, useState } from "react";
import { KeyRound, Upload, Trash2 } from "lucide-react";
import { client } from "../../api/client";
import { useLanguage } from "../../contexts/LanguageContext";
import { getErrorMessage } from "../../utils/error";
import { useToast } from "../ui/Toast";
import { Button, Card, CardHeader, StatusDot } from "../ui/primitives";

export function YouTubeAuth() {
    const { t } = useLanguage();
    const toast = useToast();
    const input = useRef<HTMLInputElement>(null);
    const [configured, setConfigured] = useState(false);
    const [busy, setBusy] = useState(false);
    useEffect(() => {
        client.get<{ configured: boolean }>("/platforms/youtube/cookie")
            .then(({ data }) => setConfigured(data.configured))
            .catch(() => toast.error(t("요청에 실패했습니다.")));
    }, []);
    const change = async (file?: File) => {
        setBusy(true);
        try {
            if (file) {
                const body = new FormData();
                body.append("file", file);
                await client.post("/platforms/youtube/cookie", body, { headers: { "Content-Type": "multipart/form-data" } });
            } else {
                await client.delete("/platforms/youtube/cookie");
            }
            setConfigured(!!file);
            toast.success(t(file ? "YouTube 쿠키를 등록했습니다." : "쿠키 파일이 삭제되었습니다."));
        } catch (err) {
            toast.error(getErrorMessage(err, t("요청에 실패했습니다.")));
        } finally {
            setBusy(false);
            if (input.current) input.current.value = "";
        }
    };
    return <Card className="space-y-5">
        <CardHeader icon={KeyRound} title={t("YouTube")} description={t("로그인 확인이 필요한 경우 Netscape 형식의 YouTube 쿠키 파일을 등록하세요.")} />
        <div className="flex flex-wrap items-center gap-3">
            <StatusDot active={configured} label={t(configured ? "업로드됨" : "없음")} />
            <input ref={input} type="file" accept=".txt" className="hidden" onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void change(file);
            }} />
            <Button icon={Upload} loading={busy} onClick={() => input.current?.click()}>{t("파일 선택")}</Button>
            {configured && <Button variant="danger" icon={Trash2} disabled={busy} onClick={() => void change()}>{t("삭제")}</Button>}
        </div>
        <a className="text-xs text-accent underline" href="https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies" target="_blank" rel="noreferrer">{t("YouTube 쿠키 내보내기 안내")}</a>
    </Card>;
}
