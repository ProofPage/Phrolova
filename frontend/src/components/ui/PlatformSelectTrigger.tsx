import type { ButtonHTMLAttributes } from 'react';
import { ChevronDown } from 'lucide-react';

/** Live and download registration use the same label/dot/arrow geometry. */
export function PlatformSelectTrigger({ label, dotClass, className = '', ...props }:
    ButtonHTMLAttributes<HTMLButtonElement> & { label: string; dotClass: string }) {
    return <button type="button" {...props} className={`ui-input input-focus w-full flex items-center gap-2 media-platform-trigger ${className}`}>
        <span aria-hidden="true" className={`size-2 rounded-full shrink-0 ${dotClass}`} />
        <span className="flex-1 text-left">{label}</span>
        <ChevronDown aria-hidden="true" className="size-3 shrink-0 text-ink-faint" />
    </button>;
}
