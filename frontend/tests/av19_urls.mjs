import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const result = await build({
    stdin: {
        contents: "export * from './src/utils/downloads.ts'; export * from './src/utils/episodeSites.ts'; export * from './src/utils/av19Urls.ts';",
        resolveDir: fileURLToPath(new URL('..', import.meta.url)),
        loader: 'ts',
    },
    bundle: true, write: false, platform: 'node', format: 'esm',
});
const { canonicalAV19VideoUrl, detectDownloadPlatform, normalizeDownloadInput, parseDownloadInputs, isEpisodeSource } =
    await import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);

assert.equal(isEpisodeSource('av19'), false);
for (const locale of ['de-DE', 'en-US', 'es-ES', 'ja-JP', 'ko-KR', 'ru-RU', 'zh-CN', 'zh-TW']) {
    const messages = JSON.parse(await readFile(new URL(`../src/i18n/locales/${locale}.json`, import.meta.url), 'utf8'));
    assert.equal(messages['platform.av19'], 'AV19');
}
for (const path of ['/korea/104856', '/bj/40043', '/nsub/152']) {
    const canonical = `https://av19t.com${path}`;
    for (const host of ['av19t.com', 'www.av19t.com', 'AV19T.COM']) {
        for (const scheme of ['http', 'https']) {
            const input = `${scheme}://${host}${path}/?ref=test#player`;
            assert.equal(canonicalAV19VideoUrl(input), canonical);
            assert.equal(detectDownloadPlatform(input), 'av19');
            for (const selected of ['av19', 'external']) {
                assert.deepEqual(normalizeDownloadInput(input, selected),
                    { url: canonical, collection: false, source: 'av19' });
            }
        }
    }
    for (const selected of ['av19', 'external']) {
        const batch = parseDownloadInputs(`${canonical}\nhttp://www.av19t.com${path}/?ref=test`, selected);
        assert.deepEqual(batch.items, [{ url: canonical, collection: false, source: 'av19' }]);
        assert.equal(batch.duplicates.length, 1);
        assert.deepEqual(batch.invalid, []);
    }
}
for (const path of [
    '/', '/korea', '/korea/', '/bj/', '/nsub/', '/unknown/152', '/korea/0',
    '/korea/-1', '/korea/1.5', '/korea/104856/extra', '/KOREA/104856',
    '/korea/%31', '/korea/1%2f2', '/korea/1%5c2', '/korea/%252f152',
    '/korea/%00', '/korea/%20', '/korea/%FF',
    '/other/../korea/104856', '/korea/1/../../bj/40043', '/korea/%2e%2e/bj/40043',
    '/korea/104856\n', '/korea/\t104856', '/korea/104856\\',
]) {
    const input = `https://av19t.com${path}`;
    assert.equal(canonicalAV19VideoUrl(input), null, input);
    for (const selected of ['av19', 'external']) {
        assert.equal(normalizeDownloadInput(input, selected), null, input);
    }
    assert.notEqual(detectDownloadPlatform(input), 'av19', input);
}
for (const input of [
    'https://av19.org/korea/104856', 'https://av19.gg/korea/104856',
    'https://av19a.com/korea/104856', 'https://av19t.com.evil/korea/104856',
    'https://media.av19t.com/korea/104856', 'https://av19t.com./korea/104856',
    'https://user:pass@av19t.com/korea/104856', 'https://@av19t.com/korea/104856',
    'https://av19t.com:8443/korea/104856', 'https://av19t.com:80/korea/104856',
    'http://av19t.com:443/korea/104856', 'ftp://av19t.com/korea/104856',
    'https://%61v19t.com/korea/104856', 'https://ａｖ19t.com/korea/104856',
]) {
    assert.equal(canonicalAV19VideoUrl(input), null, input);
    assert.equal(normalizeDownloadInput(input, 'av19'), null, input);
    assert.notEqual(detectDownloadPlatform(input), 'av19', input);
}
console.log('PASS: AV19 single-video queue, eight locale labels, strict URL validation and canonical deduplication');
