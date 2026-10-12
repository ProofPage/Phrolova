import { useLayoutEffect, useRef } from 'react';

/** Align each logical row using its actual header content; details occupy separate rows. */
export function useCardGrid(enabled: boolean, itemKeys: string) {
    const gridRef = useRef<HTMLDivElement>(null);
    useLayoutEffect(() => {
        const grid = gridRef.current;
        if (!enabled || !grid || typeof ResizeObserver === 'undefined') return;
        const cards = [...grid.querySelectorAll<HTMLElement>(':scope > [data-channel-key]')];
        let pendingFrame = 0;
        const layout = () => {
            pendingFrame = 0;
            const measuredColumns = getComputedStyle(grid).gridTemplateColumns.split(' ').length;
            for (let i = 0; i < cards.length; i += measuredColumns) {
                const group = cards.slice(i, i + measuredColumns);
                const headerSize = Math.max(...group.flatMap(card =>
                    [...card.querySelectorAll('.recording-channel-identity,.recording-channel-management')]
                        .map(element => element.getBoundingClientRect().height)));
                group.forEach(card => card.style.setProperty('--recording-header-size', `${headerSize}px`));
            }
        };
        grid.classList.add('is-measured');
        layout();
        const observer = new ResizeObserver(() => {
            if (!pendingFrame) pendingFrame = requestAnimationFrame(layout);
        });
        observer.observe(grid);
        cards.forEach(card => {
            card.querySelectorAll('.recording-channel-identity,.recording-channel-management').forEach(element => observer.observe(element));
        });
        return () => {
            observer.disconnect();
            cancelAnimationFrame(pendingFrame);
            grid.classList.remove('is-measured');
            cards.forEach(card => {
                card.style.removeProperty('--recording-header-size');
            });
        };
    }, [enabled, itemKeys]);
    return gridRef;
}
