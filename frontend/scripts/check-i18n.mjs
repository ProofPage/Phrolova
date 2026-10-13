import fs from 'node:fs';
import path from 'node:path';
import ts from 'typescript';
import { fileURLToPath } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../src');
const locales = ['ko-KR','en-US','ja-JP','es-ES','de-DE','zh-CN','zh-TW','ru-RU'];
const failures = [];
const dictionaries = Object.fromEntries(locales.map(locale => {
    const raw = fs.readFileSync(path.join(root, 'i18n/locales', locale + '.json'), 'utf8');
    const properties = [...raw.matchAll(/^\s*"([^"\n]+)":/gm)].map(match => match[1]);
    if (new Set(properties).size !== properties.length) failures.push(`${locale}: duplicate keys`);
    return [locale, JSON.parse(raw)];
}));
const keys = Object.keys(dictionaries['ko-KR']);
const variables = text => [...new Set([...text.matchAll(/\{(\w+)\}/g)].map(match => match[1]))].sort().join(',');
for (const locale of locales) {
    const dictionary = dictionaries[locale];
    if (Object.keys(dictionary).sort().join('|') !== [...keys].sort().join('|')) failures.push(`${locale}: key set differs`);
    for (const key of keys) {
        if (typeof dictionary[key] !== 'string' || !dictionary[key].trim()) failures.push(`${locale}:${key}: empty translation`);
        else if (variables(dictionary[key]) !== variables(dictionaries['ko-KR'][key])) failures.push(`${locale}:${key}: variables differ`);
        if (/(?:spaces|chatLogs|saveChat)/i.test(key)) failures.push(`${locale}:${key}: removed feature`);
    }
}
function files(dir) { return fs.readdirSync(dir, {withFileTypes:true}).flatMap(entry => entry.isDirectory() ? files(path.join(dir,entry.name)) : [path.join(dir,entry.name)]); }
for (const file of files(root).filter(file => /\.tsx?$/.test(file) && !file.includes(`${path.sep}i18n${path.sep}`))) {
    const source = ts.createSourceFile(file, fs.readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true, file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    const where = node => `${path.relative(root,file)}:${source.getLineAndCharacterOfPosition(node.getStart(source)).line+1}`;
    function visit(node) {
        if (ts.isJsxText(node) && /[가-힣]/.test(node.text)) failures.push(`${where(node)}: hardcoded JSX text`);
        if (ts.isJsxAttribute(node) && ['title','aria-label','alt','placeholder'].includes(node.name.getText(source)) && node.initializer && ts.isStringLiteral(node.initializer) && /[가-힣]/.test(node.initializer.text)) failures.push(`${where(node)}: hardcoded accessible text`);
        if ((ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) && /^(common|live|download|settings|logs|stats|setup|platform|errors)\.[a-zA-Z]/.test(node.text) && !Object.hasOwn(dictionaries['ko-KR'],node.text) && !Object.hasOwn(dictionaries['ko-KR'],node.text+'.other')) failures.push(`${where(node)}: missing key ${node.text}`);
        ts.forEachChild(node, visit);
    }
    visit(source);
}
if (failures.length) { console.error(failures.join('\n')); process.exitCode = 1; }
else console.log(`PASS: ${keys.length} keys in each of ${locales.length} locales; matching variables, no empty/duplicate/missing keys or hardcoded JSX labels`);
