import { useLayoutEffect, useState, type CSSProperties, type RefObject } from "react";

/** 입력 키보드가 펼쳐져도 플랫폼 목록을 화면 안의 넓은 쪽으로 배치한다. */
export function useListboxPosition(open: boolean, root: RefObject<HTMLElement | null>): CSSProperties {
    const [position, setPosition] = useState<CSSProperties>({});
    useLayoutEffect(() => {
        if (!open) return;
        const update = () => {
            const trigger = root.current?.querySelector<HTMLElement>("[aria-haspopup='listbox']");
            const list = root.current?.querySelector<HTMLElement>("[role='listbox']");
            if (!trigger || !list) return;
            const rect = trigger.getBoundingClientRect();
            const viewport = window.visualViewport;
            const top = viewport?.offsetTop ?? 0;
            const left = viewport?.offsetLeft ?? 0;
            const width = viewport?.width ?? window.innerWidth;
            const height = viewport?.height ?? window.innerHeight;
            const below = top + height - rect.bottom - 12;
            const above = rect.top - top - 12;
            const down = below >= Math.min(list.scrollHeight, above);
            const maxHeight = Math.max(0, Math.min(height - 24, Math.max(44, down ? below : above)));
            const listWidth = Math.min(Math.max(180, rect.width), width - 24);
            setPosition({ position: "fixed", marginTop: 0, width: listWidth, minWidth: 0,
                left: Math.max(left + 12, Math.min(rect.left, left + width - listWidth - 12)),
                top: Math.max(top + 12, Math.min(top + height - Math.min(list.scrollHeight, maxHeight) - 12, down ? rect.bottom + 6 : rect.top - Math.min(list.scrollHeight, maxHeight) - 6)),
                maxHeight, overflowY: "auto" });
        };
        update();
        window.addEventListener("resize", update);
        window.addEventListener("scroll", update, true);
        window.visualViewport?.addEventListener("resize", update);
        window.visualViewport?.addEventListener("scroll", update);
        return () => {
            window.removeEventListener("resize", update);
            window.removeEventListener("scroll", update, true);
            window.visualViewport?.removeEventListener("resize", update);
            window.visualViewport?.removeEventListener("scroll", update);
        };
    }, [open, root]);
    return position;
}
