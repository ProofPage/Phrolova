import { useEffect, useId, useRef, useState } from 'react';
import { PlatformSelectTrigger } from './ui/PlatformSelectTrigger';
import { useListboxKeyboard } from '../hooks/useListboxKeyboard';
import { useListboxPosition } from '../hooks/useListboxPosition';
import { useLanguage } from '../contexts/LanguageContext';
import type { DownloadSource } from '../utils/downloads';

const dots = { chzzk: 'bg-chzzk', youtube: 'bg-youtube', soop: 'bg-soop', cime: 'bg-cime', kick: 'bg-kick', twitch: 'bg-twitch', tiktok: 'bg-tiktok', bilibili: 'bg-bilibili', popkontv:'bg-popkontv', rplay:'bg-rplay', hearheart: 'bg-hearheart', anilife:'bg-info', linkani:'bg-info', ohli24:'bg-info', ohli365:'bg-info', tvwiki:'bg-info', tvchak:'bg-info', animaru:'bg-info', external: 'bg-ink-faint' };
export function DownloadSourceSelect({ sources, value, disabled, onChange }: {
    sources: { id: DownloadSource; label: string }[]; value: DownloadSource;
    disabled: boolean; onChange: (value: DownloadSource) => void;
}) {
    const { t } = useLanguage();
    const [open, setOpen] = useState(false);
    const root = useRef<HTMLDivElement>(null);
    const id = useId();
    const position = useListboxPosition(open, root);
    useListboxKeyboard(open, root, () => setOpen(false));
    useEffect(() => {
        if (!open) return;
        const close = (event: MouseEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
        document.addEventListener('mousedown', close);
        return () => document.removeEventListener('mousedown', close);
    }, [open]);
    return <div ref={root} className="relative">
        <PlatformSelectTrigger role="combobox" aria-label={t("download.downloadPlatform")} aria-expanded={open} aria-controls={id} aria-haspopup="listbox" disabled={disabled}
            label={t(sources.find(source => source.id === value)?.label ?? '')} dotClass={dots[value]}
            className="download-source-trigger" onClick={() => setOpen(current => !current)} onKeyDown={event => { if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); setOpen(true); } }} />
        {open && <div id={id} role="listbox" aria-label={t("download.downloadPlatformList")} style={position} className="ui-popover z-30 rounded-[var(--radius-control)]">
            {sources.map(source => <button key={source.id} type="button" role="option" aria-selected={source.id === value} className="w-full text-left px-3 py-2 text-sm flex items-center gap-2 text-ink-muted hover:bg-surface-3 focus-visible:bg-surface-3" onClick={() => { onChange(source.id); setOpen(false); root.current?.querySelector<HTMLButtonElement>('[role=combobox]')?.focus(); }}>
                <span aria-hidden="true" className={`size-2 rounded-full shrink-0 ${dots[source.id]}`} />{t(source.label)}
            </button>)}
        </div>}
    </div>;
}
