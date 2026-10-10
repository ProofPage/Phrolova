import { useEffect, useId, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { useListboxKeyboard } from '../hooks/useListboxKeyboard';
import { useListboxPosition } from '../hooks/useListboxPosition';
import { useLanguage } from '../contexts/LanguageContext';
import type { DownloadSource } from '../utils/downloads';

const dots = { chzzk: 'bg-chzzk', youtube: 'bg-youtube', soop: 'bg-soop', cime: 'bg-cime', external: 'bg-ink-faint' };
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
        <button type="button" role="combobox" aria-label={t('다운로드 플랫폼')} aria-expanded={open} aria-controls={id} aria-haspopup="listbox" disabled={disabled}
            className="ui-input input-focus w-full flex items-center gap-2 download-source-trigger" onClick={() => setOpen(current => !current)} onKeyDown={event => { if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); setOpen(true); } }}>
            <span aria-hidden="true" className={`size-2 rounded-full shrink-0 ${dots[value]}`} /><span className="flex-1 text-left">{t(sources.find(source => source.id === value)?.label ?? '')}</span><ChevronDown className="size-3 text-ink-faint" />
        </button>
        {open && <div id={id} role="listbox" aria-label={t('다운로드 플랫폼 목록')} style={position} className="ui-popover z-30 rounded-[var(--radius-control)]">
            {sources.map(source => <button key={source.id} type="button" role="option" aria-selected={source.id === value} className="w-full text-left px-3 py-2 text-sm flex items-center gap-2 text-ink-muted hover:bg-surface-3 focus-visible:bg-surface-3" onClick={() => { onChange(source.id); setOpen(false); root.current?.querySelector<HTMLButtonElement>('[role=combobox]')?.focus(); }}>
                <span aria-hidden="true" className={`size-2 rounded-full shrink-0 ${dots[source.id]}`} />{t(source.label)}
            </button>)}
        </div>}
    </div>;
}
