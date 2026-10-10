import { PLATFORM_LABELS, type Platform } from '../../api/client';
import { useLanguage } from '../../contexts/LanguageContext';
import './platform-badge.css';

export function PlatformBadge({ platform }: { platform: Platform | 'external' }) {
    const { t } = useLanguage();
    return <span className={`platform-badge recording-platform platform-${platform}`}>{t(platform === 'external' ? '외부 영상' : PLATFORM_LABELS[platform])}</span>;
}
