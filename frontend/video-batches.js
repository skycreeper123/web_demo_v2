(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const flowUI = window.VideoFlowUI;
  const html = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char]));
  const columns = ["name", "videoPath", "referenceImagePath", "referenceAlt1Path", "referenceAlt2Path", "startImagePath", "endImagePath", "cutSeconds", "editInstruction"];
  const labels = {name: "名称", videoPath: "原视频", referenceImagePath: "参考图", referenceAlt1Path: "补充参考图 1", referenceAlt2Path: "补充参考图 2", startImagePath: "新首图", endImagePath: "目标尾图", cutSeconds: "切点（秒）", editInstruction: "编辑需求"};
  const roles = ["videos", "references", "startImages", "endImages"];
  const assetFields = ["videoPath", "referenceImagePath", "referenceAlt1Path", "referenceAlt2Path", "startImagePath", "endImagePath"];
  const videoExtensions = /\.(mp4|mov|avi|mkv|webm|m4v)$/i;
  const imageExtensions = /\.(png|jpe?g|webp|bmp)$/i;
  const modes = {spatial: "局部空间替换", prefix: "替换前段", suffix: "替换后段", mixed: "混合替换"};
  const statuses = {draft: "待开始", ready: "可继续", pending: "待处理", running: "运行中", completed: "已完成", partial: "部分失败", failed: "失败", interrupted: "执行中断", stopped: "已停止"};
  const state = {list: [], batch: null, visible: false, timer: null, request: 0, busy: false, preparing: false, parsed: null, csvDirty: false, initialized: false, previousPromptSource: "ai", inputMode: "single", scan: null, scanFingerprint: "", expandMatches: false, fileVersion: 0, files: Object.fromEntries(roles.map(role => [role, []])), fileMap: new Map(), uploaded: new Map(), expandedFiles: {}, preparationLogs: [], frozenControls: new Map()};
  const stored = key => { try { return localStorage.getItem(key) || ""; } catch { return ""; } };
  const store = (key, value) => { try { localStorage.setItem(key, value); } catch {} };
  const isBatch = () => $("flowInputMode").value === "batch";
  const notice = (message = "", error = false) => {
    $("flowNotice").hidden = !message;
    $("flowNotice").textContent = message;
    $("flowNotice").classList.toggle("is-error", error);
  };
  const safeUrl = value => {
    try { const url = new URL(value || "", location.href); return value && url.origin === location.origin && ["http:", "https:"].includes(url.protocol) ? url.href : ""; }
    catch { return ""; }
  };
  async function api(path, body) {
    const response = await fetch(path, body === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.error === "string" ? data.error : data.detail || `请求失败（${response.status}）`);
    return data;
  }
  const endpoint = batch => `/api/video-batches/${encodeURIComponent(batch.id)}`;

  function parseCsv(text) {
    text = String(text || "").replace(/^\uFEFF/, "");
    const records = [];
    let cells = [], field = "", quoted = false, closed = false, line = 1, recordLine = 1;
    const fieldEnd = () => { cells.push(field); field = ""; closed = false; };
    const rowEnd = () => { fieldEnd(); if (cells.some(value => value.trim())) records.push({line: recordLine, cells}); cells = []; };
    for (let i = 0; i < text.length; i++) {
      const char = text[i];
      if (quoted) {
        if (char === '"') {
          if (text[i + 1] === '"') { field += '"'; i++; }
          else { quoted = false; closed = true; }
        } else { field += char; if (char === "\n" || char === "\r" && text[i + 1] !== "\n") line++; }
        continue;
      }
      if (char === ',') { fieldEnd(); continue; }
      if (char === "\n" || char === "\r") {
        rowEnd();
        if (char === "\r" && text[i + 1] === "\n") i++;
        line++; recordLine = line; continue;
      }
      if (closed) { if (/^[ \t]$/.test(char)) continue; throw new Error(`第 ${line} 行：闭合引号后只能是逗号或换行。`); }
      if (char === '"') { if (field !== "") throw new Error(`第 ${line} 行：字段内引号需用双引号转义。`); quoted = true; }
      else field += char;
    }
    if (quoted) throw new Error(`第 ${recordLine} 行：引号未闭合。`);
    if (field || cells.length || closed) rowEnd();
    if (!records.length) throw new Error("请导入包含表头和素材行的 CSV。");
    const headers = records.shift().cells.map(value => value.trim());
    if (new Set(headers).size !== headers.length) throw new Error("CSV 存在重复列名，请保留每列一次。");
    const unknown = headers.filter(header => !columns.includes(header));
    if (unknown.length) throw new Error(`不支持的列：${unknown.map(value => value || "（空列名）").join("、")}。请使用模板列名；流程类型通过统一设置选择。`);
    if (!headers.includes("videoPath")) throw new Error("CSV 缺少 videoPath（原视频路径）列。");
    if (!records.length) throw new Error("CSV 只有表头，没有素材行。");
    const rows = records.map(record => {
      if (record.cells.length !== headers.length) throw new Error(`第 ${record.line} 行有 ${record.cells.length} 列，表头有 ${headers.length} 列。含逗号或换行的字段须用双引号包住。`);
      return {line: record.line, values: Object.fromEntries(headers.map((header, index) => [header, record.cells[index].trim()]))};
    });
    return {headers, rows};
  }
  function validateRows(parsed, defaults) {
    const temporal = defaults.mode === "mixed" ? defaults.temporalMode : defaults.mode;
    return parsed.rows.map(row => {
      const effective = {...defaults};
      for (const [key, value] of Object.entries(row.values)) if (value !== "") effective[key] = value;
      const errors = [];
      if (!effective.videoPath) errors.push("缺少原视频路径（本行或统一素材）");
      if (["spatial", "mixed"].includes(defaults.mode) && !effective.referenceImagePath) errors.push("缺少参考图（本行或统一素材）");
      if (temporal === "suffix" && !effective.endImagePath) errors.push("缺少目标尾图（本行或统一素材）");
      if (defaults.mode !== "spatial" && (!Number.isFinite(Number(effective.cutSeconds)) || Number(effective.cutSeconds) <= 0)) errors.push("切点须大于 0（本行或统一参数）");
      return {...row, effective, errors};
    });
  }
  function renderPreview() {
    if (!state.parsed) return false;
    const rows = validateRows(state.parsed, flowUI.getDefaults());
    const errors = rows.filter(row => row.errors.length);
    $("batchCsvSummary").textContent = `${rows.length} 组素材 · ${state.parsed.headers.length} 列 · ${errors.length ? `${errors.length} 组待修正` : "表格检查通过"}${state.csvDirty ? " · 内容已修改，需重新解析" : ""}`;
    $("batchCsvSummary").classList.toggle("is-error", !!errors.length || state.csvDirty);
    $("batchCsvErrors").hidden = !errors.length;
    $("batchCsvErrors").textContent = errors.slice(0, 20).map(row => `CSV 第 ${row.line} 行：${row.errors.join("；")}`).join("\n") + (errors.length > 20 ? `\n另有 ${errors.length - 20} 组错误，请查看预览。` : "");
    const headers = state.parsed.headers;
    $("batchCsvPreview").hidden = false;
    $("batchCsvPreview").innerHTML = `<table class="batch-table"><caption>导入列：${html(headers.join(", "))}。空单元格显示继承后的值。${rows.length > 200 ? `预览前 200 组，提交时包含全部 ${rows.length} 组。` : ""}</caption><thead><tr><th scope="col">CSV 行</th>${headers.map(key => `<th scope="col">${html(labels[key])}<small>${html(key)}</small></th>`).join("")}<th scope="col">检查</th></tr></thead><tbody>${rows.slice(0, 200).map(row => `<tr class="${row.errors.length ? "batch-row-error" : ""}"><th scope="row">${row.line}</th>${headers.map(key => `<td>${html(row.effective[key] ?? "")}${!row.values[key] && row.effective[key] ? '<small>继承统一参数</small>' : ""}</td>`).join("")}<td>${row.errors.length ? html(row.errors.join("；")) : "通过"}</td></tr>`).join("")}</tbody></table>`;
    return !errors.length && !state.csvDirty;
  }
  function parseInput() {
    try {
      state.parsed = parseCsv($("batchCsvText").value);
      state.csvDirty = false;
      return renderPreview();
    } catch (error) {
      state.parsed = null;
      $("batchCsvSummary").textContent = "素材表未通过检查。";
      $("batchCsvSummary").classList.add("is-error");
      $("batchCsvErrors").hidden = false;
      $("batchCsvErrors").textContent = error.message;
      $("batchCsvPreview").hidden = true;
      return false;
    }
  }
  function updateInputMode() {
    const batch = isBatch();
    if (batch && state.inputMode !== "batch") { state.previousPromptSource = $("flowPromptSource").value; $("flowPromptSource").value = "ai"; }
    if (!batch && state.inputMode === "batch") $("flowPromptSource").value = state.previousPromptSource;
    state.inputMode = batch ? "batch" : "single";
    $("flowPromptSource").disabled = batch || state.preparing;
    $("flowVideoField").querySelector("label > span").textContent = batch ? "统一原视频（可选）" : "原视频 *";
    $("flowReferenceField").querySelector("label > span").textContent = batch ? "统一参考图（可选）" : "空间替换参考图 *";
    $("flowEndField").querySelector("label > span").textContent = batch ? "统一目标尾图（可选）" : "目标尾图 *";
    $("batchImportPanel").hidden = !batch;
    $("batchDefaultsHint").hidden = !batch;
    $("flowCreateTitle").textContent = batch ? "创建视频批次" : "创建视频流程";
    $("flowCreateBadge").textContent = batch ? "一种流程，多组素材" : "一条原视频，一个流程";
    $("flowCreateBtn").textContent = batch ? state.preparing ? "正在准备素材…" : "一键生成" : "创建流程";
    $("flowCreateNote").textContent = batch ? "自动匹配全部素材、上传浏览器文件并开始生成。任何一组缺图或重名都会先停下，请修正后再生成；运行中一组失败会继续下一组。" : "创建只保存素材与步骤。点击执行后才开始生成。";
    if (batch) $("flowPromptSourceHint").textContent = "批量模式统一使用自动提示词，逐组读取对应模块已保存的 API 和 System / User 配置；不使用模拟结果。";
    else $("flowPromptSourceHint").textContent = $("flowPromptSource").value === "manual" ? "创建后检查并修改各步提示词，保存后再执行。" : "每次自动生成读取对应模块已保存的 API、System Prompt 与 User Prompt，并在 User Prompt 末尾补充任务范围、素材顺序和时长。不使用模拟结果。";
    if (batch && state.parsed) renderPreview();
    updateMaterialSource();
  }
  function activeRoles(defaults = flowUI.getDefaults()) {
    const temporal = defaults.mode === "mixed" ? defaults.temporalMode : defaults.mode;
    return roles.filter(role => role === "videos" || role === "references" || role === "startImages" && temporal === "prefix" || role === "endImages" && temporal === "suffix");
  }
  function updateMaterialSource() {
    const source = $("batchMaterialSource").value;
    const defaults = flowUI.getDefaults();
    const temporal = defaults.mode === "mixed" ? defaults.temporalMode : defaults.mode;
    const spatial = ["spatial", "mixed"].includes(defaults.mode);
    $("batchDirectoryPanel").hidden = source === "csv";
    $("batchCsvPanel").hidden = source !== "csv";
    const titles = {videos: "原视频目录 *", references: spatial ? "空间替换参考图目录" : temporal === "suffix" ? "目标尾图目录" : "新首图目录（可选）", startImages: "优先使用的新首图目录（可选）", endImages: defaults.mode === "mixed" ? "目标尾图目录 *" : "优先使用的目标尾图目录（可选）"};
    $("batchRoleHint").textContent = spatial ? `原视频与空间参考图同名配对${temporal === "suffix" ? "，混合替换后段还需单独的目标尾图目录（或共用尾图）" : defaults.mode === "mixed" ? "；新首图可另选目录，缺省时自动生成" : ""}。` : temporal === "suffix" ? "同名图片作为目标尾图。可额外指定优先使用的尾图目录，缺省时使用共用尾图。" : "同名图片作为可选新首图。可额外指定优先使用的新首图目录；未提供时由 Qwen 根据原首帧生成。";
    for (const role of roles) {
      $(`batchRole-${role}`).hidden = !activeRoles(defaults).includes(role);
      $(`batchRoleTitle-${role}`).textContent = titles[role];
      $(`batchServer-${role}`).hidden = source !== "directories";
      $(`batchBrowser-${role}`).hidden = source !== "files";
    }
    invalidateScan();
  }
  function renderFiles(role) {
    const files = state.files[role].map(item => state.fileMap.get(item.id));
    renderStackList(files, $(`batchFileList-${role}`), "尚未选择文件夹。刷新页面后需重新选择浏览器文件。", {label: role === "videos" ? "视频" : "图片", expanded: !!state.expandedFiles[role], toggleKey: `batch-${role}`});
    $(`batchClear-${role}`).disabled = state.preparing || !files.length;
  }
  function chooseFiles(role, incoming) {
    if (state.preparing) return;
    const accepts = role === "videos" ? videoExtensions : imageExtensions;
    const files = Array.from(incoming || []).filter(file => accepts.test(file.name));
    for (const item of state.files[role]) { state.fileMap.delete(item.id); state.uploaded.delete(item.id); }
    const version = ++state.fileVersion;
    state.files[role] = files.map((file, index) => {
      const id = `${role}:${version}:${index}`;
      state.fileMap.set(id, file);
      return {id, name: file.name, relativePath: file.webkitRelativePath || file.name, path: ""};
    });
    state.expandedFiles[role] = false;
    renderFiles(role); invalidateScan();
    const ignored = Array.from(incoming || []).length - files.length;
    if (ignored) notice(`已读取 ${files.length} 个${role === "videos" ? "视频" : "图片"}，忽略 ${ignored} 个不支持格式的文件。`);
  }
  function initDirectories() {
    $("batchDirectoryInputs").innerHTML = roles.map(role => `<section id="batchRole-${role}" class="batch-directory-card"><h3 id="batchRoleTitle-${role}"></h3><div id="batchServer-${role}"><label class="prompt-field"><span class="panel-note">服务器可读取的文件夹路径（包含子目录）</span><input id="batchDir-${role}" class="input" placeholder="${role === "videos" ? "/data/videos" : role === "references" ? "/data/references" : role === "startImages" ? "/data/start_images" : "/data/end_images"}" /></label></div><div id="batchBrowser-${role}" hidden><label id="batchDropzone-${role}" class="dropzone batch-folder-dropzone"><input id="batchFiles-${role}" type="file" multiple webkitdirectory directory accept="${role === "videos" ? ".mp4,.mov,.avi,.mkv,.webm,.m4v" : ".png,.jpg,.jpeg,.webp,.bmp"}" /><span>点击选择文件夹，或拖入文件</span><small>保留目录内文件名，生成时上传所需素材</small></label><div id="batchFileList-${role}" class="stack-list empty"></div><button id="batchClear-${role}" class="btn btn-ghost" type="button">清空此目录</button></div></section>`).join("");
    for (const role of roles) {
      const input = $(`batchFiles-${role}`), dropzone = $(`batchDropzone-${role}`);
      // Stop the shared picker before it opens while a snapshot is being submitted.
      ["click", "drop"].forEach(type => dropzone.addEventListener(type, event => {
        if (state.preparing) { event.preventDefault(); event.stopImmediatePropagation(); }
      }, true));
      bindDropzone(dropzone, input, files => chooseFiles(role, files));
      input.addEventListener("change", event => chooseFiles(role, event.target.files));
      $(`batchClear-${role}`).addEventListener("click", () => { input.value = ""; chooseFiles(role, []); });
      renderFiles(role);
    }
    $("batchDirectoryInputs").addEventListener("click", event => {
      const button = event.target.closest("[data-list-toggle]");
      if (!button || state.preparing) return;
      const role = button.dataset.listToggle.replace(/^batch-/, "");
      if (!roles.includes(role)) return;
      state.expandedFiles[role] = !state.expandedFiles[role]; renderFiles(role);
    });
  }
  function scanPayload(defaults = {...flowUI.getDefaults(), promptSource: "ai"}) {
    const inputMode = $("batchMaterialSource").value;
    const active = activeRoles(defaults);
    return {defaults, inputMode, directories: Object.fromEntries(roles.map(role => [role, inputMode === "directories" && active.includes(role) ? $(`batchDir-${role}`).value.trim() : ""])), files: Object.fromEntries(roles.map(role => [role, inputMode === "files" && active.includes(role) ? state.files[role] : []]))};
  }
  function creationFingerprint() {
    return JSON.stringify({batch: isBatch(), ...scanPayload(), csv: $("batchMaterialSource").value === "csv" ? $("batchCsvText").value : ""});
  }
  function invalidateScan() {
    if (!state.scan || state.scanFingerprint === creationFingerprint()) return;
    state.scan = null; state.scanFingerprint = ""; state.expandMatches = false;
    $("batchScanSummary").textContent = "素材或统一设置已修改；点击“一键生成”会重新匹配。";
    $("batchScanSummary").classList.remove("is-error");
    $("batchScanErrors").hidden = true; $("batchScanPreview").hidden = true; $("batchExpandMatchesBtn").hidden = true;
  }
  function renderScan() {
    const scan = state.scan;
    if (!scan) return;
    const matches = scan.matches || [], blocked = matches.filter(match => !match.canCreate);
    const ready = matches.length - blocked.length;
    $("batchScanSummary").textContent = `${matches.length} 组素材 · ${ready} 组匹配成功 · ${blocked.length} 组待修正${matches.some(match => match.requiresUpload) ? " · 生成时上传浏览器素材" : ""}。${blocked.length ? "请修正全部问题后再一键生成。" : matches.length ? "一键生成会处理全部组。" : "目录中没有可用视频。"}`;
    $("batchScanSummary").classList.toggle("is-error", !!blocked.length || !matches.length);
    $("batchScanErrors").hidden = !blocked.length;
    const issueText = issue => `${issue.message || "素材不能创建"}${issue.candidates?.length ? `（${issue.candidates.map(asset => asset.relativePath || asset.path || asset.name).join("、")}）` : ""}`;
    $("batchScanErrors").textContent = blocked.slice(0, 20).map(match => `${match.row?.name || match.matchKey || `第 ${match.index} 组`}：${(match.issues || []).map(issueText).join("；") || "素材不能创建"}`).join("\n") + (blocked.length > 20 ? `\n另有 ${blocked.length - 20} 组待修正，展开全部匹配可查看。` : "");
    $("batchScanPreview").hidden = !matches.length;
    const shown = state.expandMatches ? matches : matches.slice(0, 200);
    $("batchScanPreview").innerHTML = `<table class="batch-table"><caption>${matches.length > shown.length ? `预览前 ${shown.length} 组，共 ${matches.length} 组；生成包含全部组。` : `共 ${matches.length} 组。`}图片匹配及必需项以所选流程为准。</caption><thead><tr><th scope="col">组</th><th scope="col">原视频</th><th scope="col">匹配图片</th><th scope="col">检查</th></tr></thead><tbody>${shown.map(match => `<tr class="${match.canCreate ? "" : "batch-row-error"}"><th scope="row">${html(match.row?.name || match.matchKey || match.index)}</th><td>${html(match.assets?.videoPath?.relativePath || match.assets?.videoPath?.name || match.row?.videoPath || "—")}</td><td>${assetFields.filter(field => field !== "videoPath" && match.assets?.[field]).map(field => `<small>${html(labels[field])}</small>${html(match.assets[field].relativePath || match.assets[field].name || match.assets[field].path)}`).join("<br>") || "无需图片 / 自动生成新首图"}</td><td>${match.canCreate ? "匹配成功" : (match.issues || []).map(issue => html(issueText(issue))).join("<br>") || "素材不能创建"}</td></tr>`).join("")}</tbody></table>`;
    $("batchExpandMatchesBtn").hidden = matches.length <= 200;
    $("batchExpandMatchesBtn").textContent = state.expandMatches ? "收起匹配预览" : `展开全部 ${matches.length} 组匹配`;
  }
  function preparationLog(message) {
    state.preparationLogs.push(`[${new Date().toLocaleTimeString()}] ${message}`);
    $("batchPreparationPanel").hidden = false;
    const output = $("batchPreparationLogs");
    output.textContent = state.preparationLogs.join("\n"); output.scrollTop = output.scrollHeight;
  }
  function freezePreparation(frozen) {
    state.preparing = frozen;
    if (frozen) {
      state.frozenControls.clear();
      const controls = [...$("flowCreateForm").querySelectorAll("input, select, textarea, button"), ...$("flowHistory").querySelectorAll("button"), ...$("batchHistory").querySelectorAll("button"), $("flowNewBtn"), $("batchNewBtn")];
      for (const control of controls) { state.frozenControls.set(control, control.disabled); control.disabled = true; }
    } else {
      for (const [control, disabled] of state.frozenControls) control.disabled = disabled;
      state.frozenControls.clear();
    }
    $("batchDirectoryInputs").classList.toggle("is-preparing", frozen);
    updateInputMode();
    $("flowCreateBtn").disabled = frozen || !!flowUI.uploadsPending();
  }
  async function scanMaterials(defaults, fingerprint) {
    const payload = scanPayload(defaults);
    if (!payload.directories.videos && !payload.files.videos.length) throw new Error("请提供原视频目录。生成数量由目录中的视频决定。");
    if (defaults.mode !== "spatial" && (!Number.isFinite(Number(defaults.cutSeconds)) || Number(defaults.cutSeconds) <= 0)) throw new Error("请填写大于 0 的统一切点（从视频开始计算，秒）。");
    preparationLog(payload.inputMode === "files" ? `正在匹配 ${payload.files.videos.length} 个视频及所选图片…` : "正在扫描服务器目录并按文件名匹配…");
    const scan = await api("/api/video-batches/scan", payload);
    if (fingerprint !== creationFingerprint()) throw new Error("素材或统一设置已改变，请重新匹配后生成。");
    state.scan = scan; state.scanFingerprint = fingerprint; state.expandMatches = false; renderScan();
    const blocked = (scan.matches || []).filter(match => !match.canCreate);
    preparationLog(`匹配完成：${scan.matches?.length || 0} 组，${blocked.length} 组待修正。`);
    return scan;
  }
  async function checkMatching() {
    if (state.busy || flowUI.uploadsPending()) { notice("请等待正在提交的任务或素材上传完成。", true); return; }
    state.busy = true; state.preparationLogs = []; notice(); freezePreparation(true);
    try { await scanMaterials({...flowUI.getDefaults(), promptSource: "ai"}, creationFingerprint()); }
    catch (error) { notice(error.message, true); preparationLog(error.message); }
    finally { state.busy = false; freezePreparation(false); }
  }
  async function uploadRows(scan) {
    const matches = scan.matches || [];
    if (!matches.length) throw new Error("未找到可生成的素材组，请检查视频目录。");
    if (matches.some(match => !match.canCreate) || Number(scan.summary?.blocked || 0)) throw new Error("存在缺失素材或重名冲突，尚未创建批次。请按匹配预览修正全部问题。");
    const required = new Map();
    for (const match of matches) for (const field of assetFields) {
      const asset = match.assets?.[field];
      if (!asset || asset.path) continue;
      if (!asset.id || !state.fileMap.has(asset.id)) throw new Error(`浏览器素材已失效：${asset.name || field}，请重新选择文件夹。`);
      const file = state.fileMap.get(asset.id);
      if (file.size > 1024 ** 3) throw new Error(`${file.name} 超过单文件 1 GB 上限。`);
      required.set(asset.id, file);
    }
    let index = 0;
    for (const [id, file] of required) {
      index++;
      if (state.uploaded.has(id)) { preparationLog(`复用已上传素材 ${index}/${required.size}：${file.name}`); continue; }
      preparationLog(`上传素材 ${index}/${required.size}：${file.name}`);
      const response = await fetch("/api/comfy/upload", {method: "POST", headers: {"Content-Type": "application/octet-stream", "X-Filename": encodeURIComponent(file.name)}, body: file});
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.path) throw new Error(`上传 ${file.name} 失败：${data.error || `请求失败（${response.status}）`}`);
      state.uploaded.set(id, data.path);
    }
    return matches.map(match => {
      const row = Object.fromEntries(Object.entries(match.row || {}).filter(([key, value]) => columns.includes(key) && value !== "" && value !== null && value !== undefined));
      for (const field of assetFields) {
        const asset = match.assets?.[field];
        if (asset) row[field] = asset.path || state.uploaded.get(asset.id);
      }
      return row;
    });
  }
  function saveDraft() {
    const controls = [...$("flowCreateForm").querySelectorAll("input[id], select[id], textarea[id]")].filter(input => input.type !== "file");
    const values = Object.fromEntries(controls.map(input => [input.id, input.type === "checkbox" ? input.checked : input.value]));
    try { sessionStorage.setItem("video-batches:create-draft", JSON.stringify(values)); } catch {}
  }
  function restoreDraft() {
    try {
      const values = JSON.parse(sessionStorage.getItem("video-batches:create-draft") || "null");
      if (values && typeof values === "object") for (const [id, value] of Object.entries(values)) {
        const control = $(id);
        if (!control || !$("flowCreateForm").contains(control) || control.type === "file") continue;
        if (control.type === "checkbox") control.checked = !!value; else control.value = String(value ?? "");
      }
    } catch {}
    flowUI.updateCreateFields();
    updateInputMode();
    if ($("batchCsvText").value.trim()) parseInput();
  }
  function templateDownload() {
    const defaults = flowUI.getDefaults();
    const temporal = defaults.mode === "mixed" ? defaults.temporalMode : defaults.mode;
    const example = {name: "素材 001", videoPath: "/data/videos/001.mp4", referenceImagePath: ["spatial", "mixed"].includes(defaults.mode) ? "/data/references/001.png" : "", startImagePath: "", endImagePath: temporal === "suffix" ? "/data/end_frames/001.png" : "", cutSeconds: defaults.mode !== "spatial" ? defaults.cutSeconds || 3 : "", editInstruction: ""};
    const escape = value => `"${String(value ?? "").replace(/"/g, '""')}"`;
    const content = "\uFEFF" + columns.join(",") + "\r\n" + columns.map(key => escape(example[key])).join(",") + "\r\n";
    const url = URL.createObjectURL(new Blob([content], {type: "text/csv;charset=utf-8"}));
    const link = document.createElement("a"); link.href = url; link.download = `video-batch-${defaults.mode}.csv`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function renderHistory() {
    $("batchHistory").innerHTML = state.list.length ? state.list.map(batch => `<button type="button" class="flow-history-item ${state.visible && state.batch?.id === batch.id ? "is-active" : ""}" data-batch-open="${html(batch.id)}"><strong>${html(batch.name || "视频批次")}</strong><span><span>${html(modes[batch.mode] || batch.mode)} · ${Number(batch.total || 0)} 组</span><span class="flow-status" data-status="${html(batch.status)}">${html(statuses[batch.status] || batch.status)}</span></span><small>成功 ${Number(batch.completed || 0)} · 失败 ${Number(batch.failed || 0)}</small></button>`).join("") : '<p class="panel-note flow-empty">尚无批次。选择素材目录和替换方式，即可批量生成。</p>';
  }
  async function loadHistory() { const data = await api("/api/video-batches"); state.list = data.batches || []; renderHistory(); }
  function renderBatch(batch) {
    state.batch = batch;
    state.visible = true;
    $("batchDetail").hidden = false;
    document.dispatchEvent(new CustomEvent("video-batches:show"));
    $("batchDetailTitle").textContent = batch.name || "视频批次";
    $("batchDetailMeta").textContent = [modes[batch.mode] || batch.mode, ["spatial", "mixed"].includes(batch.mode) ? batch.spatialTarget === "background" ? "背景" : "前景 / 主体" : "", batch.mode === "mixed" ? modes[batch.temporalMode] : "", "按组串行执行"].filter(Boolean).join(" · ");
    $("batchStatus").textContent = statuses[batch.status] || batch.status;
    $("batchStatus").dataset.status = batch.status;
    const total = Number(batch.total || batch.rows?.length || 0), completed = Number(batch.completed || 0), failed = Number(batch.failed || 0), pending = Number(batch.pending || 0);
    $("batchTotal").textContent = total; $("batchCompleted").textContent = completed; $("batchFailed").textContent = failed; $("batchPending").textContent = pending;
    $("batchProgress").style.width = `${total ? Math.min(100, (completed + failed) * 100 / total) : 0}%`;
    const active = (batch.rows || []).find(row => row.status === "running");
    $("batchProgressText").textContent = `已处理 ${completed + failed} / ${total} 组${active ? ` · 当前：${active.name || `第 ${active.index} 组`}${active.activeStepTitle ? ` / ${active.activeStepTitle}` : ""}` : ""}`;
    const running = batch.status === "running";
    $("batchRunBtn").disabled = state.busy || running || !pending || !!batch.requiresReview;
    $("batchRetryBtn").disabled = state.busy || running || !failed;
    $("batchStopBtn").hidden = !running;
    $("batchStopBtn").disabled = state.busy || !!batch.stopRequested;
    $("batchStopBtn").textContent = batch.stopRequested ? "已请求在本步结束后停止" : "当前步骤后停止";
    $("batchRunHint").textContent = running ? "一组失败后继续下一组；停止请求在当前步骤结束后生效，保留已完成结果。" : batch.status === "completed" ? "全部完成，可打开每组流程或下载成片及汇总表。" : "开始 / 继续只处理待完成组并跳过失败组；仅重试失败只处理失败组，已成功组不会重跑。";
    $("batchReviewNotice").hidden = !batch.requiresReview;
    $("batchReviewNotice").textContent = batch.requiresReview ? "部分任务结果不确定，请先检查服务器 Comfy 队列。检查后使用“仅重试失败”处理这些条目，再点击“开始 / 继续”处理剩余素材。" : "";
    $("batchError").hidden = !batch.error; $("batchError").textContent = batch.error || "";
    const manifest = safeUrl(batch.manifestUrl);
    $("batchManifestLink").hidden = !manifest;
    if (manifest) { $("batchManifestLink").href = manifest; $("batchManifestLink").download = `batch-${batch.id}.csv`; }
    const logDownload = safeUrl(batch.logDownloadUrl);
    $("batchLogDownload").hidden = !logDownload;
    if (logDownload) { $("batchLogDownload").href = logDownload; $("batchLogDownload").download = `batch-${batch.id}-logs.txt`; }
    const signature = JSON.stringify(batch.rows || []);
    if ($("batchRows").dataset.signature !== signature) {
      $("batchRows").innerHTML = `<table class="batch-table"><thead><tr><th scope="col">组</th><th scope="col">名称 / 步骤</th><th scope="col">状态</th><th scope="col">错误</th><th scope="col">流程与成片</th></tr></thead><tbody>${(batch.rows || []).map(row => {
        const finalUrl = safeUrl(row.finalVideo?.url);
        return `<tr><th scope="row">${html(row.index)}</th><td>${html(row.name || "未命名")}<small>${html(row.activeStepTitle || "")}</small></td><td><span class="flow-status" data-status="${html(row.status)}">${html(statuses[row.status] || row.status)}</span></td><td class="batch-error-cell">${html(row.error || "—")}</td><td><div class="batch-row-actions">${row.flowId ? `<button type="button" class="btn btn-ghost" data-batch-flow="${html(row.flowId)}">打开流程</button>` : ""}${finalUrl ? `<a href="${html(finalUrl)}" target="_blank" rel="noreferrer">查看成片</a><a href="${html(finalUrl)}" download="${html(row.finalVideo.name || "video.mp4")}">下载</a>` : ""}</div></td></tr>`;
      }).join("")}</tbody></table>`;
      $("batchRows").dataset.signature = signature;
    }
    const index = state.list.findIndex(item => item.id === batch.id);
    if (index >= 0) state.list[index] = {...state.list[index], ...batch}; else state.list.unshift(batch);
    renderHistory();
  }
  function stopPolling() { clearTimeout(state.timer); state.timer = null; }
  async function refreshBatch() {
    const id = state.batch?.id;
    if (!id || !state.visible) return;
    const data = await api(`/api/video-batches/${encodeURIComponent(id)}`);
    if (state.batch?.id !== id || !state.visible || Number(data.batch.updatedAt || 0) < Number(state.batch.updatedAt || 0)) return;
    renderBatch(data.batch);
    const logUrl = safeUrl(data.batch.logUrl);
    if (logUrl || data.batch.jobId) {
      try {
        const log = await api(logUrl || `/api/jobs/${encodeURIComponent(data.batch.jobId)}`);
        if (state.batch?.id === id && state.visible) {
          const output = $("batchLogs"), nearBottom = output.scrollHeight - output.scrollTop - output.clientHeight < 60;
          output.textContent = (log.logs || []).join("\n") || "等待运行日志。";
          if (nearBottom) output.scrollTop = output.scrollHeight;
        }
      } catch (error) {
        if (state.batch?.id === id && state.visible) $("batchLogs").textContent = `日志暂时无法读取：${error.message}。稍后将自动重试。`;
      }
    }
  }
  function startPolling() {
    stopPolling();
    const tick = async () => {
      if (!state.visible || $("videoFlowsView").hidden) return;
      try { await refreshBatch(); } catch (error) { notice(`批次状态读取失败：${error.message}`, true); }
      if (state.visible && !$("videoFlowsView").hidden) state.timer = setTimeout(tick, state.batch?.status === "running" ? 2000 : 6000);
    };
    state.timer = setTimeout(tick, 1500);
  }
  async function openBatch(id) {
    if (state.preparing) return;
    const request = ++state.request;
    stopPolling(); notice();
    const data = await api(`/api/video-batches/${encodeURIComponent(id)}`);
    if (request !== state.request) return;
    store("video-workspace:selection", "batch"); store("video-batches:selected", id);
    $("batchPreparationPanel").hidden = true;
    $("batchLogs").textContent = "正在读取批次历史日志…";
    renderBatch(data.batch); await refreshBatch(); startPolling();
  }
  async function createBatch(event) {
    if (!isBatch()) return;
    event.preventDefault();
    if (state.busy || flowUI.uploadsPending()) { notice("请等待正在提交的任务或素材上传完成。", true); return; }
    const defaults = {...flowUI.getDefaults(), promptSource: "ai"};
    const fingerprint = creationFingerprint();
    const source = $("batchMaterialSource").value;
    let created = null;
    state.busy = true; state.preparationLogs = []; notice(); freezePreparation(true);
    try {
      let rows;
      if (source === "csv") {
        if (!parseInput()) throw new Error("请修正素材表中的全部问题后再生成。");
        rows = state.parsed.rows.map(row => Object.fromEntries(Object.entries(row.values).filter(([, value]) => value !== "").map(([key, value]) => [key, key === "cutSeconds" ? Number(value) : value])));
        preparationLog(`CSV 检查通过：${rows.length} 组素材。`);
      } else {
        const scan = await scanMaterials(defaults, fingerprint);
        rows = await uploadRows(scan);
      }
      if (fingerprint !== creationFingerprint()) throw new Error("素材或统一设置已改变，尚未创建批次。请重新匹配后生成。");
      preparationLog(`准备完成，正在保存全部 ${rows.length} 组素材…`);
      const data = await api("/api/video-batches", {name: defaults.name, defaults, rows});
      created = data.batch;
      store("video-workspace:selection", "batch"); store("video-batches:selected", data.batch.id);
      renderBatch(created);
      $("batchLogs").textContent = "批次已保存，正在启动…";
      preparationLog(`已保存批次 ${created.name || created.id}，正在启动自动生成…`);
      const started = await api(`${endpoint(created)}/run`, {retryFailed: false});
      renderBatch(started.batch); preparationLog("已开始生成。下方显示每组步骤、实时日志与成片。");
      notice(`已开始处理 ${rows.length} 组素材；可在批次历史中继续查看进度。`);
      startPolling();
    } catch (error) {
      preparationLog(error.message);
      if (created) {
        renderBatch(state.batch?.id === created.id ? state.batch : created);
        notice(`批次已保存，但启动未确认：${error.message}。请在此批次查看状态并点击“开始 / 继续”，无需重新导入。`, true);
        startPolling();
      } else notice(error.message, true);
    } finally { state.busy = false; freezePreparation(false); if (state.visible && state.batch) renderBatch(state.batch); }
  }
  async function batchAction(action, body) {
    const batch = state.batch;
    if (!batch || state.busy) return;
    state.busy = true; renderBatch(batch); notice();
    try {
      const data = await api(`${endpoint(batch)}/${action}`, body);
      if (state.visible && state.batch?.id === batch.id) { renderBatch(data.batch); startPolling(); }
    } catch (error) { notice(error.message, true); }
    finally { state.busy = false; if (state.visible && state.batch?.id === batch.id) renderBatch(state.batch); }
  }

  initDirectories();
  $("batchMaterialSource").addEventListener("change", () => { updateMaterialSource(); saveDraft(); });
  $("batchScanBtn").addEventListener("click", checkMatching);
  $("batchExpandMatchesBtn").addEventListener("click", () => { state.expandMatches = !state.expandMatches; renderScan(); });
  $("batchCsvFile").addEventListener("change", async event => {
    const file = event.target.files[0]; if (!file) return;
    try { if (file.size > 5 * 1024 ** 2) throw new Error("CSV 超过 5 MB，请分批导入。"); $("batchCsvText").value = await file.text(); parseInput(); saveDraft(); }
    catch (error) { notice(error.message, true); }
  });
  $("batchCsvText").addEventListener("input", () => { state.csvDirty = true; $("batchCsvSummary").textContent = "CSV 内容已修改，点击“解析并预览”查看最新内容。"; $("batchCsvSummary").classList.add("is-error"); $("batchCsvPreview").hidden = true; });
  $("batchParseBtn").addEventListener("click", parseInput);
  $("batchTemplateBtn").addEventListener("click", templateDownload);
  $("flowCreateForm").addEventListener("submit", createBatch);
  $("flowCreateForm").addEventListener("input", () => { if (isBatch() && state.parsed && !state.csvDirty) renderPreview(); invalidateScan(); saveDraft(); });
  $("flowCreateForm").addEventListener("change", () => { invalidateScan(); saveDraft(); });
  document.addEventListener("video-flows:settingschange", () => { updateInputMode(); saveDraft(); });
  $("batchNewBtn").addEventListener("click", () => { flowUI.showCreate(); $("flowInputMode").value = "batch"; flowUI.updateCreateFields(); saveDraft(); });
  $("batchRefreshListBtn").addEventListener("click", () => loadHistory().catch(error => notice(error.message, true)));
  $("batchRefreshBtn").addEventListener("click", () => refreshBatch().catch(error => notice(error.message, true)));
  $("batchRunBtn").addEventListener("click", () => batchAction("run", {retryFailed: false}));
  $("batchRetryBtn").addEventListener("click", () => batchAction("run", {retryFailed: true}));
  $("batchStopBtn").addEventListener("click", () => batchAction("stop", {}));
  $("batchHistory").addEventListener("click", event => { const button = event.target.closest("[data-batch-open]"); if (button) openBatch(button.dataset.batchOpen).catch(error => notice(error.message, true)); });
  $("batchRows").addEventListener("click", event => { const button = event.target.closest("[data-batch-flow]"); if (button) flowUI.openFlow(button.dataset.batchFlow).catch(error => notice(error.message, true)); });
  document.addEventListener("video-batches:open", event => openBatch(event.detail.id).catch(error => notice(error.message, true)));
  document.addEventListener("video-flows:show", () => { ++state.request; state.visible = false; $("batchDetail").hidden = true; if (!state.preparing) $("batchPreparationPanel").hidden = true; stopPolling(); renderHistory(); });
  document.addEventListener("studio:viewchange", async event => {
    if (event.detail.view !== "videoFlows") { stopPolling(); return; }
    try {
      await loadHistory();
      if (state.visible && state.batch) { await refreshBatch(); startPolling(); }
      else if (!state.initialized) {
        state.initialized = true;
        const selected = stored("video-batches:selected");
        if (stored("video-workspace:selection") === "batch" && selected && state.list.some(batch => batch.id === selected)) await openBatch(selected);
      }
    } catch (error) { notice(`无法加载批次：${error.message}`, true); }
  });
  restoreDraft();
})();
