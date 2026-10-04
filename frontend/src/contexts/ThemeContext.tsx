/**
 * ThemeContext: 웹 UI 개인화 (테마·타이틀·파비콘)
 * localStorage 기반으로 백엔드 없이 완결.
 */
import { createContext, useContext, useEffect, useState, ReactNode } from "react";

export type ThemeId = "green" | "blue" | "purple" | "orange" | "red" | "custom";

export interface ThemePreset {
    id: ThemeId;
    label: string;
    primary: string;
    dark: string;
}

export const THEMES: ThemePreset[] = [
    { id: "green", label: "치지직 (기본)", primary: "#00FFA3", dark: "#00D689" },
    { id: "blue", label: "블루", primary: "#3B82F6", dark: "#2563EB" },
    { id: "purple", label: "퍼플", primary: "#A855F7", dark: "#9333EA" },
    { id: "orange", label: "오렌지", primary: "#F97316", dark: "#EA6C0A" },
    { id: "red", label: "레드", primary: "#EF4444", dark: "#DC2626" },
];

const DEFAULT_TITLE = "Phrolova";

/** 과거 버전에서 기본값으로 저장된 타이틀. */
const LEGACY_DEFAULT_TITLES = ["Rookery", "Signal Recorder", "Signal-Recorder"];
const DEFAULT_CUSTOM_COLOR = "#6366F1"; // 기본 커스텀 색 (인디고)
const STORAGE_KEYS = {
    theme: "chzzk_theme",
    customColor: "chzzk_custom_color",
    title: "chzzk_title",
    iconUrl: "chzzk_icon_url",
} as const;

// ── 색상 유틸 ──────────────────────────────────────

/** hex 컬러를 어둡게 (factor: 0.18 = 18% 어둡게) */
function darkenHex(hex: string, factor = 0.18): string {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    const dr = Math.max(0, Math.round(r * (1 - factor)));
    const dg = Math.max(0, Math.round(g * (1 - factor)));
    const db = Math.max(0, Math.round(b * (1 - factor)));
    return `#${dr.toString(16).padStart(2, "0")}${dg.toString(16).padStart(2, "0")}${db.toString(16).padStart(2, "0")}`;
}

/** hex → rgba 문자열 */
function hexToRgba(hex: string, alpha: number): string {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r},${g},${b},${alpha})`;
}

// ── DOM 적용 헬퍼 ──────────────────────────────────

function applyPresetTheme(id: ThemeId) {
    // 인라인 CSS 변수 초기화 (커스텀→프리셋 전환 시 제거)
    const el = document.documentElement;
    el.style.removeProperty("--primary");
    el.style.removeProperty("--primary-dark");
    el.style.removeProperty("--primary-dim");
    el.style.removeProperty("--primary-ring");
    el.setAttribute("data-theme", id);
}

function applyCustomColor(hex: string) {
    const dark = darkenHex(hex);
    const dim = hexToRgba(hex, 0.15);
    const ring = hexToRgba(hex, 0.5);
    const el = document.documentElement;
    el.setAttribute("data-theme", "custom");
    el.style.setProperty("--primary", hex);
    el.style.setProperty("--primary-dark", dark);
    el.style.setProperty("--primary-dim", dim);
    el.style.setProperty("--primary-ring", ring);
}

/**
 * 저장된 페이지 타이틀을 읽되, 옛 기본값이면 새 기본값으로 승격한다.
 *
 * 타이틀은 브라우저별로 커스터마이징되어 localStorage에 남는다. 기본값 상수만
 * 바꾸면 기존 사용자 화면에는 계속 옛 이름이 보인다. 반대로 사용자가 직접
 * 지정한 값은 그대로 둬야 하므로, 옛 기본값과 정확히 일치할 때만 승격한다.
 */
function readStoredTitle(): string {
    const stored = localStorage.getItem(STORAGE_KEYS.title);
    if (!stored) return DEFAULT_TITLE;
    if (LEGACY_DEFAULT_TITLES.includes(stored)) {
        localStorage.removeItem(STORAGE_KEYS.title);
        return DEFAULT_TITLE;
    }
    return stored;
}

function applyTitle(title: string) {
    document.title = title || DEFAULT_TITLE;
}

function applyFavicon(url: string) {
    const existing = document.querySelector<HTMLLinkElement>("link[rel~='icon']");
    const link = existing ?? document.createElement("link");
    link.rel = "icon";
    link.href = url || "/favicon.ico";
    if (!existing) document.head.appendChild(link);
}

// ── Context ───────────────────────────────────────

interface ThemeContextValue {
    themeId: ThemeId;
    customColor: string;
    pageTitle: string;
    iconUrl: string;
    setTheme: (id: ThemeId) => void;
    setCustomColor: (hex: string) => void;
    setPageTitle: (title: string) => void;
    setIconUrl: (url: string) => void;
    resetAll: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
    const [themeId, setThemeId] = useState<ThemeId>(() =>
        (localStorage.getItem(STORAGE_KEYS.theme) as ThemeId) || "green"
    );
    const [customColor, setCustomColorState] = useState<string>(() =>
        localStorage.getItem(STORAGE_KEYS.customColor) || DEFAULT_CUSTOM_COLOR
    );
    const [pageTitle, setPageTitleState] = useState<string>(readStoredTitle);
    const [iconUrl, setIconUrlState] = useState<string>(() =>
        localStorage.getItem(STORAGE_KEYS.iconUrl) || ""
    );

    // 최초 마운트: 저장값 즉시 DOM 반영
    useEffect(() => {
        if (themeId === "custom") {
            applyCustomColor(customColor);
        } else {
            applyPresetTheme(themeId);
        }
        applyTitle(pageTitle);
        applyFavicon(iconUrl);
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    const setTheme = (id: ThemeId) => {
        setThemeId(id);
        localStorage.setItem(STORAGE_KEYS.theme, id);
        if (id === "custom") {
            applyCustomColor(customColor);
        } else {
            applyPresetTheme(id);
        }
    };

    const setCustomColor = (hex: string) => {
        setCustomColorState(hex);
        setThemeId("custom");
        localStorage.setItem(STORAGE_KEYS.customColor, hex);
        localStorage.setItem(STORAGE_KEYS.theme, "custom");
        applyCustomColor(hex);
    };

    const setPageTitle = (title: string) => {
        const trimmed = title.trim().slice(0, 32);
        setPageTitleState(trimmed || DEFAULT_TITLE);
        localStorage.setItem(STORAGE_KEYS.title, trimmed);
        applyTitle(trimmed);
    };

    const setIconUrl = (url: string) => {
        setIconUrlState(url);
        localStorage.setItem(STORAGE_KEYS.iconUrl, url);
        applyFavicon(url);
    };

    const resetAll = () => {
        setThemeId("green");
        setCustomColorState(DEFAULT_CUSTOM_COLOR);
        setPageTitleState(DEFAULT_TITLE);
        setIconUrlState("");
        localStorage.removeItem(STORAGE_KEYS.theme);
        localStorage.removeItem(STORAGE_KEYS.customColor);
        localStorage.removeItem(STORAGE_KEYS.title);
        localStorage.removeItem(STORAGE_KEYS.iconUrl);
        applyPresetTheme("green");
        applyTitle(DEFAULT_TITLE);
        applyFavicon("");
    };

    return (
        <ThemeContext.Provider value={{ themeId, customColor, pageTitle, iconUrl, setTheme, setCustomColor, setPageTitle, setIconUrl, resetAll }}>
            {children}
        </ThemeContext.Provider>
    );
}

export function useTheme(): ThemeContextValue {
    const ctx = useContext(ThemeContext);
    if (!ctx) throw new Error("useTheme must be used inside <ThemeProvider>");
    return ctx;
}
