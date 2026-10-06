import { useEffect, useRef, type RefObject } from "react";

/** Constrain keyboard focus to a mounted dialog and restore it on close. */
export function useDialogKeyboard(ref: RefObject<HTMLElement | null>, onClose: () => void, active = true) {
    const closeRef = useRef(onClose);
    closeRef.current = onClose;
    useEffect(() => {
        if (!active || !ref.current) return;
        const previous = document.activeElement as HTMLElement | null;
        const root = ref.current;
        const focusable = () => Array.from(root.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex="0"]')).filter(element => element.getClientRects().length > 0);
        (root.querySelector<HTMLElement>('[autofocus]') || focusable()[0] || root).focus();
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closeRef.current(); }
            if (event.key !== "Tab") return;
            const items = focusable();
            if (!items.length) { event.preventDefault(); root.focus(); return; }
            const first = items[0], last = items[items.length - 1];
            if (event.shiftKey && (document.activeElement === first || !root.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
            else if (!event.shiftKey && (document.activeElement === last || !root.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
        };
        root.addEventListener("keydown", onKeyDown);
        return () => { root.removeEventListener("keydown", onKeyDown); previous?.focus(); };
    }, [active, ref]);
}
