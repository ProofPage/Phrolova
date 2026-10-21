import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

const source = await readFile(new URL('../src/utils/episodeSites.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
});
const { parseEpisodeInput, episodeSourceForHost, isEpisodeSource } =
    await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);

assert.equal(episodeSourceForHost('tvroom42.org'), 'tvroom');
assert.equal(episodeSourceForHost('tvroom42.org.evil'), undefined);
assert.equal(isEpisodeSource('tvroom'), true);
for (const host of ['tvroom42.org', 'tvroom43.org']) {
    const work = `https://${host}/video/${encodeURIComponent('표류일기-1997')}`;
    assert.deepEqual(parseEpisodeInput(work), { url: work, collection: true, source: 'tvroom' });
    const episode = `${work}/${encodeURIComponent('본편')}`;
    assert.deepEqual(parseEpisodeInput(episode), { url: episode, collection: false, source: 'tvroom' });
}
for (const value of [
    'https://tvroom42.org/video/영화', 'https://tvroom42.org/video/a/b/c',
    'https://tvroom42.org/video/a/%2Fbad', 'https://tvroom42.org/video/a/%5Cbad',
    'https://tvroom42.org.evil/video/a/b', 'http://tvroom42.org/video/a/b',
    'https://user:pass@tvroom42.org/video/a/b',
]) assert.equal(parseEpisodeInput(value), null, value);
console.log('PASS: TVRoom work/episode recognition, rotated hosts and invalid URL rejection');
