import { useEffect } from "react";

/** One passive listener for all shared controls; no React renders on pointer movement. */
export function useLiquidGlass() {
    useEffect(() => {
        const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
        let frame = 0;
        let active: HTMLElement | null = null;
        let x = 0;
        let y = 0;
        const clear = () => {
            cancelAnimationFrame(frame);
            frame = 0;
            active?.style.removeProperty("--glass-x");
            active?.style.removeProperty("--glass-y");
            active = null;
        };
        const move = (event: PointerEvent) => {
            if (event.pointerType !== "mouse" || motion.matches) return;
            const control = event.target instanceof Element
                ? event.target.closest<HTMLElement>(".ui-button, .icon-button, .top-search, .dashboard-filter, .settings-tabs button, .ui-chip")
                : null;
            if (!control || control.matches(":disabled")) { clear(); return; }
            if (control !== active) { clear(); active = control; }
            x = event.clientX;
            y = event.clientY;
            if (!frame) frame = requestAnimationFrame(() => {
                frame = 0;
                if (!active) return;
                const bounds = active.getBoundingClientRect();
                active.style.setProperty("--glass-x", `${x - bounds.left}px`);
                active.style.setProperty("--glass-y", `${y - bounds.top}px`);
            });
        };
        document.addEventListener("pointermove", move, { passive: true });
        document.addEventListener("pointerleave", clear);
        motion.addEventListener("change", clear);
        return () => {
            document.removeEventListener("pointermove", move);
            document.removeEventListener("pointerleave", clear);
            motion.removeEventListener("change", clear);
            clear();
        };
    }, []);
}
