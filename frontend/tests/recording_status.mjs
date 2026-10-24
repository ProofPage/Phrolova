import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/utils/recordingStatus.ts", import.meta.url), "utf8");
const javascript = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { recordingPresentation: present, connectionEventLabel } = await import(
    `data:text/javascript;base64,${Buffer.from(javascript).toString("base64")}`);

const waiting = {
    retry_code: "stream_unavailable", retry_at: "2026-10-24T23:10:00",
    retry_blocked: false, last_error: "503 Service Unavailable",
    recording: { state: "error", is_recording: false, has_data: true, file_size_bytes: 1024 },
};
assert.deepEqual(present(waiting), { label: "live.serverRecoveryWait", tone: "neutral", recovering: true });
assert.equal(present({ ...waiting, retry_blocked: true }).tone, "danger");
assert.equal(present({ ...waiting, retry_at: null }).tone, "danger");
assert.equal(present({ ...waiting, retry_code: "connection" }).label, "live.waitingToReconnect");
assert.equal(present({ ...waiting, retry_code: "stream_closed" }).label, "live.streamClosedPending");
assert.equal(present({ ...waiting, retry_code: "authentication" }).tone, "danger");
assert.equal(present({ recording: { state: "completed", connection_stage: "receiving" } }).label, "live.recordingCompleted");
assert.equal(present({ recording: { state: "idle", connection_stage: "idle" } }).label, "live.waitingToRecord");
assert.equal(present({ recording: { state: "connecting" } }).label, "live.connectingToStream");
assert.equal(present({ recording: { state: "recording", is_recording: true } }).label, "live.recording");
assert.equal(present({ recording: { state: "stopping", is_recording: true } }).label, "live.stoppingRecording");
assert.equal(present(waiting, "stop").label, "live.stoppingRecording");
assert.equal(connectionEventLabel({ event: "receiving" }), "live.recordingStartedAt");
assert.equal(connectionEventLabel({ event: "interrupted", code: "stream_closed" }), "live.streamClosedPending");
assert.equal(connectionEventLabel({ event: "interrupted", code: "stream_unavailable" }), "live.serverRecoveryWait");
assert.equal(connectionEventLabel({ event: "interrupted", code: "storage" }), "live.recordingError");
console.log("PASS: recovery/blocked/authentication/idle/completed/stopping states and reception event labels.");
