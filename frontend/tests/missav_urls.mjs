import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const result = await build({
    stdin: {
        contents: "export * from './src/utils/downloads.ts'; export * from './src/utils/missavUrls.ts'; export * from './src/utils/episodeSites.ts';",
        resolveDir: fileURLToPath(new URL('..', import.meta.url)), loader: 'ts',
    },
    bundle: true, write: false, platform: 'node', format: 'esm',
});
const { canonicalMissAVVideoUrl, detectDownloadPlatform, normalizeDownloadInput, parseDownloadInputs, isEpisodeSource } =
    await import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);
const canonical = 'https://missav123.com/ko/example-123';
assert.equal(isEpisodeSource('missav'), false);
for (const locale of ['de-DE', 'en-US', 'es-ES', 'ja-JP', 'ko-KR', 'ru-RU', 'zh-CN', 'zh-TW']) {
    const messages = JSON.parse(await readFile(new URL(`../src/i18n/locales/${locale}.json`, import.meta.url), 'utf8'));
    assert.equal(messages['platform.missav'], 'MissAV');
}
for (const host of ['missav123.com', 'www.missav123.com', 'MISSAV123.COM']) {
    for (const scheme of ['http', 'https']) {
        const input = `${scheme}://${host}/ko/example-123/?ref=test#player`;
        assert.equal(canonicalMissAVVideoUrl(input), canonical);
        assert.equal(detectDownloadPlatform(input), 'missav');
        for (const source of ['missav', 'external']) {
            assert.deepEqual(normalizeDownloadInput(input, source), { url: canonical, collection: false, source: 'missav' });
        }
    }
}
for (const source of ['missav', 'external']) {
    const batch = parseDownloadInputs(`${canonical}\nhttp://www.missav123.com/ko/example-123/?ref=test`, source);
    assert.deepEqual(batch.items, [{ url: canonical, collection: false, source: 'missav' }]);
    assert.equal(batch.duplicates.length, 1);
    assert.deepEqual(batch.invalid, []);
}
// Syntax only: prepare must verify main-player presence before treating a page as a video.
for (const slug of ['actors', 'search', 'genres', 'Example-123']) {
    const url = `https://missav123.com/ko/${slug}`;
    assert.equal(canonicalMissAVVideoUrl(url), url);
    assert.equal(detectDownloadPlatform(url), 'missav');
    for (const source of ['missav', 'external']) {
        assert.deepEqual(normalizeDownloadInput(url, source), { url, collection: false, source: 'missav' });
    }
}
for (const path of [
    '/', '/dm270/ko', '/ko', '/ko/',
    '/en/example-123', '/KO/example-123', '/ko/example-123/extra',
    '/other/../ko/example-123', '/ko/%2e%2e/example-123', '/ko/..',
    '/ko/example%2f123', '/ko/example%252f123', '/ko/example%5c123',
    '/ko/example-123\n', '/ko/ex\tample-123', '/ko/example-123\\',
]) {
    const input = `https://missav123.com${path}`;
    assert.equal(canonicalMissAVVideoUrl(input), null, input);
    assert.notEqual(detectDownloadPlatform(input), 'missav', input);
    for (const source of ['missav', 'external']) assert.equal(normalizeDownloadInput(input, source), null, input);
}
for (const authority of [
    'missav.com', 'missav.live', 'missav.ws', 'missav.ai', 'missav123.com.evil',
    'media.missav123.com', 'missav123.com.', 'user:pass@missav123.com', '@missav123.com',
    'missav123.com:443', 'missav123.com:80', 'missav123.com:8443', '%6dissav123.com',
    'ｍissav123.com',
]) {
    const input = `https://${authority}/ko/example-123`;
    assert.equal(canonicalMissAVVideoUrl(input), null, input);
    assert.equal(normalizeDownloadInput(input, 'missav'), null, input);
    assert.notEqual(detectDownloadPlatform(input), 'missav', input);
}
assert.equal(canonicalMissAVVideoUrl('ftp://missav123.com/ko/example-123'), null);
console.log('PASS: MissAV single-video queue, eight locale labels, strict URL validation and canonical deduplication');
