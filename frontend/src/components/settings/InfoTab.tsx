import { useEffect, useState, type ReactNode } from "react";
import { Info } from "lucide-react";
import { api, type Settings as SettingsType } from "../../api/client";
import { Card, CardHeader } from "../ui/primitives";
import { useLanguage } from "../../contexts/LanguageContext";

const AUTHOR = "ProofPage";
const REPOSITORY_URL = "https://github.com/ProofPage/Phrolova";

interface Props {
    settings: SettingsType | null;
    /** 정보 탭은 읽기 전용이지만 탭 props 형태를 통일한다. */
    onSaved: () => void;
    /** 정보 탭에는 편집 폼이 없음을 상위에 알린다. */
    onDirtyChange?: (dirty: boolean) => void;
}

function InfoRow({ label, children, last = false }: { label: string; children: ReactNode; last?: boolean }) {
    return (
        <div className={`ui-info-row ${last ? "border-0" : ""}`}>
            <span className="text-ink-faint">{label}</span>
            {children}
        </div>
    );
}

export function InfoTab({ settings, onDirtyChange }: Props) {
    const { t } = useLanguage();
    const [version, setVersion] = useState<string | null>(null);

    useEffect(() => onDirtyChange?.(false), [onDirtyChange]);

    useEffect(() => {
        // 버전은 backend/app/version.py가 단일 출처다. 화면에 상수로 박아두면 어긋난다.
        api.getUpdateStatus()
            .then((info) => setVersion(info.current_version))
            .catch(() => setVersion(null));
    }, []);

    return (
        <div className="space-y-5">
            <Card>
                <CardHeader icon={Info} title="시스템 정보" />
                <div className="space-y-1 text-sm">
                    <InfoRow label={t("앱 이름")}><span className="text-ink-muted">{settings?.app_name || t("불러오는 중…")}</span></InfoRow>
                    <InfoRow label={t("FFmpeg 버전")}><span className={settings?.ffmpeg_version ? "text-ok" : "text-ink-faint"}>{settings?.ffmpeg_version ? `${t("설치됨")} · v${settings.ffmpeg_version}` : t("버전을 확인할 수 없음")}</span></InfoRow>
                    <InfoRow label="Streamlink"><span className={settings?.streamlink_version ? "text-ok" : "text-ink-faint"}>{settings?.streamlink_version ? `${t("설치됨")} · v${settings.streamlink_version}` : t("설치되지 않음")}</span></InfoRow>
                    <InfoRow label={t("서버 주소")}><span className="text-ink-muted">{settings ? `${settings.host}:${settings.port}` : t("불러오는 중…")}</span></InfoRow>
                    <InfoRow label="Discord Bot"><span className={settings?.discord_bot_configured ? "text-ok" : "text-ink-faint"}>{settings?.discord_bot_configured ? t("연결됨") : t("미설정")}</span></InfoRow>
                    <InfoRow label={t("X Spaces 쿠키")} last><span className={settings?.x_cookie_file ? "text-xspaces" : "text-ink-faint"}>{settings?.x_cookie_file ? t("설정됨") : t("미설정")}</span></InfoRow>
                </div>
            </Card>

            <Card>
                <CardHeader icon={Info} title="프로그램 정보" />
                <div className="space-y-1 text-sm">
                    <InfoRow label={t("버전")}>
                        <span className="text-ink-muted font-mono">{version ? `v${version}` : t("확인 중...")}</span>
                    </InfoRow>
                    <InfoRow label={t("만든 사람")}>
                        <span className="text-ink-muted">{AUTHOR}</span>
                    </InfoRow>
                    <InfoRow label={t("저장소")}>
                        <a
                            href={REPOSITORY_URL}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-[var(--primary)] hover:underline"
                        >
                            github.com/ProofPage/Phrolova
                        </a>
                    </InfoRow>
                    <InfoRow label={t("라이선스")} last>
                        <span className="text-ink-muted">MIT</span>
                    </InfoRow>
                </div>
                <p className="text-xs text-ink-faint mt-4 leading-relaxed">
                    {t("Copyright © 2026 {author}. 배포 라이선스: MIT.").replace("{author}", AUTHOR)}
                    <br />
                    {t("FFmpeg는 앱에 포함되지 않으며 별도의 라이선스를 따릅니다.")}
                </p>
            </Card>
        </div>
    );
}
