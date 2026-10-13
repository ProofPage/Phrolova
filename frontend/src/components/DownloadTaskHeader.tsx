import type { ReactNode } from 'react';
import { ShieldCheck } from 'lucide-react';
import type { VodTask } from '../api/client';
import { useLanguage } from '../contexts/LanguageContext';
import { formatDuration } from '../utils/format';
import { PlatformBadge } from './ui/PlatformBadge';
import { DownloadThumbnail } from './DownloadThumbnail';
import { detectDownloadPlatform } from '../utils/downloads';

export function DownloadTaskHeader({ task, duration, actions }: { task: VodTask; duration?: number | null; actions: ReactNode }) {
    const { t } = useLanguage();
    const length = typeof duration === 'number' && Number.isFinite(duration) && duration > 0 ? formatDuration(duration) : t("download.checkingVideoDuration");
    const media = length + (task.cdn_applied ? ` · ${task.cdn === 'akamai' ? 'Akamai CDN' : 'Naver CDN'}` : '');
    const inspectionLabel = task.state === 'completed' && task.inspection_state === 'passed' ? t("download.fileInspectionComplete") : null;
    const uploader = task.metadata?.uploader || t("download.checkingChannelInformation");
    return <header className="download-task-header">
        <DownloadThumbnail src={task.metadata?.thumbnail} />
        <div className="download-task-copy">
            <h3 className="download-title" title={task.title || task.url}>{task.title || t("download.checkingVideoInformation")}</h3>
            <div className="download-task-meta"><span className="download-uploader" title={uploader}>{uploader}</span><PlatformBadge platform={task.platform || detectDownloadPlatform(task.url)} /></div>
            <p className="download-media-meta" title={media}>{media}</p>
        </div>
        <div className="download-task-header-actions">
            {inspectionLabel && <span className="download-inspection-passed"><ShieldCheck className="size-3.5" aria-hidden="true" />{inspectionLabel}</span>}
            {actions}
        </div>
    </header>;
}
