import { getActiveLocale } from '../i18n';
/** 표시 이름만 바꾸고 ID, URL, 경로는 보존한다. */
export function localizePlatformNames(text: string): string {
    const korean = getActiveLocale() === 'ko-KR';
    if (!korean) return text.replace(/(?<![\w./:@-])(?:치지직|유튜브|숲|씨미)(?![\w./:@-])/g,
        name => ({ '치지직': 'CHZZK', '유튜브': 'YouTube', '숲': 'SOOP', '씨미': 'CIME' })[name] ?? name);
    return text.replace(/(?<![\w./:@-])(?:CHZZK|Chzzk|YouTube|Youtube|SOOP|CIME)(?![\w./:@-])/g,
        name => ({ chzzk: '치지직', youtube: '유튜브', soop: '숲', cime: '씨미' })[name.toLowerCase()] ?? name);
}
