/**
 * Integration tests for the opencode plugin (dist/server.js) -> status files
 * that the desktop pet consumes.
 *
 * The plugin resolves PET_DIR from os.homedir(), so run with HOME/USERPROFILE
 * pointed at a throwaway directory:
 *
 *   HOME=$(mktemp -d) USERPROFILE=$HOME node tests/test_server_plugin.mjs
 */

import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const pluginPath = path.join(__dirname, "..", "dist", "server.js");
const { default: PetPlugin } = await import(pathToFileURL(pluginPath).href);

const PET_DIR = path.join(os.homedir(), ".opencode", "pet");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const statusFile = (id) =>
  path.join(PET_DIR, `status-${String(id).replace(/[^a-zA-Z0-9_-]/g, "_")}.json`);
const readStatus = (id) =>
  JSON.parse(fs.readFileSync(statusFile(id), "utf8"));

let passed = 0;
let failed = 0;
const results = [];
function t(name, fn) {
  return Promise.resolve()
    .then(fn)
    .then(() => {
      passed++;
      results.push(`  PASS  ${name}`);
    })
    .catch((err) => {
      failed++;
      results.push(`  FAIL  ${name}\n        ${err && err.message}`);
    });
}

const client = { session: { get: async () => ({ title: "My Project" }) } };

fs.rmSync(PET_DIR, { recursive: true, force: true });
fs.mkdirSync(PET_DIR, { recursive: true });
const plugin = await PetPlugin({ directory: "/tmp/proj", client });

await t("session.created writes idle status with title", async () => {
  await plugin.event({ event: { type: "session.created", properties: { sessionID: "s1" } } });
  const s = readStatus("s1");
  assert.equal(s.state, "idle");
  assert.equal(s.title, "My Project");
  assert.ok(s.updatedAt > 0);
});

await t("session.status busy updates state", async () => {
  await plugin.event({ event: { type: "session.status", properties: { sessionID: "s1", status: { type: "busy" } } } });
  assert.equal(readStatus("s1").state, "busy");
});

await t("session.status thinking updates state", async () => {
  await plugin.event({ event: { type: "session.status", properties: { sessionID: "s1", status: { type: "thinking" } } } });
  assert.equal(readStatus("s1").state, "thinking");
});

await t("message.part.updated -> busy with message", async () => {
  await plugin.event({ event: { type: "message.part.updated", properties: { sessionID: "s1", part: { type: "text", text: "  hello   world  " } } } });
  const s = readStatus("s1");
  assert.equal(s.state, "busy");
  assert.equal(s.message, "hello world");
});

await t("session.error sets error state", async () => {
  await plugin.event({ event: { type: "session.error", properties: { sessionID: "s1" } } });
  assert.equal(readStatus("s1").state, "error");
});

await t("session.idle after busy -> celebrating then idle", async () => {
  await plugin.event({ event: { type: "session.created", properties: { sessionID: "c1" } } });
  await plugin.event({ event: { type: "session.status", properties: { sessionID: "c1", status: { type: "busy" } } } });
  await plugin.event({ event: { type: "session.idle", properties: { sessionID: "c1" } } });
  assert.equal(readStatus("c1").state, "celebrating");
  await sleep(2300);
  assert.equal(readStatus("c1").state, "idle");
});

await t("session.idle after error does not celebrate", async () => {
  await plugin.event({ event: { type: "session.created", properties: { sessionID: "e1" } } });
  await plugin.event({ event: { type: "session.status", properties: { sessionID: "e1", status: { type: "busy" } } } });
  await plugin.event({ event: { type: "session.error", properties: { sessionID: "e1" } } });
  await plugin.event({ event: { type: "session.idle", properties: { sessionID: "e1" } } });
  assert.equal(readStatus("e1").state, "idle");
});

await t("session.idle after long work sequence celebrates", async () => {
  await plugin.event({ event: { type: "session.created", properties: { sessionID: "w1" } } });
  await plugin.event({ event: { type: "session.status", properties: { sessionID: "w1", status: { type: "busy" } } } });
  await plugin.event({ event: { type: "session.status", properties: { sessionID: "w1", status: { type: "thinking" } } } });
  await plugin.event({ event: { type: "message.part.updated", properties: { sessionID: "w1", part: { type: "text", text: "working..." } } } });
  await plugin.event({ event: { type: "session.idle", properties: { sessionID: "w1" } } });
  assert.equal(readStatus("w1").state, "celebrating");
});

await t("status-idle alone celebrates (no session.idle event)", async () => {
  await plugin.event({ event: { type: "session.created", properties: { sessionID: "s1" } } });
  await plugin.event({ event: { type: "session.status", properties: { sessionID: "s1", status: { type: "busy" } } } });
  await plugin.event({ event: { type: "session.status", properties: { sessionID: "s1", status: { type: "idle" } } } });
  assert.equal(readStatus("s1").state, "celebrating");
});

await t("status-idle then session.idle does not double-celebrate or stomp", async () => {
  await plugin.event({ event: { type: "session.created", properties: { sessionID: "d1" } } });
  await plugin.event({ event: { type: "session.status", properties: { sessionID: "d1", status: { type: "busy" } } } });
  await plugin.event({ event: { type: "session.status", properties: { sessionID: "d1", status: { type: "idle" } } } });
  await plugin.event({ event: { type: "session.idle", properties: { sessionID: "d1" } } });
  assert.equal(readStatus("d1").state, "celebrating", "session.idle stomped the celebration");
  await sleep(2300);
  assert.equal(readStatus("d1").state, "idle");
});

await t("duplicate status-idle does not stomp a live celebration", async () => {
  await plugin.event({ event: { type: "session.created", properties: { sessionID: "dup" } } });
  await plugin.event({ event: { type: "session.status", properties: { sessionID: "dup", status: { type: "busy" } } } });
  await plugin.event({ event: { type: "session.status", properties: { sessionID: "dup", status: { type: "idle" } } } });
  await plugin.event({ event: { type: "session.status", properties: { sessionID: "dup", status: { type: "idle" } } } });
  assert.equal(readStatus("dup").state, "celebrating",
    "duplicate status-idle cut the celebration short");
  await sleep(2300);
  assert.equal(readStatus("dup").state, "idle");
});

await t("work resuming during celebration is not flipped to idle by stale timer", async () => {
  await plugin.event({ event: { type: "session.created", properties: { sessionID: "res" } } });
  await plugin.event({ event: { type: "session.status", properties: { sessionID: "res", status: { type: "busy" } } } });
  await plugin.event({ event: { type: "session.idle", properties: { sessionID: "res" } } });
  assert.equal(readStatus("res").state, "celebrating");
  // work resumes inside the 2s celebration window
  await sleep(300);
  await plugin.event({ event: { type: "session.status", properties: { sessionID: "res", status: { type: "busy" } } } });
  await plugin.event({ event: { type: "message.part.updated", properties: { sessionID: "res", part: { type: "text", text: "more work" } } } });
  assert.equal(readStatus("res").state, "busy");
  await sleep(2300); // the old celebration timer fires in here
  assert.equal(readStatus("res").state, "busy",
    "stale celebration timer flipped an actively-working session to idle");
});

await t("tool.execute.before formats label and flips direction", async () => {
  const before = readStatus("s1").direction;
  await plugin["tool.execute.before"]({ sessionID: "s1", tool: "bash", args: { command: "ls -la /tmp" } });
  const s = readStatus("s1");
  assert.ok(s.toolLabel.includes("ls -la /tmp"));
  assert.notEqual(s.direction, before);
});

await t("tool label read uses basename", async () => {
  await plugin["tool.execute.before"]({ sessionID: "s1", tool: "read", args: { filePath: "/tmp/foo/bar.txt" } });
  assert.equal(readStatus("s1").toolLabel, "read bar.txt");
});

await t("tool.execute.before on idle session flips to busy", async () => {
  // fresh session is idle; a tool means work is happening NOW
  await plugin.event({ event: { type: "session.created", properties: { sessionID: "t2" } } });
  assert.equal(readStatus("t2").state, "idle");
  await plugin["tool.execute.before"]({ sessionID: "t2", tool: "bash", args: { command: "npm test" } });
  const s = readStatus("t2");
  assert.equal(s.state, "busy", "tool execution must not leave the session idle");
  assert.ok(s.toolLabel.includes("npm test"));
  // and a completion afterwards celebrates (it was genuinely working)
  await plugin.event({ event: { type: "session.idle", properties: { sessionID: "t2" } } });
  assert.equal(readStatus("t2").state, "celebrating");
  await sleep(2300);
  assert.equal(readStatus("t2").state, "idle");
});

await t("tool.execute.after does not flip busy back to idle", async () => {
  await plugin["tool.execute.before"]({ sessionID: "t3", tool: "grep", args: { pattern: "foo" } });
  assert.equal(readStatus("t3").state, "busy");
  await plugin["tool.execute.after"]({ sessionID: "t3" });
  assert.equal(readStatus("t3").state, "busy", "tool.execute.after must not stomp the working state");
});

await t("file names sanitize weird session ids", async () => {
  await plugin.event({ event: { type: "session.created", properties: { sessionID: "a/b c!d" } } });
  const s = readStatus("a_b_c_d");
  assert.equal(s.sessionID, "a/b c!d");
});

await t("message truncation to 120 chars", async () => {
  await plugin.event({ event: { type: "message.part.updated", properties: { sessionID: "s1", part: { type: "text", text: "x".repeat(500) } } } });
  assert.ok(readStatus("s1").message.length <= 120);
});

await t("session.deleted removes file", async () => {
  await plugin.event({ event: { type: "session.deleted", properties: { sessionID: "s1" } } });
  assert.equal(fs.existsSync(statusFile("s1")), false);
});

// --- killswitch ---
await t("disabled file short-circuits the plugin", async () => {
  fs.writeFileSync(path.join(PET_DIR, "disabled"), "");
  const p2 = await PetPlugin({ directory: "/tmp/proj", client });
  const before = fs.readdirSync(PET_DIR).filter((f) => f.startsWith("status-"));
  await p2.event({ event: { type: "session.created", properties: { sessionID: "k1" } } });
  const after = fs.readdirSync(PET_DIR).filter((f) => f.startsWith("status-"));
  assert.deepEqual(after, before, "disabled plugin must not write status files");
  fs.rmSync(path.join(PET_DIR, "disabled"));
});

// --- throttle: same state within 400ms must not rewrite the file ---
await t("write throttle skips unchanged state writes", async () => {
  await plugin.event({ event: { type: "session.created", properties: { sessionID: "th" } } });
  await plugin.event({ event: { type: "session.status", properties: { sessionID: "th", status: { type: "busy" } } } });
  const afterFirst = readStatus("th").updatedAt;
  await sleep(50);
  // duplicate identical busy event inside the 400ms window -> throttled
  await plugin.event({ event: { type: "session.status", properties: { sessionID: "th", status: { type: "busy" } } } });
  assert.equal(readStatus("th").updatedAt, afterFirst,
    "throttled duplicate write changed updatedAt");
  // after the window the rate limiter allows a rewrite — that keeps updatedAt
  // fresh, which the pet relies on for its 25s staleness detection.
  await sleep(500);
  await plugin.event({ event: { type: "session.status", properties: { sessionID: "th", status: { type: "busy" } } } });
  assert.ok(readStatus("th").updatedAt > afterFirst,
    "duplicate after the window must rewrite (min-interval rate limiter, not dedupe)");
});

await plugin.dispose();

console.log("\n=== server.js plugin contract tests ===");
console.log(results.join("\n"));
console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
