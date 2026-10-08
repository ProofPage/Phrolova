import { useEffect, useRef, type RefObject } from "react";

export function useListboxKeyboard(open: boolean, rootRef: RefObject<HTMLElement | null>, onClose: () => void) {
    const closeRef = useRef(onClose);
    closeRef.current = onClose;
    useEffect(() => {
        const root = rootRef.current;
        if (!open || !root) return;
        const options = () => Array.from(root.querySelectorAll<HTMLButtonElement>('[role="option"]:not(:disabled)'));
        const selected = root.querySelector<HTMLButtonElement>('[role="option"][aria-selected="true"]:not(:disabled)');
        (selected || options()[0])?.focus({ preventScroll: true });
        const keydown = (event: KeyboardEvent) => {
            const items = options();
            if (event.key === "Escape") { event.preventDefault(); closeRef.current(); root.querySelector<HTMLButtonElement>('[aria-expanded]')?.focus(); }
            if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key) || !items.length) return;
            event.preventDefault();
            const current = items.indexOf(document.activeElement as HTMLButtonElement);
            const next = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1 : (current + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
            items[next]?.focus();
        };
        root.addEventListener("keydown", keydown);
        return () => root.removeEventListener("keydown", keydown);
    }, [open, rootRef]);
}
