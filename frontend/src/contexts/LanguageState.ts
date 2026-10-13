import { createContext } from 'react';
import type { Locale, MessageParams } from '../i18n';

export interface LanguageContextValue {
    language: Locale;
    setLanguage: (language: Locale) => void;
    t: (key: string, params?: MessageParams) => string;
}

// 번역 리소스가 자동 갱신되어도 Provider와 소비자가 같은 Context를 참조해야 한다.
// 런타임 번역 모듈에서 분리하여 리소스 변경이 Context를 다시 만들지 않게 한다.
export const LanguageContext = createContext<LanguageContextValue | null>(null);
