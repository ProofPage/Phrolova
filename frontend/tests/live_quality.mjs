import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/utils/liveQuality.ts", import.meta.url), "utf8");
const javascript = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { formatLiveResolution, liveQualityLabel } = await import(
    `data:text/javascript;base64,${Buffer.from(javascript).toString("base64")}`);

assert.equal(formatLiveResolution({ width: 1920, height: 1080, fps: 60 }), "1920×1080 · 60fps");
assert.equal(formatLiveResolution({ width: 1080, height: 1920, fps: 29.97 }), "1080×1920 · 29.97fps");
assert.equal(formatLiveResolution({ width: 1920, height: 1080 }), "1920×1080");
assert.equal(formatLiveResolution({ height: 720 }), "720p");
assert.equal(formatLiveResolution(null), "");
assert.equal(formatLiveResolution({ width: 0, height: NaN, fps: Infinity }), "");
assert.equal(liveQualityLabel({ value: "1080p60", label: "1080p60", width: 1920, height: 1080, fps: 60 }),
    "1080p60 · 1920×1080 · 60fps");
assert.equal(liveQualityLabel({ value: "source", label: "Source" }), "Source");
assert.equal(liveQualityLabel({ value: "origin", label: "ORIGIN · 1080×1920 · H.264", width: 1080, height: 1920, fps: 60 }),
    "ORIGIN · 1080×1920 · H.264 · 60fps");
console.log("PASS: actual dimensions/FPS, portrait and fractional rates, unknown metadata, quality option labels.");
