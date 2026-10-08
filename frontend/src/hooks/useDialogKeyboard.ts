import { useEffect, useRef, type RefObject } from "react";

const dialogStack: HTMLElement[] = [];

/** 중첩된 폴더 선택·확인 창에서는 맨 위 대화상자만 키보드를 처리해야 한다. */
export function useDialogKeyboard(ref: RefObject<HTMLElement | null>, onClose: () => void, active = true) {
    const closeRef = useRef(onClose);
    closeRef.current = onClose;
    useEffect(() => {
        if (!active || !ref.current) return;
        const previous = document.activeElement as HTMLElement | null;
        const root = ref.current;
        const focusable = () => Array.from(root.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex="0"]')).filter(element => element.getClientRects().length > 0);
        dialogStack.push(root);
        const focused = root.contains(document.activeElement);
        if (!focused) (root.querySelector<HTMLElement>('[data-dialog-initial-focus], [autofocus]') || focusable()[0] || root).focus();
        const onKeyDown = (event: KeyboardEvent) => {
            if (dialogStack.at(-1) !== root) return;
            if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closeRef.current(); }
            if (event.key !== "Tab") return;
            const items = focusable();
            if (!items.length) { event.preventDefault(); root.focus(); return; }
            const first = items[0], last = items[items.length - 1];
            if (event.shiftKey && (document.activeElement === first || !root.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
            else if (!event.shiftKey && (document.activeElement === last || !root.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
        };
        document.addEventListener("keydown", onKeyDown, true);
        return () => {
            document.removeEventListener("keydown", onKeyDown, true);
            const index = dialogStack.lastIndexOf(root);
            if (index >= 0) dialogStack.splice(index, 1);
            if (previous?.isConnected) previous.focus({ preventScroll: true });
        };
    }, [active, ref]);
}
