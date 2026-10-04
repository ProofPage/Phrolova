import { useEffect, useState, type ReactNode } from "react";
import { Info } from "lucide-react";
import { api, type Settings as SettingsType } from "../../api/client";
import { Card, CardHeader } from "../ui/primitives";

/** 저작자 표기. LICENSE·README·exe 파일 속성과 같은 문구를 쓴다. */
const AUTHOR = "Serian";
const REPOSITORY_URL = "https://github.com/eruminyu/Rookery";

interface Props {
    settings: SettingsType | null;
    /** 정보 탭은 읽기 전용이지만 탭 props 형태를 통일한다. */
    onSaved: () => void;
    /** 정보 탭에는 편집 폼이 없음을 상위에 알린다. */
    onDirtyChange?: (dirty: boolean) => void;
}

function InfoRow({ label, children, last = false }: { label: string; children: ReactNode; last?: boolean }) {
    return (
        <div className={`flex justify-between gap-4 py-2 ${last ? "" : "border-b border-line"}`}>
            <span className="text-ink-faint">{label}</span>
            {children}
        </div>
    );
}

export function InfoTab({ settings, onDirtyChange }: Props) {
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
                    <InfoRow label="앱 이름"><span className="text-ink-muted">{settings?.app_name || "Loading..."}</span></InfoRow>
                    <InfoRow label="FFmpeg 경로"><span className="text-ink-muted truncate max-w-[220px]" title={settings?.ffmpeg_path}>{settings?.ffmpeg_path || "Loading..."}</span></InfoRow>
                    <InfoRow label="서버"><span className="text-ink-muted">{settings ? `${settings.host}:${settings.port}` : "Loading..."}</span></InfoRow>
                    <InfoRow label="Discord Bot"><span className={settings?.discord_bot_configured ? "text-ok" : "text-ink-faint"}>{settings?.discord_bot_configured ? "연결됨" : "미설정"}</span></InfoRow>
                    <InfoRow label="TwitCasting 설정"><span className={settings?.twitcasting_client_id ? "text-twitcasting" : "text-ink-faint"}>{settings?.twitcasting_client_id ? "설정됨" : "미설정"}</span></InfoRow>
                    <InfoRow label="X Spaces 쿠키" last><span className={settings?.x_cookie_file ? "text-xspaces" : "text-ink-faint"}>{settings?.x_cookie_file ? "설정됨" : "미설정"}</span></InfoRow>
                </div>
            </Card>

            <Card>
                <CardHeader icon={Info} title="이 프로그램에 대하여" />
                <div className="space-y-1 text-sm">
                    <InfoRow label="버전">
                        <span className="text-ink-muted font-mono">{version ? `v${version}` : "확인 중..."}</span>
                    </InfoRow>
                    <InfoRow label="만든 사람">
                        <span className="text-ink-muted">{AUTHOR}</span>
                    </InfoRow>
                    <InfoRow label="저장소">
                        <a
                            href={REPOSITORY_URL}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-[var(--primary)] hover:underline truncate max-w-[220px]"
                        >
                            github.com/eruminyu/Rookery
                        </a>
                    </InfoRow>
                    <InfoRow label="라이선스" last>
                        <span className="text-ink-muted">MIT</span>
                    </InfoRow>
                </div>
                <p className="text-xs text-ink-faint mt-4 leading-relaxed">
                    Copyright &copy; 2026 {AUTHOR}. MIT License로 배포됩니다.
                    <br />
                    FFmpeg는 번들되지 않으며 각자의 라이선스를 따릅니다.
                </p>
            </Card>
        </div>
    );
}
