import { useState } from 'react';

function ThumbnailSlot({ src }: { src?: string }) {
    const [state, setState] = useState<'loading' | 'loaded' | 'failed'>(src ? 'loading' : 'failed');
    return <span className="download-thumbnail" data-image-state={state} aria-hidden="true">
        <span className="download-thumbnail-placeholder" hidden={state === 'loaded'}>Phrolova</span>
        {src && state !== 'failed' && <img className="download-thumbnail-image" src={src} alt="" referrerPolicy="no-referrer"
            onLoad={event => setState(event.currentTarget.naturalWidth > 0 ? 'loaded' : 'failed')} onError={() => setState('failed')} />}
    </span>;
}

/** A new source resets failure/loading state without changing the reserved slot. */
export function DownloadThumbnail({ src }: { src?: string }) {
    return <ThumbnailSlot key={src || ''} src={src} />;
}
