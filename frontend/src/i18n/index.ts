import ru from './locales/ru-RU.json';
import tw from './locales/zh-TW.json';
import cn from './locales/zh-CN.json';
import de from './locales/de-DE.json';
import es from './locales/es-ES.json';
import ko from './locales/ko-KR.json';
import en from './locales/en-US.json';
import ja from './locales/ja-JP.json';
import aliases from './aliases.json';

export const LOCALES = ['ko-KR', 'en-US', 'ja-JP', 'es-ES', 'de-DE', 'zh-CN', 'zh-TW', 'ru-RU'] as const;
export type Locale = typeof LOCALES[number];
export type MessageParams = Record<string, string | number>;
export const LANGUAGE_OPTIONS: { value: Locale; label: string }[] = [
    { value: 'ko-KR', label: '한국어' }, { value: 'en-US', label: 'English' },
    { value: 'ja-JP', label: '日本語' }, { value: 'es-ES', label: 'Español' },
    { value: 'de-DE', label: 'Deutsch' }, { value: 'zh-CN', label: '简体中文' },
    { value: 'zh-TW', label: '繁體中文' }, { value: 'ru-RU', label: 'Русский' },
];
const dictionaries: Record<Locale, Record<string, string>> = {
    'ko-KR': ko, 'en-US': en, 'ja-JP': ja,
    'es-ES': es, 'de-DE': de, 'zh-CN': cn, 'zh-TW': tw, 'ru-RU': ru,
};
const sourceKeys: Record<string, string> = aliases;
// 알림 내역처럼 이전 언어로 저장된 표시값도 언어를 바꿀 때 다시 현지화한다.
const translatedKeys = new Map<string, string>();
const templates: { key: string; names: string[]; pattern: RegExp }[] = [];
for (const dictionary of Object.values(dictionaries)) {
    for (const [key, text] of Object.entries(dictionary)) {
        if (!translatedKeys.has(text)) translatedKeys.set(text, key);
        const names: string[] = [];
        const parts = text.split(/(\{\w+\})/g).map(part => {
            const name = part.match(/^\{(\w+)\}$/)?.[1];
            if (name) { names.push(name); return '(.+?)'; }
            return part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        });
        if (names.length) templates.push({key, names, pattern: new RegExp(`^${parts.join('')}$`, 's')});
    }
}
const missing = new Set<string>();
let activeLocale: Locale = 'ko-KR';
export const STORAGE_KEY = 'phrolova-language';

export function normalizeLocale(value: unknown): Locale {
    const old: Record<string, Locale> = { ko: 'ko-KR', en: 'en-US', ja: 'ja-JP' };
    if (typeof value !== 'string') return 'ko-KR';
    return old[value] ?? LOCALES.find(locale => locale.toLowerCase() === value.toLowerCase()) ?? 'ko-KR';
}
export function readLocale(): Locale {
    try { return normalizeLocale(localStorage.getItem(STORAGE_KEY)); } catch { return 'ko-KR'; }
}
export function setActiveLocale(locale: Locale) { activeLocale = locale; }
export function getActiveLocale(): Locale { return activeLocale; }
export function getMissingTranslations(): string[] { return [...missing]; }

/** 기존 상태값과 API 문구는 보존하고 표시할 때만 의미 키에 대응시킨다. */
export function messageKey(text: string): string | undefined {
    if (Object.hasOwn(ko, text)) return text;
    return sourceKeys[text] ?? translatedKeys.get(text);
}
export function translate(text: string, params?: MessageParams, locale = activeLocale): string {
    let key = messageKey(text);
    if (!key) {
        for (const template of templates) {
            const match = template.pattern.exec(text);
            if (!match) continue;
            key = template.key;
            params = Object.fromEntries(template.names.map((name, i) => [name, match[i + 1]]));
            break;
        }
    }
    if (!key) {
        if (/^(?:common|live|download|settings|setup|logs|stats|platform|errors)\.[A-Za-z]/.test(text)) {
            const id = `${locale}:${text}`;
            if (!missing.has(id)) { missing.add(id); console.warn(`[i18n] Missing ${id}`); }
            return dictionaries[locale]['common.textUnavailable'] ?? ko['common.textUnavailable'];
        }
        return text;
    }
    let output = dictionaries[locale][key];
    if (!output) {
        const id = `${locale}:${key}`;
        if (!missing.has(id)) { missing.add(id); console.warn(`[i18n] Missing ${id}`); }
        output = ko[key as keyof typeof ko] ?? text;
    }
    if (params) output = output.replace(/\{([\w]+)\}/g, (token, name: string) =>
        Object.hasOwn(params, name) ? typeof params[name] === 'number' ? formatNumber(params[name] as number, {}, locale) : String(params[name]) : token);
    return output;
}
export function formatNumber(value: number, options: Intl.NumberFormatOptions = {}, locale = activeLocale): string {
    return new Intl.NumberFormat(locale, options).format(Number.isFinite(value) ? value : 0);
}
export function formatDateTime(value: string | Date, options: Intl.DateTimeFormatOptions = {}, locale = activeLocale): string {
    const date = value instanceof Date ? value : new Date(value);
    return Number.isNaN(date.getTime()) ? '—' : new Intl.DateTimeFormat(locale, options).format(date);
}
export function pluralCategory(count: number, locale = activeLocale): Intl.LDMLPluralRule {
    return new Intl.PluralRules(locale).select(count);
}
export function translatePlural(key: string, count: number, params: MessageParams = {}, locale = activeLocale): string {
    const category = pluralCategory(count, locale);
    const variant = `${key}.${category}`;
    return translate(Object.hasOwn(dictionaries[locale], variant) ? variant : `${key}.other`, { ...params, count }, locale);
}
