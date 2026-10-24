import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const result = await build({
    stdin: {
        contents: "export * from './src/utils/downloads.ts'; export * from './src/utils/episodeSites.ts';",
        resolveDir: fileURLToPath(new URL('..', import.meta.url)),
        loader: 'ts',
    },
    bundle: true, write: false, platform: 'node', format: 'esm',
});
const { detectDownloadPlatform, normalizeDownloadInput, parseDownloadInputs, isEpisodeSource } =
    await import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);

const canonical = 'https://ym-05.com/videos/sample-video/';
for (const host of ['ym-05.com', 'www.ym-05.com']) {
    for (const scheme of ['http', 'https']) {
        const input = `${scheme}://${host}/videos/sample-video?ref=test#player`;
        assert.equal(detectDownloadPlatform(input), 'yamikorea');
        for (const selected of ['yamikorea', 'external']) {
            assert.deepEqual(normalizeDownloadInput(input, selected),
                {url: canonical, collection: false, source: 'yamikorea'});
        }
    }
}
assert.equal(isEpisodeSource('yamikorea'), false);
const batch = parseDownloadInputs(`${canonical}\nhttp://www.ym-05.com/videos/sample-video`, 'yamikorea');
assert.equal(batch.items.length, 1);
assert.equal(batch.items[0].collection, false);
assert.equal(batch.duplicates.length, 1);
for (const input of [
    'https://ym-06.com/videos/sample-video/', 'https://ym-05.com.evil/videos/sample-video/',
    'https://media.ym-05.com/videos/sample-video/', 'https://user:pass@ym-05.com/videos/sample-video/',
    'https://ym-05.com:8443/videos/sample-video/', 'ftp://ym-05.com/videos/sample-video/',
    'https://ym-05.com/', 'https://ym-05.com/videos/', 'https://ym-05.com/videos/a/b/',
    'https://ym-05.com/videos/%2Fbad/', 'https://ym-05.com/videos/%5Cbad/',
    'https://ym-05.com/videos/%00bad/', 'https://ym-05.com/videos/%20bad/',
    'https://ym-05.com/videos/%FF/', 'https://ym%2D05.com/videos/sample-video/',
    'https://ym-05.com/videos/%252fprivate/', 'https://ym-05.com/videos/%2525/',
]) {
    assert.equal(normalizeDownloadInput(input, 'yamikorea'), null, input);
    assert.notEqual(detectDownloadPlatform(input), 'yamikorea', input);
}
console.log('PASS: YamiKorea single-video source, direct queue inputs, canonical deduplication and invalid URL rejection');
