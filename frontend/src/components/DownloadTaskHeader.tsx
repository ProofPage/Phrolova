import type { ReactNode } from 'react';
import type { VodTask } from '../api/client';
import { useLanguage } from '../contexts/LanguageContext';
import { formatDuration } from '../utils/format';
import { PlatformBadge } from './ui/PlatformBadge';
import { DownloadThumbnail } from './DownloadThumbnail';
import { detectDownloadPlatform } from '../utils/downloads';

export function DownloadTaskHeader({ task, duration, actions }: { task: VodTask; duration?: number | null; actions: ReactNode }) {
    const { t } = useLanguage();
    const length = typeof duration === 'number' && Number.isFinite(duration) && duration > 0 ? formatDuration(duration) : t('영상 길이 확인 중');
    const media = length + (task.cdn_applied ? ` · ${task.cdn === 'akamai' ? 'Akamai CDN' : t('기본 CDN')}` : '');
    const uploader = task.metadata?.uploader || t('채널 정보 확인 중');
    return <header className="download-task-header">
        <DownloadThumbnail src={task.metadata?.thumbnail} />
        <div className="download-task-copy">
            <h3 className="download-title" title={task.title || task.url}>{task.title || t('영상 정보 확인 중')}</h3>
            <div className="download-task-meta"><span className="download-uploader" title={uploader}>{uploader}</span><PlatformBadge platform={task.platform || detectDownloadPlatform(task.url)} /></div>
            <p className="download-media-meta" title={media}>{media}</p>
        </div>
        {actions}
    </header>;
}
