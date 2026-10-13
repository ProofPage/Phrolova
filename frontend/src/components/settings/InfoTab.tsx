import { translate } from "../../i18n";
import { useEffect, type ReactNode } from "react";
import { Info } from "lucide-react";
import { type Settings as SettingsType } from "../../api/client";
import { MediaToolsCard } from './MediaToolsCard';
import { ProgramUpdateCard } from './ProgramUpdateCard';
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
    onUpdateAvailabilityChange?: (available: boolean) => void;
}

function InfoRow({ label, children, last = false }: { label: string; children: ReactNode; last?: boolean }) {
    useLanguage();
    return (
        <div className={`ui-info-row ${last ? "border-0" : ""}`}>
            <span className="text-ink-faint">{label}</span>
            {children}
        </div>
    );
}

export function InfoTab({ settings, onDirtyChange, onUpdateAvailabilityChange }: Props) {
    const { t } = useLanguage();

    useEffect(() => onDirtyChange?.(false), [onDirtyChange]);

    return (
        <div className="info-settings">
            <Card className="info-system-card">
                <CardHeader icon={Info} title={translate("settings.systemInformation")} />
                <div className="info-section-body">
                    <div className="space-y-1 text-sm">
                        <InfoRow label={t("settings.appName")}><span className="text-ink-muted">{settings?.app_name || t("settings.loading")}</span></InfoRow>
                        <InfoRow label="Discord Bot"><span className={settings?.discord_bot_configured ? "text-ok" : "text-ink-faint"}>{settings?.discord_bot_configured ? t("settings.configured") : t("settings.notConfigured")}</span></InfoRow>
                    </div>
                    <MediaToolsCard ffmpegVersion={settings?.ffmpeg_version} />
                </div>
            </Card>
            <ProgramUpdateCard onUpdateAvailabilityChange={onUpdateAvailabilityChange} />

            <Card>
                <CardHeader icon={Info} title={translate("settings.about")} />
                <div className="space-y-1 text-sm">
                    <InfoRow label={t("settings.author")}>
                        <span className="text-ink-muted">{AUTHOR}</span>
                    </InfoRow>
                    <InfoRow label={t("settings.repository")}>
                        <a
                            href={REPOSITORY_URL}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-[var(--primary)] hover:underline"
                        >
                            github.com/ProofPage/Phrolova
                        </a>
                    </InfoRow>
                    <InfoRow label={t("settings.license")} last>
                        <span className="text-ink-muted">MIT</span>
                    </InfoRow>
                </div>
                <p className="text-xs text-ink-faint mt-4 leading-relaxed">
                    {t("settings.copyright2026AuthorDistributedUnderTheMITLicense", {author: AUTHOR})}
                    <br />
                    {t("settings.ffmpegIsNotBundledAndIsSubjectToItsOwnLicense")}
                </p>
            </Card>
        </div>
    );
}
