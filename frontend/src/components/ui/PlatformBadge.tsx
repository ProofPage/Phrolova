import { translate } from "../../i18n";
import { DOWNLOAD_SOURCE_LABELS, type DownloadSource } from '../../api/client';
import { useLanguage } from '../../contexts/LanguageContext';
import './platform-badge.css';

export function PlatformBadge({ platform }: { platform: DownloadSource }) {
    const { t } = useLanguage();
    return <span className={`platform-badge recording-platform platform-${platform}`}>{t(DOWNLOAD_SOURCE_LABELS[platform] || translate("download.externalVideo"))}</span>;
}
