import { useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { LANGUAGE_OPTIONS, type Locale, normalizeLocale, readLocale, setActiveLocale, STORAGE_KEY, translate } from "../i18n";
import { LanguageContext, type LanguageContextValue } from './LanguageState';
export { LANGUAGE_OPTIONS };
export type Language = Locale;
export function LanguageProvider({ children }: { children: ReactNode }) {
    const [language, setLanguageState] = useState<Locale>(readLocale);
    setActiveLocale(language);
    const setLanguage = (value: Locale) => {
        const next = normalizeLocale(value);
        setActiveLocale(next);
        setLanguageState(next);
        try { localStorage.setItem(STORAGE_KEY, next); } catch { /* 저장할 수 없는 환경에서도 언어 전환은 유지한다. */ }
    };
    useEffect(() => {
        document.documentElement.lang = language;
        const sync = (event: StorageEvent) => {
            if (event.key === STORAGE_KEY) setLanguageState(normalizeLocale(event.newValue));
        };
        window.addEventListener('storage', sync);
        return () => window.removeEventListener('storage', sync);
    }, [language]);
    const value = useMemo<LanguageContextValue>(() => ({ language, setLanguage, t: (key, params) => translate(key, params, language) }), [language]);
    return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}
export function useLanguage() {
    const value = useContext(LanguageContext);
    if (!value) throw new Error("useLanguage must be used inside LanguageProvider");
    return value;
}
