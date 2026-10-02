// Offline browser orchestration checks. No HTTP server, upload or model runs.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");

const root = path.resolve(__dirname, "..");
const markup = fs.readFileSync(path.join(root, "frontend/index.html"), "utf8");
const source = fs.readFileSync(path.join(root, "frontend/video-batches.js"), "utf8");
const plain = value => JSON.parse(JSON.stringify(value));

function harness(respond) {
  const elements = new Map(), events = new Map(), calls = [];
  const defaults = {name: "offline", mode: "spatial", temporalMode: "spatial", spatialTarget: "foreground", promptSource: "ai", keepAudio: true};
  function element(id, tag = "div", type = "") {
    if (elements.has(id)) return elements.get(id);
    const classes = new Set();
    const node = {id, tag, type, value: "", checked: false, disabled: false, hidden: false, textContent: "", dataset: {}, style: {}, files: [],
      classList: {add: value => classes.add(value), remove: value => classes.delete(value), toggle(value, force) {
        const active = force === undefined ? !classes.has(value) : force;
        if (active) classes.add(value); else classes.delete(value);
      }},
      addEventListener() {}, removeAttribute(name) { delete this[name]; }, setAttribute(name, value) { this[name] = value; },
      querySelector() { return this.label || (this.label = {textContent: ""}); },
      querySelectorAll() { return [...elements.values()].filter(item => ["input", "select", "textarea", "button"].includes(item.tag)); },
      contains() { return true; }, click() {}, replaceChildren() {},
    };
    Object.defineProperty(node, "innerHTML", {get() { return this._html || ""; }, set(value) { this._html = value; register(value); }});
    elements.set(id, node);
    return node;
  }
  function register(html) {
    for (const match of html.matchAll(/<(\w+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
      const node = element(match[3], match[1], /\btype="([^"]+)"/.exec(match[2])?.[1] || "");
      if (/\bhidden(?:\s|$)/.test(match[2])) node.hidden = true;
    }
  }
  register(markup);
  const $ = id => { assert.ok(elements.has(id), `Missing DOM element: ${id}`); return elements.get(id); };
  $("flowInputMode").value = "batch";
  $("flowPromptSource").value = "ai";
  $("batchMaterialSource").value = "directories";
  const storage = () => { const values = new Map(); return {getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value)}; };
  const document = {getElementById: $, createElement: tag => element(`anonymous-${elements.size}`, tag),
    addEventListener: (name, listener) => { if (!events.has(name)) events.set(name, []); events.get(name).push(listener); },
    dispatchEvent: event => { for (const listener of events.get(event.type) || []) listener(event); }};
  const window = {addEventListener() {}, VideoFlowUI: {getDefaults: () => ({...defaults}), uploadsPending: () => 0, updateCreateFields() {}, showCreate() {}, openFlow: async () => {}}};
  const context = {window, document, location: {href: "http://workbench.local/", origin: "http://workbench.local"},
    localStorage: storage(), sessionStorage: storage(), URL, Blob, console,
    CustomEvent: class { constructor(type, options = {}) { this.type = type; this.detail = options.detail; } },
    setTimeout: () => 1, clearTimeout() {}, bindDropzone() {}, renderStackList() {},
    fetch: async (url, options = {}) => {
      const body = options.headers?.["Content-Type"] === "application/json" ? JSON.parse(options.body) : options.body;
      const call = {url, body, options}; calls.push(call);
      const result = await respond(call, {calls, defaults, $, api: context.__batch});
      return {ok: result?.ok !== false, status: result?.status || 200, json: async () => result?.data ?? result};
    },
  };
  vm.createContext(context);
  const instrumented = source.replace(/\}\)\(\);\s*$/, "globalThis.__batch = {state, parseCsv, scanPayload, creationFingerprint, scanMaterials, uploadRows, createBatch, refreshBatch, chooseFiles, batchAction};\n})();");
  vm.runInContext(instrumented, context, {filename: "video-batches.js"});
  $("batchDir-videos").value = "/data/videos";
  $("batchDir-references").value = "/data/references";
  return {api: context.__batch, $, defaults, calls, submit: () => context.__batch.createBatch({preventDefault() {}})};
}

function scanResult(count = 2) {
  return {summary: {total: count, ready: count, blocked: 0}, matches: Array.from({length: count}, (_, i) => ({
    index: i + 1, matchKey: String(i + 1), canCreate: true, requiresUpload: false, issues: [], row: {name: `group-${i + 1}`},
    assets: {videoPath: {id: `v:${i}`, name: `${i + 1}.mp4`, path: `/videos/${i + 1}.mp4`}, referenceImagePath: {id: `r:${i}`, name: `${i + 1}.png`, path: `/images/${i + 1}.png`}},
  }))};
}
function batch(status = "draft", total = 2) {
  return {id: "abc123", name: "offline", mode: "spatial", status, total, completed: 0, failed: 0, pending: total,
    rows: Array.from({length: total}, (_, index) => ({index: index + 1, name: `group-${index + 1}`, status: "pending"})),
    logUrl: "/api/video-batches/abc123/logs", logDownloadUrl: "/api/video-batches/abc123/logs.txt"};
}

test("one click scans all groups, creates once and starts with the same batch ID", async () => {
  const h = harness(({url, body}, {$}) => {
    assert.equal($("flowMode").disabled, true, "settings stay frozen through submission");
    if (url.endsWith("/scan")) return scanResult();
    if (url === "/api/video-batches") { assert.equal(body.rows.length, 2); return {batch: batch()}; }
    if (url.endsWith("/run")) return {batch: batch("running")};
    throw new Error(`Unexpected request: ${url}`);
  });
  await h.submit();
  assert.deepEqual(h.calls.map(call => call.url), ["/api/video-batches/scan", "/api/video-batches", "/api/video-batches/abc123/run"]);
  assert.equal(h.api.state.batch.status, "running");
  assert.equal(h.$("flowMode").disabled, false);
  assert.equal(h.api.state.preparing, false);
});

test("one blocked group prevents every upload, create and run", async () => {
  const scan = scanResult();
  scan.matches[1].canCreate = false; scan.matches[1].issues = [{message: "缺少主参考图"}]; scan.summary.blocked = 1;
  const h = harness(() => scan);
  await h.submit();
  assert.deepEqual(h.calls.map(call => call.url), ["/api/video-batches/scan"]);
  assert.match(h.$("batchScanErrors").textContent, /缺少主参考图/);
  assert.equal(h.api.state.batch, null);
  assert.equal(h.$("flowCreateBtn").disabled, false);
});

test("browser upload reuses shared assets and places server paths in every created row", async () => {
  let upload = 0;
  const h = harness(({url, body}, {api}) => {
    if (url.endsWith("/scan")) {
      const scan = scanResult();
      scan.matches.forEach((match, i) => { match.assets = {videoPath: api.state.files.videos[i], referenceImagePath: api.state.files.references[0]}; match.requiresUpload = true; });
      return scan;
    }
    if (url === "/api/comfy/upload") return {path: `/uploads/${++upload}-${body.name}`};
    if (url === "/api/video-batches") {
      assert.equal(body.rows[0].referenceImagePath, body.rows[1].referenceImagePath);
      assert.notEqual(body.rows[0].videoPath, body.rows[1].videoPath);
      assert.ok(body.rows.every(row => row.videoPath.startsWith("/uploads/") && row.referenceImagePath.startsWith("/uploads/")));
      return {batch: batch()};
    }
    if (url.endsWith("/run")) return {batch: batch("running")};
    throw new Error(`Unexpected request: ${url}`);
  });
  h.$("batchMaterialSource").value = "files";
  h.api.chooseFiles("videos", [{name: "a.mp4", size: 10}, {name: "b.mp4", size: 20}]);
  h.api.chooseFiles("references", [{name: "a.png", size: 5}]);
  await h.submit();
  assert.equal(upload, 3);
  assert.equal(h.api.state.batch.status, "running");
});

test("failed start keeps saved batch available for continue without recreating it", async () => {
  let attempts = 0;
  const h = harness(({url}) => {
    if (url.endsWith("/scan")) return scanResult();
    if (url === "/api/video-batches") return {batch: batch()};
    if (url.endsWith("/run")) return ++attempts === 1 ? {ok: false, status: 400, data: {error: "已有批次运行"}} : {batch: batch("running")};
    throw new Error(`Unexpected request: ${url}`);
  });
  await h.submit();
  assert.equal(h.api.state.batch.id, "abc123");
  assert.equal(h.api.state.visible, true);
  assert.equal(h.$("batchRunBtn").disabled, false);
  assert.match(h.$("flowNotice").textContent, /已有批次运行/);
  await h.api.batchAction("run", {retryFailed: false});
  assert.equal(h.calls.filter(call => call.url === "/api/video-batches").length, 1);
  assert.equal(h.api.state.batch.status, "running");
});

test("failed upload creates nothing and a retry reuses only unchanged successful uploads", async () => {
  let failReference = true;
  const h = harness(({url, body}, {api}) => {
    if (url.endsWith("/scan")) {
      const scan = scanResult(1);
      scan.matches[0].assets = {videoPath: api.state.files.videos[0], referenceImagePath: api.state.files.references[0]};
      return scan;
    }
    if (url === "/api/comfy/upload") {
      if (body.name.endsWith(".png") && failReference) return {ok: false, data: {error: "上传中断"}};
      return {path: `/uploads/${body.name}`};
    }
    if (url === "/api/video-batches") return {batch: batch("draft", 1)};
    if (url.endsWith("/run")) return {batch: batch("running", 1)};
    throw new Error(`Unexpected request: ${url}`);
  });
  h.$("batchMaterialSource").value = "files";
  h.api.chooseFiles("videos", [{name: "a.mp4", size: 10}]);
  h.api.chooseFiles("references", [{name: "a.png", size: 5}]);
  await h.submit();
  assert.equal(h.api.state.batch, null);
  assert.equal(h.calls.filter(call => call.url === "/api/video-batches").length, 0);
  assert.equal(h.api.state.uploaded.size, 1);
  failReference = false;
  await h.submit();
  assert.equal(h.calls.filter(call => call.url === "/api/comfy/upload" && call.body.name === "a.mp4").length, 1);
  assert.equal(h.api.state.batch.status, "running");
  const previousId = h.api.state.files.videos[0].id;
  h.api.chooseFiles("videos", [{name: "a.mp4", size: 11}]);
  assert.notEqual(h.api.state.files.videos[0].id, previousId);
  assert.equal(h.api.state.uploaded.has(previousId), false);
});

test("changed input snapshot is rejected before create", async () => {
  const h = harness((_call, {defaults}) => { defaults.spatialTarget = "background"; return scanResult(); });
  await h.submit();
  assert.equal(h.calls.length, 1);
  assert.equal(h.api.state.batch, null);
  assert.match(h.$("flowNotice").textContent, /改变/);
});

test("CSV supports actual material counts above 500 and quoted fields", () => {
  const h = harness(() => { throw new Error("No request expected"); });
  const csv = "name,videoPath,referenceImagePath\n" + Array.from({length: 501}, (_, i) => `"group, ${i}",/v/${i}.mp4,/i/${i}.png`).join("\n");
  const result = h.api.parseCsv(csv);
  assert.equal(result.rows.length, 501);
  assert.equal(result.rows[0].values.name, "group, 0");
});

test("unused temporal directories are omitted after switching to spatial mode", () => {
  const h = harness(() => { throw new Error("No request expected"); });
  h.$("batchDir-endImages").value = "/old/tails";
  h.defaults.mode = "mixed"; h.defaults.temporalMode = "suffix";
  assert.equal(h.api.scanPayload().directories.endImages, "/old/tails");
  h.defaults.mode = "spatial";
  assert.equal(h.api.scanPayload().directories.endImages, "");
});

test("refresh reads cumulative batch logs and exposes full download", async () => {
  const saved = {...batch("running"), jobId: "last-job"};
  const h = harness(({url}) => {
    if (url.endsWith("/logs")) return {logs: ["first attempt", "retry attempt"]};
    if (url === "/api/video-batches/abc123") return {batch: saved};
    throw new Error(`Unexpected request: ${url}`);
  });
  h.api.state.batch = saved; h.api.state.visible = true;
  await h.api.refreshBatch();
  assert.match(h.$("batchLogs").textContent, /first attempt\nretry attempt/);
  assert.equal(h.$("batchLogDownload").hidden, false);
  assert.ok(h.$("batchLogDownload").href.endsWith("/logs.txt"));
});
