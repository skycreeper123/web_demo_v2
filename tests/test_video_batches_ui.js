// Offline browser orchestration checks. No HTTP server, upload or model runs.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");

const root = path.resolve(__dirname, "..");
const markup = fs.readFileSync(path.join(root, "frontend/index.html"), "utf8");
const source = fs.readFileSync(path.join(root, "frontend/video-batches.js"), "utf8");
const flowSource = fs.readFileSync(path.join(root, "frontend/video-flows.js"), "utf8");
const plain = value => JSON.parse(JSON.stringify(value));

function harness(respond, options = {}) {
  const elements = new Map(), events = new Map(), calls = [], downloads = [];
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
      querySelectorAll() { return this.id === "flowCreateForm" ? [...elements.values()].filter(item => ["input", "select", "textarea", "button"].includes(item.tag) && !["flowNewBtn", "batchNewBtn"].includes(item.id)) : []; },
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
      const value = /\bvalue="([^"]*)"/.exec(match[2]);
      if (value) node.value = value[1];
    }
    for (const select of html.matchAll(/<select\b[^>]*id="([^"]+)"[^>]*>([\s\S]*?)<\/select>/g)) {
      const options = [...select[2].matchAll(/<option\b([^>]*)>/g)];
      const selected = options.find(option => /\bselected\b/.test(option[1])) || options[0];
      if (selected) element(select[1]).value = /\bvalue="([^"]*)"/.exec(selected[1])?.[1] || "";
    }
  }
  register(markup);
  const $ = id => { assert.ok(elements.has(id), `Missing DOM element: ${id}`); return elements.get(id); };
  $("flowInputMode").value = "batch";
  $("flowPromptSource").value = "ai";
  $("batchMaterialSource").value = "directories";
  const storage = () => { const values = new Map(); return {getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value)}; };
  const document = {getElementById: $, querySelectorAll: () => [], createElement: tag => element(`anonymous-${elements.size}`, tag),
    addEventListener: (name, listener) => { if (!events.has(name)) events.set(name, []); events.get(name).push(listener); },
    dispatchEvent: event => { for (const listener of events.get(event.type) || []) listener(event); }};
  const window = {addEventListener() {}, VideoFlowUI: {getDefaults: () => ({...defaults}), uploadsPending: () => 0, updateCreateFields() {}, showCreate() {}, openFlow: async () => {}}};
  window.location = {href: "http://workbench.local/", origin: "http://workbench.local"};
  class TestURL extends URL { static createObjectURL(blob) { downloads.push(blob); return `blob:offline-${downloads.length}`; } static revokeObjectURL() {} }
  const context = {window, document, location: {href: "http://workbench.local/", origin: "http://workbench.local"},
    localStorage: storage(), sessionStorage: storage(), URL: TestURL, Blob, console,
    CustomEvent: class { constructor(type, options = {}) { this.type = type; this.detail = options.detail; } },
    setTimeout: () => 1, clearTimeout() {}, bindDropzone() {}, renderStackList() {},
    fetch: async (url, options = {}) => {
      const body = options.headers?.["Content-Type"] === "application/json" ? JSON.parse(options.body) : options.body;
      const call = {url, body, options}; calls.push(call);
      const result = await respond(call, {calls, defaults, $, api: context.__batch});
      return {ok: result?.ok !== false, status: result?.status || 200, json: async () => result?.data ?? result};
    },
  };
  if (options.draft) context.sessionStorage.setItem("video-batches:create-draft", JSON.stringify(options.draft));
  vm.createContext(context);
  if (options.realFlows) {
    const instrumentedFlows = flowSource.replace(/\}\)\(\);\s*$/, "globalThis.__flow = {flowState, createDefaults, updateCreateFields, createFlow, renderInputs, renderFlow};\n})();");
    vm.runInContext(instrumentedFlows, context, {filename: "video-flows.js"});
  }
  const instrumented = source.replace(/\}\)\(\);\s*$/, "globalThis.__batch = {state, parseCsv, validateRows, validateTiming, scanPayload, creationFingerprint, scanMaterials, uploadRows, createBatch, refreshBatch, chooseFiles, batchAction, templateDownload};\n})();");
  vm.runInContext(instrumented, context, {filename: "video-batches.js"});
  $("batchDir-videos").value = "/data/videos";
  $("batchDir-references").value = "/data/references";
  return {api: context.__batch, flowApi: context.__flow, $, defaults, calls, downloads, submit: () => context.__batch.createBatch({preventDefault() {}})};
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

test("new temporal forms default to 30 percent and disable hidden timing controls", () => {
  const h = harness(() => { throw new Error("No request expected"); }, {realFlows: true});
  for (const mode of ["prefix", "suffix", "mixed"]) {
    h.$("flowMode").value = mode;
    h.$("flowTemporalMode").value = "suffix";
    h.$("flowInputMode").value = "single";
    h.flowApi.updateCreateFields();
    const defaults = h.flowApi.createDefaults();
    assert.equal(defaults.cutMode, "percent");
    assert.equal(defaults.replacePercent, 30);
    assert.equal(defaults.cutSeconds, null);
    assert.equal(h.$("flowReplacePercent").required, true);
    assert.equal(h.$("flowCutSeconds").disabled, true);
    assert.equal(h.$("flowCutSeconds").required, false);
    assert.equal(h.$("flowSecondsField").hidden, true);
  }
  assert.match(h.$("flowPercentHint").textContent, /最后 30%/);
  h.$("flowMode").value = "spatial";
  h.flowApi.updateCreateFields();
  assert.equal(h.$("flowCutField").hidden, true);
  assert.equal(h.$("flowCutMode").disabled, true);
  assert.equal(h.$("flowReplacePercent").disabled, true);
  assert.equal(h.$("flowReplacePercent").required, false);
});

test("switching to seconds preserves values but submits only the active timing field", () => {
  const h = harness(() => { throw new Error("No request expected"); }, {realFlows: true});
  h.$("flowMode").value = "prefix"; h.$("flowInputMode").value = "single";
  h.$("flowCutMode").value = "seconds"; h.$("flowCutSeconds").value = "4.5";
  h.flowApi.updateCreateFields();
  assert.equal(h.$("flowPercentField").hidden, true);
  assert.equal(h.$("flowReplacePercent").disabled, true);
  assert.equal(h.$("flowReplacePercent").required, false);
  assert.equal(h.$("flowCutSeconds").required, true);
  assert.equal(h.flowApi.createDefaults().cutSeconds, 4.5);
  assert.equal(h.flowApi.createDefaults().replacePercent, null);
  h.$("flowCutMode").value = "percent";
  h.flowApi.updateCreateFields();
  assert.equal(h.flowApi.createDefaults().replacePercent, 30);
  assert.equal(h.flowApi.createDefaults().cutSeconds, null);
  assert.equal(h.$("flowCutSeconds").value, "4.5");
});

test("legacy browser drafts without a timing mode retain their seconds meaning", () => {
  const h = harness(() => { throw new Error("No request expected"); }, {realFlows: true, draft: {flowMode: "suffix", flowCutSeconds: "3.5"}});
  assert.equal(h.$("flowCutMode").value, "seconds");
  assert.equal(h.flowApi.createDefaults().cutSeconds, 3.5);
  assert.equal(h.flowApi.createDefaults().replacePercent, null);
});

test("saved percentage drafts restore their percentage without reverting to seconds", () => {
  const h = harness(() => { throw new Error("No request expected"); }, {realFlows: true, draft: {flowMode: "prefix", flowCutMode: "percent", flowReplacePercent: "42.5", flowCutSeconds: "8"}});
  assert.equal(h.flowApi.createDefaults().cutMode, "percent");
  assert.equal(h.flowApi.createDefaults().replacePercent, 42.5);
  assert.equal(h.flowApi.createDefaults().cutSeconds, null);
});

test("invalid single-flow percentages are rejected before sending a request", async () => {
  const h = harness(() => { throw new Error("No request expected"); }, {realFlows: true});
  h.$("flowMode").value = "prefix"; h.$("flowInputMode").value = "single";
  for (const value of ["", "0", "100", "-1", "101", "not-a-number", "Infinity"]) {
    h.$("flowReplacePercent").value = value;
    await h.flowApi.createFlow({preventDefault() {}});
    assert.match(h.$("flowNotice").textContent, /大于 0、小于 100/);
  }
  assert.equal(h.calls.length, 0);
});

for (const mode of ["prefix", "suffix", "mixed"]) test(`${mode} one-click forwards replacement percentage unchanged to scan and create`, async () => {
  const h = harness(({url, body}) => {
    if (url.endsWith("/scan") || url === "/api/video-batches") {
      assert.equal(body.defaults.cutMode, "percent");
      assert.equal(body.defaults.replacePercent, 30);
      assert.equal(body.defaults.cutSeconds, null);
    }
    if (url.endsWith("/scan")) return scanResult(1);
    if (url === "/api/video-batches") return {batch: batch("draft", 1)};
    if (url.endsWith("/run")) return {batch: batch("running", 1)};
    throw new Error(`Unexpected request: ${url}`);
  }, {realFlows: true});
  h.$("flowMode").value = mode; h.$("flowTemporalMode").value = "suffix";
  h.flowApi.updateCreateFields();
  await h.submit();
  assert.deepEqual(h.calls.map(call => call.url), ["/api/video-batches/scan", "/api/video-batches", "/api/video-batches/abc123/run"]);
});

test("directory timing validation supports percentages and keeps legacy seconds behavior", async () => {
  const h = harness(() => { throw new Error("No request expected"); });
  Object.assign(h.defaults, {mode: "prefix", cutMode: "percent"});
  for (const value of [null, 0, 100, -1, NaN, Infinity]) {
    h.defaults.replacePercent = value;
    await h.submit();
    assert.match(h.$("flowNotice").textContent, /比例/);
  }
  assert.equal(h.calls.length, 0);
  assert.equal(h.api.validateTiming({mode: "prefix", cutSeconds: 3}), "");
  assert.match(h.api.validateTiming({mode: "prefix", replacePercent: 30}), /切点/);
  assert.equal(h.api.validateTiming({mode: "prefix", cutMode: "percent", replacePercent: 0.01}), "");
  assert.equal(h.api.validateTiming({mode: "suffix", cutMode: "percent", replacePercent: 99.99}), "");
});

test("CSV row timing precedence matches the backend and validates effective values", () => {
  const h = harness(() => { throw new Error("No request expected"); });
  const parsed = h.api.parseCsv("videoPath,cutMode,replacePercent,cutSeconds\n/a.mp4,seconds,25,2\n/b.mp4,percent,45,3\n/c.mp4,,35,4\n/d.mp4,,,5\n/e.mp4,,,\n/f.mp4,percent,0,7\n/g.mp4,invalid,10,2");
  const rows = h.api.validateRows(parsed, {mode: "prefix", cutMode: "percent", replacePercent: 30, cutSeconds: null});
  assert.deepEqual(plain(rows.map(row => row.effective.cutMode)), ["seconds", "percent", "percent", "seconds", "percent", "percent", "invalid"]);
  assert.deepEqual(plain(rows.slice(0, 5).map(row => row.errors)), [[], [], [], [], []]);
  assert.match(rows[5].errors.join(), /比例/);
  assert.match(rows[6].errors.join(), /cutMode/);
  const legacy = h.api.validateRows(h.api.parseCsv("videoPath,cutSeconds\n/a.mp4,2"), {mode: "prefix", cutMode: "percent", replacePercent: 30});
  assert.equal(legacy[0].effective.cutMode, "seconds");
});

test("CSV submit keeps inferred modes for the backend and serializes numeric percentages", async () => {
  const h = harness(({url, body}) => {
    if (url === "/api/video-batches") {
      assert.deepEqual(body.rows, [{videoPath: "/a.mp4", replacePercent: 25}, {videoPath: "/b.mp4", cutSeconds: 4}, {videoPath: "/c.mp4", cutMode: "percent", replacePercent: 40, cutSeconds: 3}]);
      return {batch: batch("draft", 3)};
    }
    if (url.endsWith("/run")) return {batch: batch("running", 3)};
    throw new Error(`Unexpected request: ${url}`);
  });
  Object.assign(h.defaults, {mode: "prefix", cutMode: "percent", replacePercent: 30});
  h.$("batchMaterialSource").value = "csv";
  h.$("batchCsvText").value = "videoPath,cutMode,replacePercent,cutSeconds\n/a.mp4,,25,\n/b.mp4,,,4\n/c.mp4,percent,40,3";
  await h.submit();
  assert.equal(h.api.state.batch.status, "running");
});

test("percentage template contains mode and ratio without a misleading seconds value", async () => {
  const h = harness(() => { throw new Error("No request expected"); });
  Object.assign(h.defaults, {mode: "suffix", cutMode: "percent", replacePercent: 30, cutSeconds: null});
  h.api.templateDownload();
  const row = h.api.parseCsv(await h.downloads[0].text()).rows[0].values;
  assert.equal(row.cutMode, "percent"); assert.equal(row.replacePercent, "30"); assert.equal(row.cutSeconds, "");
});

test("flow details distinguish percent from legacy seconds and show the resolved cut", () => {
  const h = harness(() => { throw new Error("No request expected"); }, {realFlows: true});
  h.flowApi.renderInputs({mode: "suffix", inputs: {cutMode: "percent", replacePercent: 30, cutSeconds: 8.123456}});
  assert.match(h.$("flowInputSummary").innerHTML, /替换后 30%.*已解析切点：8\.123 秒/);
  h.flowApi.renderInputs({mode: "prefix", inputs: {cutSeconds: 4}});
  assert.match(h.$("flowInputSummary").innerHTML, /切点：4 秒/);
  assert.doesNotMatch(h.$("flowInputSummary").innerHTML, /替换前.*%/);
});

test("polling refreshes the resolved percentage cut without clearing prompt drafts", () => {
  const h = harness(() => { throw new Error("No request expected"); }, {realFlows: true});
  const flow = {id: "percent-flow", mode: "suffix", status: "running", inputs: {cutMode: "percent", replacePercent: 30, cutSeconds: null}, steps: []};
  h.flowApi.renderFlow(flow, true);
  assert.doesNotMatch(h.$("flowInputSummary").innerHTML, /已解析切点/);
  h.flowApi.flowState.drafts.set("percent-flow:motion_prompt", {prompt: "unsaved text"});
  h.flowApi.renderFlow({...flow, inputs: {...flow.inputs, cutSeconds: 7}}, false);
  assert.match(h.$("flowInputSummary").innerHTML, /已解析切点：7 秒/);
  assert.equal(h.flowApi.flowState.drafts.get("percent-flow:motion_prompt").prompt, "unsaved text");
});

for (const mode of ["suffix", "mixed"]) test(`${mode} single flow accepts an empty end image and preserves manual overrides`, async () => {
  const h = harness(({url, body}) => {
    assert.equal(url, "/api/video-flows");
    return {flow: {id: "tail-optional", mode: body.mode, status: "draft", inputs: body, steps: []}};
  }, {realFlows: true});
  h.$("flowInputMode").value = "single"; h.$("flowMode").value = mode; h.$("flowTemporalMode").value = "suffix";
  h.$("flowVideoPath").value = "/videos/a.mp4";
  h.$("flowReferencePath").value = mode === "mixed" ? "/images/a.png" : "";
  h.flowApi.updateCreateFields();
  assert.equal(h.$("flowEndPath").required, false);
  assert.equal(h.$("flowReferencePath").required, mode === "mixed");
  assert.match(h.$("flowRecipe").innerHTML, mode === "mixed" ? /提取空间处理后末帧/ : /提取原视频末帧/);
  await h.flowApi.createFlow({preventDefault() {}});
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].body.endImagePath, "");
  h.$("flowEndPath").value = "/manual/last.png";
  h.flowApi.updateCreateFields();
  assert.match(h.$("flowRecipe").innerHTML, /使用指定尾图/);
  await h.flowApi.createFlow({preventDefault() {}});
  assert.equal(h.calls[1].body.endImagePath, "/manual/last.png");
});

for (const mode of ["suffix", "mixed"]) test(`${mode} directory batch starts without an end-image directory`, async () => {
  const h = harness(({url, body}) => {
    if (url.endsWith("/scan")) {
      assert.equal(body.directories.endImages, "");
      assert.equal(body.defaults.endImagePath, "");
      assert.equal(body.directories.references, mode === "mixed" ? "/data/references" : "");
      const scan = scanResult(1);
      if (mode === "suffix") delete scan.matches[0].assets.referenceImagePath;
      return scan;
    }
    if (url === "/api/video-batches") {
      assert.equal(body.rows[0].endImagePath, undefined);
      assert.equal(body.rows[0].referenceImagePath, mode === "mixed" ? "/images/1.png" : undefined);
      return {batch: batch("draft", 1)};
    }
    if (url.endsWith("/run")) return {batch: batch("running", 1)};
    throw new Error(`Unexpected request: ${url}`);
  }, {realFlows: true});
  h.$("flowMode").value = mode; h.$("flowTemporalMode").value = "suffix";
  if (mode === "suffix") h.$("batchDir-references").value = "";
  h.flowApi.updateCreateFields();
  assert.equal(h.$("flowEndPath").required, false);
  assert.match(h.$("batchRoleTitle-endImages").textContent, /可选/);
  assert.match(h.$("batchRoleHint").textContent, /自动取/);
  await h.submit();
  assert.equal(h.api.state.batch.status, "running");
  if (mode === "suffix") assert.match(h.$("batchScanPreview").innerHTML, /自动取视频末帧/);
});

test("CSV end images are optional while spatial references remain required", async () => {
  const h = harness(({url, body}) => {
    if (url === "/api/video-batches") {
      assert.deepEqual(body.rows, [{videoPath: "/a.mp4"}, {videoPath: "/b.mp4", endImagePath: "/manual/end.png"}]);
      return {batch: batch()};
    }
    if (url.endsWith("/run")) return {batch: batch("running")};
    throw new Error(`Unexpected request: ${url}`);
  });
  Object.assign(h.defaults, {mode: "suffix", cutMode: "percent", replacePercent: 30});
  const parsed = h.api.parseCsv("videoPath,endImagePath\n/a.mp4,\n/b.mp4,/manual/end.png");
  assert.deepEqual(plain(h.api.validateRows(parsed, h.defaults).map(row => row.errors)), [[], []]);
  const mixed = {...h.defaults, mode: "mixed", temporalMode: "suffix", referenceImagePath: "/ref.png"};
  assert.deepEqual(plain(h.api.validateRows(parsed, mixed).map(row => row.errors)), [[], []]);
  assert.match(h.api.validateRows(parsed, {...mixed, referenceImagePath: ""})[0].errors.join(), /缺少参考图/);
  h.$("batchMaterialSource").value = "csv";
  h.$("batchCsvText").value = "videoPath,endImagePath\n/a.mp4,\n/b.mp4,/manual/end.png";
  await h.submit();
  assert.equal(h.api.state.batch.status, "running");
});

test("matched explicit browser end images override common defaults in created rows", async () => {
  const h = harness(({url, body}, {api}) => {
    if (url.endsWith("/scan")) {
      assert.equal(body.defaults.endImagePath, "/shared/end.png");
      assert.equal(body.files.endImages.length, 1);
      const scan = scanResult(1);
      scan.matches[0].assets = {videoPath: api.state.files.videos[0], endImagePath: api.state.files.endImages[0]};
      return scan;
    }
    if (url === "/api/comfy/upload") return {path: `/uploaded/${body.name}`};
    if (url === "/api/video-batches") {
      assert.equal(body.rows[0].endImagePath, "/uploaded/a.png");
      assert.equal(body.defaults.endImagePath, "/shared/end.png");
      return {batch: batch("draft", 1)};
    }
    if (url.endsWith("/run")) return {batch: batch("running", 1)};
    throw new Error(`Unexpected request: ${url}`);
  }, {realFlows: true});
  h.$("flowMode").value = "suffix"; h.$("flowEndPath").value = "/shared/end.png";
  h.$("batchMaterialSource").value = "files";
  h.api.chooseFiles("videos", [{name: "a.mp4", size: 1}]);
  h.api.chooseFiles("endImages", [{name: "a.png", size: 1}]);
  h.flowApi.updateCreateFields();
  await h.submit();
  assert.equal(h.api.state.batch.status, "running");
});

test("suffix CSV template leaves end images empty for automatic extraction", async () => {
  const h = harness(() => { throw new Error("No request expected"); });
  Object.assign(h.defaults, {mode: "suffix", cutMode: "percent", replacePercent: 30});
  h.api.templateDownload();
  const row = h.api.parseCsv(await h.downloads[0].text()).rows[0].values;
  assert.equal(row.endImagePath, "");
  assert.equal(row.referenceImagePath, "");
  assert.deepEqual(plain(h.api.validateRows({rows: [{values: row}]}, h.defaults)[0].errors), []);
});
