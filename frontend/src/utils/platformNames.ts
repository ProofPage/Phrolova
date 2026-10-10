/** Display text only: preserve identifiers, URLs and paths in diagnostics. */
export function localizePlatformNames(text: string): string {
    return text.replace(/(?<![\w./:@-])(?:CHZZK|Chzzk|YouTube|Youtube|SOOP|CIME)(?![\w./:@-])/g,
        name => ({ chzzk: '치지직', youtube: '유튜브', soop: '숲', cime: '씨미' })[name.toLowerCase()] ?? name);
}
