import { getActiveLocale } from '../i18n';
/** 표시 이름만 바꾸고 ID, URL, 경로는 보존한다. */
export function localizePlatformNames(text: string): string {
    const korean = getActiveLocale() === 'ko-KR';
    if (!korean) return text.replace(/(?<![\w./:@-])(?:치지직|유튜브|씨미|킥|빌리빌리)(?![\w./:@-])/g,
        name => ({ '치지직': 'CHZZK', '유튜브': 'YouTube', '씨미': 'CIME', '킥': 'Kick', '빌리빌리': 'Bilibili' })[name] ?? name);
    return text.replace(/(?<![\w./:@-])(?:CHZZK|Chzzk|YouTube|Youtube|CIME|Kick|Bilibili)(?![\w./:@-])/g,
        name => ({ chzzk: '치지직', youtube: '유튜브', cime: '씨미', kick: '킥', bilibili: '빌리빌리' })[name.toLowerCase()] ?? name);
}
