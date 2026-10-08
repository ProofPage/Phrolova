import { useEffect } from "react";

/** 키보드가 레이아웃 viewport를 줄이지 않는 브라우저에서도 오버레이를 입력 영역 안에 둔다. */
export function useVisualViewport() {
    useEffect(() => {
        const viewport = window.visualViewport;
        const update = () => {
            const style = document.documentElement.style;
            style.setProperty("--ui-viewport-height", `${viewport?.height ?? window.innerHeight}px`);
            style.setProperty("--ui-viewport-width", `${viewport?.width ?? window.innerWidth}px`);
            style.setProperty("--ui-viewport-top", `${viewport?.offsetTop ?? 0}px`);
            style.setProperty("--ui-viewport-left", `${viewport?.offsetLeft ?? 0}px`);
        };
        update();
        viewport?.addEventListener("resize", update);
        viewport?.addEventListener("scroll", update);
        window.addEventListener("resize", update);
        return () => {
            viewport?.removeEventListener("resize", update);
            viewport?.removeEventListener("scroll", update);
            window.removeEventListener("resize", update);
        };
    }, []);
}
