import { translate } from "../../i18n";
import { DOWNLOAD_SOURCE_LABELS, PLATFORM_LABELS, type DownloadSource, type Platform } from '../../api/client';
import { useLanguage } from '../../contexts/LanguageContext';
import './platform-badge.css';

export function PlatformBadge({ platform }: { platform: DownloadSource | Platform }) {
    const { t } = useLanguage();
    return <span className={`platform-badge recording-platform platform-${platform}`}>{t((platform === 'pandalive' || platform === 'spoon' ? PLATFORM_LABELS[platform] : DOWNLOAD_SOURCE_LABELS[platform]) || translate("download.externalVideo"))}</span>;
}
