(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const flowUI = window.VideoFlowUI;
  const html = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char]));
  const columns = ["name", "videoPath", "referenceImagePath", "startImagePath", "endImagePath", "cutSeconds", "editInstruction"];
  const labels = {name: "名称", videoPath: "原视频", referenceImagePath: "参考图", startImagePath: "新首图", endImagePath: "目标尾图", cutSeconds: "切点（秒）", editInstruction: "编辑需求"};
  const modes = {spatial: "局部空间替换", prefix: "替换前段", suffix: "替换后段", mixed: "混合替换"};
  const statuses = {draft: "待开始", ready: "可继续", pending: "待处理", running: "运行中", completed: "已完成", partial: "部分失败", failed: "失败", interrupted: "执行中断", stopped: "已停止"};
  const state = {list: [], batch: null, visible: false, timer: null, request: 0, busy: false, parsed: null, csvDirty: false, initialized: false, previousPromptSource: "ai", inputMode: "single"};
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
    if (records.length > 500) throw new Error(`CSV 有 ${records.length} 组素材；每批最多 500 组，请拆分后导入。`);
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
    $("batchCsvPreview").innerHTML = `<table class="batch-table"><caption>导入列：${html(headers.join(", "))}。空单元格显示继承后的值。</caption><thead><tr><th scope="col">CSV 行</th>${headers.map(key => `<th scope="col">${html(labels[key])}<small>${html(key)}</small></th>`).join("")}<th scope="col">检查</th></tr></thead><tbody>${rows.map(row => `<tr class="${row.errors.length ? "batch-row-error" : ""}"><th scope="row">${row.line}</th>${headers.map(key => `<td>${html(row.effective[key] ?? "")}${!row.values[key] && row.effective[key] ? '<small>继承统一参数</small>' : ""}</td>`).join("")}<td>${row.errors.length ? html(row.errors.join("；")) : "通过"}</td></tr>`).join("")}</tbody></table>`;
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
    $("flowPromptSource").disabled = batch;
    $("flowVideoField").querySelector("label > span").textContent = batch ? "统一原视频（可选）" : "原视频 *";
    $("flowReferenceField").querySelector("label > span").textContent = batch ? "统一参考图（可选）" : "空间替换参考图 *";
    $("flowEndField").querySelector("label > span").textContent = batch ? "统一目标尾图（可选）" : "目标尾图 *";
    $("batchImportPanel").hidden = !batch;
    $("batchDefaultsHint").hidden = !batch;
    $("flowCreateTitle").textContent = batch ? "创建视频批次" : "创建视频流程";
    $("flowCreateBadge").textContent = batch ? "一种流程，多组素材" : "一条原视频，一个流程";
    $("flowCreateBtn").textContent = batch ? "导入批次" : "创建流程";
    $("flowCreateNote").textContent = batch ? "导入只创建批次和子流程，保存后需点击“开始 / 继续”才会生成。" : "创建只保存素材与步骤。点击执行后才开始生成。";
    if (batch) $("flowPromptSourceHint").textContent = "批量模式统一使用自动提示词，逐组读取对应模块已保存的 API 和 System / User 配置；不使用模拟结果。";
    else $("flowPromptSourceHint").textContent = $("flowPromptSource").value === "manual" ? "创建后检查并修改各步提示词，保存后再执行。" : "每次自动生成读取对应模块已保存的 API、System Prompt 与 User Prompt，并在 User Prompt 末尾补充任务范围、素材顺序和时长。不使用模拟结果。";
    if (batch && state.parsed) renderPreview();
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
    $("batchHistory").innerHTML = state.list.length ? state.list.map(batch => `<button type="button" class="flow-history-item ${state.visible && state.batch?.id === batch.id ? "is-active" : ""}" data-batch-open="${html(batch.id)}"><strong>${html(batch.name || "视频批次")}</strong><span><span>${html(modes[batch.mode] || batch.mode)} · ${Number(batch.total || 0)} 组</span><span class="flow-status" data-status="${html(batch.status)}">${html(statuses[batch.status] || batch.status)}</span></span><small>成功 ${Number(batch.completed || 0)} · 失败 ${Number(batch.failed || 0)}</small></button>`).join("") : '<p class="panel-note flow-empty">尚无批次。可用 CSV 一次导入多组素材。</p>';
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
    if (data.batch.jobId) {
      try {
        const job = await api(`/api/jobs/${encodeURIComponent(data.batch.jobId)}`);
        if (state.batch?.id === id && state.visible) $("batchLogs").textContent = (job.logs || []).join("\n") || "等待运行日志。";
      } catch { /* Persisted batch results remain available if old logs have expired. */ }
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
    const request = ++state.request;
    stopPolling(); notice();
    const data = await api(`/api/video-batches/${encodeURIComponent(id)}`);
    if (request !== state.request) return;
    store("video-workspace:selection", "batch"); store("video-batches:selected", id);
    $("batchLogs").textContent = "执行后显示批次日志。";
    renderBatch(data.batch); startPolling();
  }
  async function createBatch(event) {
    if (!isBatch()) return;
    event.preventDefault();
    if (state.busy || flowUI.uploadsPending()) { notice("请等待正在提交的任务或素材上传完成。", true); return; }
    if (!parseInput()) { notice("请修正素材表后再导入。", true); return; }
    const defaults = {...flowUI.getDefaults(), promptSource: "ai"};
    const rows = state.parsed.rows.map(row => Object.fromEntries(Object.entries(row.values).filter(([, value]) => value !== "").map(([key, value]) => [key, key === "cutSeconds" ? Number(value) : value])));
    state.busy = true; $("flowCreateBtn").disabled = true; notice();
    try {
      const data = await api("/api/video-batches", {name: defaults.name, defaults, rows});
      store("video-workspace:selection", "batch"); store("video-batches:selected", data.batch.id);
      renderBatch(data.batch); notice(`已导入 ${rows.length} 组素材，尚未开始生成。点击“开始 / 继续”执行。`); startPolling();
    } catch (error) { notice(error.message, true); }
    finally { state.busy = false; $("flowCreateBtn").disabled = !!flowUI.uploadsPending(); if (state.visible && state.batch) renderBatch(state.batch); }
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

  $("batchCsvFile").addEventListener("change", async event => {
    const file = event.target.files[0]; if (!file) return;
    try { if (file.size > 5 * 1024 ** 2) throw new Error("CSV 超过 5 MB，请分批导入。"); $("batchCsvText").value = await file.text(); parseInput(); saveDraft(); }
    catch (error) { notice(error.message, true); }
  });
  $("batchCsvText").addEventListener("input", () => { state.csvDirty = true; $("batchCsvSummary").textContent = "CSV 内容已修改，点击“解析并预览”查看最新内容。"; $("batchCsvSummary").classList.add("is-error"); $("batchCsvPreview").hidden = true; });
  $("batchParseBtn").addEventListener("click", parseInput);
  $("batchTemplateBtn").addEventListener("click", templateDownload);
  $("flowCreateForm").addEventListener("submit", createBatch);
  $("flowCreateForm").addEventListener("input", () => { if (isBatch() && state.parsed && !state.csvDirty) renderPreview(); saveDraft(); });
  $("flowCreateForm").addEventListener("change", saveDraft);
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
  document.addEventListener("video-flows:show", () => { ++state.request; state.visible = false; $("batchDetail").hidden = true; stopPolling(); renderHistory(); });
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
