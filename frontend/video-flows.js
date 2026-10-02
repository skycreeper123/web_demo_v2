(() => {
  "use strict";

  const $ = id => document.getElementById(id);
  const html = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const modes = {spatial: "局部空间替换", prefix: "替换前段", suffix: "替换后段", mixed: "混合替换"};
  const statuses = {draft: "待执行", pending: "待执行", ready: "可继续", running: "运行中", completed: "已完成", failed: "失败", stopped: "已停止"};
  const kinds = {prompt: "提示词", comfy: "生成", media: "素材准备", assemble: "合成"};
  const promptModules = {
    image: {view: "image", label: "图片 → I2V Prompt"},
    image_edit: {view: "imageEdit", label: "图片 → 图生图 Prompt"},
    video: {view: "video", label: "视频 → 视频编辑 Prompt"},
  };
  const flowState = {list: [], flow: null, timer: null, busy: false, uploads: 0, request: 0, drafts: new Map(), previews: new Map(), initialized: false, panel: "create"};
  const store = (key, value) => { try { localStorage.setItem(key, value); } catch {} };
  const stored = key => { try { return localStorage.getItem(key) || ""; } catch { return ""; } };
  try {
    const savedDrafts = JSON.parse(sessionStorage.getItem("video-flows:prompt-drafts") || "[]");
    if (Array.isArray(savedDrafts)) for (const [key, value] of savedDrafts) {
      if (typeof key === "string" && value && ["prompt", "negativePrompt", "instruction"].every(field => typeof value[field] === "string")) flowState.drafts.set(key, value);
    }
  } catch {}
  const savePromptDrafts = () => { try { sessionStorage.setItem("video-flows:prompt-drafts", JSON.stringify([...flowState.drafts])); } catch {} };
  const notice = (message = "", error = false) => {
    $("flowNotice").hidden = !message;
    $("flowNotice").textContent = message;
    $("flowNotice").classList.toggle("is-error", error);
  };
  const safeUrl = value => {
    if (!value) return "";
    try {
      const url = new URL(value, window.location.href);
      return url.origin === window.location.origin && ["http:", "https:"].includes(url.protocol) ? url.href : "";
    } catch { return ""; }
  };
  async function api(path, body) {
    const response = await fetch(path, body === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || data.detail || `请求失败（${response.status}）`);
    return data;
  }
  const endpoint = flow => `/api/video-flows/${encodeURIComponent(flow.id)}`;
  const draftKey = (flowId, stepId) => `${flowId}:${stepId}`;
  const hasDrafts = () => !!flowState.flow && [...flowState.drafts.keys()].some(key => key.startsWith(`${flowState.flow.id}:`));
  const isRunning = () => flowState.flow?.status === "running" || flowState.flow?.steps?.some(step => step.status === "running");
  const temporalMode = () => $("flowMode").value === "mixed" ? $("flowTemporalMode").value : $("flowMode").value;
  const batchInput = () => $("flowInputMode").value === "batch";

  function updateCreateFields() {
    const mode = $("flowMode").value;
    const temporal = temporalMode();
    const spatial = ["spatial", "mixed"].includes(mode);
    const timed = mode !== "spatial";
    const batch = batchInput();
    $("flowVideoField").hidden = false;
    $("flowVideoPath").required = !batch;
    $("flowSpatialField").hidden = !spatial;
    $("flowReferenceField").hidden = !spatial;
    $("flowReferencePath").required = spatial && !batch;
    $("flowTemporalField").hidden = mode !== "mixed";
    $("flowStartField").hidden = !timed || temporal !== "prefix";
    $("flowEndField").hidden = !timed || temporal !== "suffix";
    $("flowEndPath").required = timed && temporal === "suffix" && !batch;
    $("flowCutField").hidden = !timed;
    $("flowCutSeconds").required = timed && !batch;
    $("flowCutSeconds").disabled = !timed;
    $("flowCutSeconds").min = batch ? "" : "0.001";
    const sequence = [];
    if (spatial) sequence.push($("flowSpatialTarget").value === "background" ? "替换背景" : "替换前景");
    if (timed) {
      sequence.push("按切点拆分与取帧");
      if (temporal === "prefix") sequence.push($("flowStartPath").value.trim() ? "使用新首图" : "生成新首图");
      sequence.push("首尾双图生成", temporal === "prefix" ? "接回保留后段" : "接回保留前段");
    }
    $("flowRecipe").innerHTML = sequence.map((label, index) => `<span><b>${index + 1}</b>${html(label)}</span>`).join('<i aria-hidden="true">→</i>');
    $("flowPromptSourceHint").textContent = $("flowPromptSource").value === "manual"
      ? "创建后检查并修改各步提示词，保存后再执行。"
      : "每次自动生成读取对应模块已保存的 API、System Prompt 与 User Prompt，并在 User Prompt 末尾补充任务范围、素材顺序和时长。不使用模拟结果。";
    document.dispatchEvent(new CustomEvent("video-flows:settingschange"));
  }

  function dateLabel(value) {
    if (!value) return "";
    const date = new Date(typeof value === "number" && value < 1e12 ? value * 1000 : value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", {month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"});
  }
  function renderHistory() {
    $("flowHistory").innerHTML = flowState.list.length ? flowState.list.map(flow => `
      <button type="button" class="flow-history-item ${flow.id === flowState.flow?.id ? "is-active" : ""}" data-flow-open="${html(flow.id)}" aria-current="${flow.id === flowState.flow?.id ? "true" : "false"}">
        <strong>${html(flow.name || modes[flow.mode] || "视频流程")}</strong>
        <span><span>${html(modes[flow.mode] || flow.mode)}</span><span class="flow-status" data-status="${html(flow.status)}">${html(statuses[flow.status] || flow.status)}</span></span>
        <small>${html(dateLabel(flow.updatedAt || flow.createdAt))}</small>
      </button>`).join("") : '<p class="panel-note flow-empty">还没有流程。创建后可随时回来继续。</p>';
  }
  async function loadHistory() {
    const data = await api("/api/video-flows");
    flowState.list = (data.flows || []).filter(flow => !flow.batchId);
    renderHistory();
  }

  function mediaCard(output) {
    const url = safeUrl(output.url);
    const name = output.name || output.key || "结果文件";
    const path = output.path || "";
    const extension = (path || name).split(".").pop().toLowerCase();
    const kind = output.kind || (["mp4", "webm", "mov", "mkv", "avi"].includes(extension) ? "video" : ["png", "jpg", "jpeg", "webp", "bmp"].includes(extension) ? "image" : "text");
    const preview = url && kind === "video" ? `<video controls preload="metadata" playsinline src="${html(url)}"></video>`
      : url && kind === "image" ? `<a href="${html(url)}" target="_blank" rel="noreferrer"><img src="${html(url)}" alt="${html(name)}" loading="lazy" /></a>` : "";
    return `<div class="flow-media-card">${preview}<div class="flow-media-caption"><strong>${html(name)}</strong>${path ? `<code>${html(path)}</code>` : ""}${url ? `<div class="flow-file-links"><a href="${html(url)}" target="_blank" rel="noreferrer">打开</a><a href="${html(url)}" download="${html(name)}">下载</a></div>` : '<small class="panel-note">文件路径已保存</small>'}</div></div>`;
  }
  function artifactOutputs(flow) {
    if (Array.isArray(flow.artifacts)) return flow.artifacts;
    return Object.entries(flow.artifacts || {}).flatMap(([key, value]) => value && typeof value === "object" ? [{key, ...value}] : []);
  }
  function renderInputs(flow) {
    const inputs = flow.inputs || {};
    const paths = [["videoPath", "原视频", "video"], ["referenceImagePath", "空间参考图", "image"], ["referenceAlt1Path", "补充参考图 1", "image"], ["referenceAlt2Path", "补充参考图 2", "image"], ["startImagePath", "新首图", "image"], ["endImagePath", "目标尾图", "image"]];
    const artifacts = artifactOutputs(flow);
    const cards = paths.flatMap(([key, name, kind]) => {
      if (!inputs[key]) return [];
      const item = typeof inputs[key] === "object" ? inputs[key] : {path: inputs[key]};
      const artifact = artifacts.find(value => value.path === item.path);
      const url = item.url || inputs[`${key}Url`] || inputs[key.replace("Path", "Url")] || artifact?.url;
      return [mediaCard({name, kind, ...item, url})];
    });
    const notes = [inputs.cutSeconds != null && flow.mode !== "spatial" ? `切点：${inputs.cutSeconds} 秒` : "", `声音：${inputs.keepAudio === false ? "不保留" : "保留原视频声音"}`, `提示词：${inputs.promptSource === "manual" ? "手动填写" : "自动生成"}`].filter(Boolean);
    $("flowInputSummary").innerHTML = `<p class="panel-note">${html(notes.join(" · "))}</p>${inputs.editInstruction ? `<p class="flow-input-instruction">${html(inputs.editInstruction)}</p>` : ""}<div class="flow-output-grid">${cards.join("")}</div>`;
  }
  function stepCanRun(step, flow) {
    const steps = flow.steps || [];
    const dependencies = Array.isArray(step.dependsOn) ? step.dependsOn : step.dependsOn ? [step.dependsOn] : [];
    return dependencies.every(id => steps.some(candidate => candidate.id === id && candidate.status === "completed"));
  }
  function stepMarkup(step, index, flow) {
    const draft = flowState.drafts.get(draftKey(flow.id, step.id));
    const settings = draft || step.settings || {};
    const promptModule = step.kind === "prompt" ? promptModules[step.settings?.apiKind] : null;
    const editable = step.kind === "prompt" || ["prompt", "negativePrompt", "instruction"].some(key => Object.prototype.hasOwnProperty.call(step.settings || {}, key));
    const outputs = Array.isArray(step.outputs) ? step.outputs : [];
    return `<div class="flow-step-heading"><span class="flow-step-number">${index + 1}</span><div><div class="flow-step-title"><h3>${html(step.title || step.id)}</h3><span class="flow-status" data-step-status data-status="${html(step.status)}">${html(statuses[step.status] || step.status)}</span></div><p class="panel-note">${html(step.description || kinds[step.kind] || "")}</p></div></div>
      ${step.kind === "prompt" ? `<div class="flow-step-actions"><span class="chip chip-soft">配置来源：${html(promptModule?.label || "未识别 Prompt 模块")}</span><button type="button" class="btn btn-ghost" data-flow-prompt-config="${html(step.settings?.apiKind || "")}" ${promptModule ? "" : "disabled"}>配置此 Prompt 模块</button></div><p class="panel-note">自动生成时读取此模块已保存的 API、System Prompt 和 User Prompt。修改全局配置不会更新已生成文字；请重跑本提示词步骤及后续步骤。</p>` : ""}
      ${step.error ? `<p class="flow-error" role="alert">${html(step.error)}</p>` : ""}
      ${editable ? `<details class="flow-step-editor" ${step.kind === "prompt" || draft ? "open" : ""}><summary>查看 / 编辑提示词与指令<span data-dirty-label>${draft ? " · 尚未保存" : ""}</span></summary><div class="flow-step-fields">
        <label class="prompt-field"><span>本步编辑指令</span><textarea class="textarea flow-small-textarea" rows="2" data-step-field="instruction">${html(settings.instruction || "")}</textarea></label>
        <label class="prompt-field"><span>正向提示词</span><textarea class="textarea flow-prompt-textarea" rows="5" data-step-field="prompt" placeholder="自动模式执行后显示生成的提示词；也可手动填写并保存。">${html(settings.prompt || "")}</textarea></label>
        <label class="prompt-field"><span>负向提示词</span><textarea class="textarea flow-small-textarea" rows="2" data-step-field="negativePrompt">${html(settings.negativePrompt || "")}</textarea></label>
        <div class="flow-editor-footer"><p class="panel-note">保存修改或重新执行已完成步骤，会使后续步骤需要重新运行。</p><button type="button" class="btn btn-ghost" data-step-save="${html(step.id)}" ${draft ? "" : "disabled"}>保存修改</button></div>
      </div></details>` : ""}
      ${outputs.length ? `<details class="flow-step-output" open><summary>本步结果 · ${outputs.length} 个文件</summary><div class="flow-output-grid">${outputs.map(mediaCard).join("")}</div></details>` : ""}
      <div class="flow-step-actions"><small class="panel-note">${!stepCanRun(step, flow) ? "等待前置步骤完成" : step.status === "completed" ? "重新执行此步会重置后续步骤。" : ""}</small><button type="button" class="btn btn-ghost" data-step-run="${html(step.id)}">${step.status === "failed" ? "重试此步" : step.status === "completed" ? "重新执行此步" : "执行此步"}</button></div>`;
  }
  function updateControls() {
    const flow = flowState.flow;
    if (!flow) return;
    const running = isRunning() || !!flow.batchLocked;
    const dirty = hasDrafts();
    const unfinished = (flow.steps || []).some(step => step.status !== "completed");
    $("flowNextBtn").disabled = flowState.busy || running || dirty || !unfinished;
    $("flowRunAllBtn").disabled = flowState.busy || running || dirty || !unfinished;
    $("flowStopBtn").hidden = !running || !!flow.batchLocked;
    $("flowStopBtn").disabled = flowState.busy || !!flow.stopRequested;
    $("flowStopBtn").textContent = flow.stopRequested ? "已请求在本步结束后停止" : "当前步骤结束后停止";
    $("flowBackBatchBtn").hidden = !flow.batchId;
    $("flowRunHint").textContent = flow.batchLocked ? "所属批次正在运行，本流程只读。可返回批次查看总进度或请求停止。" : dirty ? "有尚未保存的修改，请保存后再执行。" : running
      ? flow.stopRequested ? "停止请求已保存；当前生成完成后，不再启动后续步骤。" : "执行中，可查看中间结果。停止只在当前步骤结束后生效。"
      : !unfinished ? "所有步骤已完成。可预览或下载最终结果。" : "下一步只执行一个步骤；连续执行会依次运行剩余步骤。";
    document.querySelectorAll("[data-step-run]").forEach(button => {
      const step = flow.steps.find(item => item.id === button.dataset.stepRun);
      button.disabled = flowState.busy || running || dirty || !step || !stepCanRun(step, flow);
    });
    document.querySelectorAll("[data-step-save]").forEach(button => {
      button.disabled = flowState.busy || running || !flowState.drafts.has(draftKey(flow.id, button.dataset.stepSave));
    });
    document.querySelectorAll("[data-step-field]").forEach(input => { input.disabled = flowState.busy || running; });
  }
  function renderFlow(flow, changed = false) {
    flowState.flow = flow;
    flowState.panel = "single";
    $("flowCreatePanel").hidden = true;
    $("flowDetail").hidden = false;
    $("flowDetailTitle").textContent = flow.name || modes[flow.mode] || "视频流程";
    const inputs = flow.inputs || {};
    const suffix = flow.mode === "mixed" ? ` · ${modes[inputs.temporalMode] || "替换前段"}` : "";
    const spatial = ["spatial", "mixed"].includes(flow.mode) ? ` · ${inputs.spatialTarget === "background" ? "背景" : "前景 / 主体"}` : "";
    $("flowDetailMeta").textContent = `${modes[flow.mode] || flow.mode}${spatial}${suffix} · ${dateLabel(flow.updatedAt || flow.createdAt)}`;
    $("flowStatus").textContent = statuses[flow.status] || flow.status;
    $("flowStatus").dataset.status = flow.status;
    const steps = flow.steps || [];
    const completed = steps.filter(step => step.status === "completed").length;
    const current = steps.find(step => step.status === "running") || steps.find(step => step.status !== "completed");
    $("flowProgress").style.width = `${steps.length ? completed * 100 / steps.length : 0}%`;
    $("flowProgressText").textContent = `已完成 ${completed} / ${steps.length} 步${current ? ` · ${current.status === "running" ? "正在" : "接下来"}：${current.title}` : ""}`;
    if (changed) { $("flowSteps").replaceChildren(); renderInputs(flow); $("flowLogs").textContent = "执行后显示运行日志。"; }
    for (const [index, step] of steps.entries()) {
      let card = [...$("flowSteps").children].find(node => node.dataset.stepId === step.id);
      const signature = JSON.stringify(step);
      if (!card) {
        card = document.createElement("article");
        card.className = "card panel flow-step";
        card.dataset.stepId = step.id;
        $("flowSteps").append(card);
      }
      card.dataset.status = step.status;
      // Polling must not replace an editor or a playing preview while the user is inspecting it.
      if (card.dataset.signature !== signature) {
        const focusInside = card.contains(document.activeElement) && document.activeElement.matches("input, textarea, select");
        const playing = [...card.querySelectorAll("video")].some(video => !video.paused);
        if (!focusInside && !playing) {
          const expanded = [...card.querySelectorAll("details")].map(details => details.open);
          card.innerHTML = stepMarkup(step, index, flow);
          card.querySelectorAll("details").forEach((details, i) => { if (expanded[i] !== undefined) details.open = expanded[i]; });
          card.dataset.signature = signature;
        } else {
          const badge = card.querySelector("[data-step-status]");
          if (badge) { badge.textContent = statuses[step.status] || step.status; badge.dataset.status = step.status; }
        }
      }
    }
    const finalStep = [...steps].reverse().find(step => step.kind === "assemble" || step.kind === "comfy");
    const finalOutputs = flow.status === "completed" ? (finalStep?.outputs || []).filter(output => output.kind === "video" || /\.(mp4|webm|mov|mkv|avi)$/i.test(output.path || output.name || "")) : [];
    const resultSignature = JSON.stringify(finalOutputs);
    $("flowResultPanel").hidden = !finalOutputs.length;
    if ($("flowResults").dataset.signature !== resultSignature) {
      $("flowResults").innerHTML = finalOutputs.map(mediaCard).join("");
      $("flowResults").dataset.signature = resultSignature;
    }
    if (!flow.batchId) {
      const listIndex = flowState.list.findIndex(item => item.id === flow.id);
      if (listIndex >= 0) flowState.list[listIndex] = {...flowState.list[listIndex], ...flow};
      else flowState.list.unshift(flow);
    }
    renderHistory();
    updateControls();
  }

  async function refreshFlow({initial = false} = {}) {
    const flow = flowState.flow;
    if (!flow || flowState.panel !== "single") return;
    const data = await api(endpoint(flow));
    if (flowState.flow?.id !== flow.id || flowState.panel !== "single") return;
    if (Number(data.flow.updatedAt) < Number(flowState.flow.updatedAt)) return;
    renderFlow(data.flow, initial);
    if (data.flow.error) notice(data.flow.error, true);
    const jobId = data.flow.jobId || [...(data.flow.steps || [])].reverse().find(step => step.jobId)?.jobId;
    if (jobId) {
      try {
        const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
        if (flowState.flow?.id === flow.id) $("flowLogs").textContent = (job.logs || []).join("\n") || "等待运行日志。";
      } catch { /* A saved flow remains usable even if an old job log is unavailable. */ }
    }
  }
  function stopPolling() { clearTimeout(flowState.timer); flowState.timer = null; }
  function startPolling() {
    stopPolling();
    const tick = async () => {
      if ($("videoFlowsView").hidden || !flowState.flow || flowState.panel !== "single") return;
      try { await refreshFlow(); }
      catch (error) { notice(`状态读取失败：${error.message}。稍后会自动重试。`, true); }
      if (!$('videoFlowsView').hidden && flowState.flow && flowState.panel === "single") flowState.timer = setTimeout(tick, isRunning() || flowState.flow.batchLocked ? 2000 : 6000);
    };
    flowState.timer = setTimeout(tick, 1500);
  }
  async function openFlow(id) {
    const request = ++flowState.request;
    flowState.panel = "single";
    document.dispatchEvent(new CustomEvent("video-flows:show", {detail: {panel: "single"}}));
    stopPolling();
    notice();
    const data = await api(`/api/video-flows/${encodeURIComponent(id)}`);
    if (request !== flowState.request) return;
    store("video-flows:selected", id);
    store("video-workspace:selection", "single");
    renderFlow(data.flow, true);
    if (data.flow.error) notice(data.flow.error, true);
    await refreshFlow();
    startPolling();
  }
  function showCreate() {
    ++flowState.request;
    stopPolling();
    flowState.flow = null;
    flowState.panel = "create";
    store("video-workspace:selection", "create");
    document.dispatchEvent(new CustomEvent("video-flows:show", {detail: {panel: "create"}}));
    store("video-flows:selected", "");
    $("flowCreatePanel").hidden = false;
    $("flowDetail").hidden = true;
    notice();
    renderHistory();
    $("flowName").focus();
  }
  async function mutate(action, success) {
    if (flowState.busy) return;
    flowState.busy = true;
    updateControls();
    notice();
    const flowId = flowState.flow?.id;
    try {
      const result = await action();
      if (flowState.flow?.id === flowId && flowState.panel === "single" && result?.flow) {
        renderFlow(result.flow);
        startPolling();
      }
      if (success) notice(success);
    } catch (error) { notice(error.message, true); }
    finally { flowState.busy = false; updateControls(); }
  }
  async function runStep(stepId, runAll) {
    const flow = flowState.flow;
    if (!flow || isRunning() || flow.batchLocked || hasDrafts()) return;
    await mutate(() => api(`${endpoint(flow)}/run`, {runAll: !!runAll, ...(stepId ? {stepId} : {})}));
  }
  async function saveStep(stepId) {
    const flow = flowState.flow;
    if (!flow || flow.batchLocked) return;
    const key = draftKey(flow.id, stepId);
    const draft = flowState.drafts.get(key);
    if (!draft) return;
    await mutate(async () => {
      const step = flow.steps.find(item => item.id === stepId);
      const changes = Object.fromEntries(Object.entries(draft).filter(([field, value]) => value !== String(step?.settings?.[field] || "")));
      const data = await api(`${endpoint(flow)}/steps/${encodeURIComponent(stepId)}`, changes);
      flowState.drafts.delete(key);
      savePromptDrafts();
      const card = [...$("flowSteps").children].find(node => node.dataset.stepId === stepId);
      if (card) { card.dataset.signature = ""; if (card.contains(document.activeElement)) document.activeElement.blur(); }
      return data;
    }, "修改已保存，后续步骤将使用新的内容。");
  }

  function createDefaults() {
    const mode = $("flowMode").value;
    const timed = mode !== "spatial";
    const cutSeconds = Number($("flowCutSeconds").value);
    return {
      name: $("flowName").value.trim(), mode, temporalMode: $("flowTemporalMode").value,
      spatialTarget: $("flowSpatialTarget").value, videoPath: $("flowVideoPath").value.trim(),
      referenceImagePath: ["spatial", "mixed"].includes(mode) ? $("flowReferencePath").value.trim() : "",
      startImagePath: timed && temporalMode() === "prefix" ? $("flowStartPath").value.trim() : "",
      endImagePath: timed && temporalMode() === "suffix" ? $("flowEndPath").value.trim() : "",
      cutSeconds: timed && $("flowCutSeconds").value.trim() ? cutSeconds : null, editInstruction: $("flowInstruction").value.trim(),
      keepAudio: $("flowKeepAudio").checked, promptSource: $("flowPromptSource").value,
    };
  }
  async function createFlow(event) {
    event.preventDefault();
    if (batchInput()) return;
    if (flowState.uploads || flowState.busy) { notice("请等待素材上传完成。", true); return; }
    const payload = createDefaults();
    if (payload.mode !== "spatial" && (!Number.isFinite(payload.cutSeconds) || payload.cutSeconds <= 0)) { notice("请填写大于 0 的切点秒数。", true); return; }
    $("flowCreateBtn").disabled = true;
    notice();
    try {
      const data = await api("/api/video-flows", payload);
      flowState.list.unshift(data.flow);
      store("video-flows:selected", data.flow.id);
      store("video-workspace:selection", "single");
      document.dispatchEvent(new CustomEvent("video-flows:show", {detail: {panel: "single"}}));
      renderFlow(data.flow, true);
      notice("流程已保存。可以先检查步骤，再执行下一步。");
      startPolling();
    } catch (error) { notice(error.message, true); }
    finally { $("flowCreateBtn").disabled = false; }
  }

  async function upload(input) {
    const file = input.files[0];
    if (!file) return;
    const target = input.dataset.flowUpload;
    const status = $(`${target}UploadStatus`);
    flowState.uploads++;
    input.disabled = true;
    $(target).disabled = true;
    $("flowCreateBtn").disabled = true;
    status.textContent = "上传中…";
    try {
      if (file.size > 1024 ** 3) throw new Error("文件超过 1 GB，请填写服务器可访问的完整路径。");
      const response = await fetch("/api/comfy/upload", {method: "POST", headers: {"Content-Type": "application/octet-stream", "X-Filename": encodeURIComponent(file.name)}, body: file});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "上传失败");
      $(target).value = data.path;
      status.textContent = `已上传：${file.name}`;
      const previous = flowState.previews.get(target);
      if (previous) URL.revokeObjectURL(previous);
      const objectUrl = URL.createObjectURL(file);
      flowState.previews.set(target, objectUrl);
      const preview = $(`${target}Preview`);
      preview.innerHTML = target === "flowVideoPath" ? `<video controls preload="metadata" playsinline src="${html(objectUrl)}"></video>` : `<img src="${html(objectUrl)}" alt="${html(file.name)}" />`;
      updateCreateFields();
    } catch (error) { status.textContent = error.message; notice(error.message, true); }
    finally { flowState.uploads--; input.disabled = false; $(target).disabled = false; $("flowCreateBtn").disabled = !!flowState.uploads; }
  }

  $("flowCreateForm").addEventListener("submit", createFlow);
  ["flowInputMode", "flowMode", "flowTemporalMode", "flowSpatialTarget", "flowPromptSource"].forEach(id => $(id).addEventListener("change", updateCreateFields));
  $("flowStartPath").addEventListener("input", updateCreateFields);
  document.querySelectorAll("[data-flow-upload]").forEach(input => input.addEventListener("change", () => upload(input)));
  ["flowVideoPath", "flowReferencePath", "flowStartPath", "flowEndPath"].forEach(id => $(id).addEventListener("input", () => {
    const old = flowState.previews.get(id);
    if (old) URL.revokeObjectURL(old);
    flowState.previews.delete(id);
    $(`${id}Preview`).replaceChildren();
    $(`${id}UploadStatus`).textContent = "";
  }));
  $("flowNewBtn").addEventListener("click", () => { showCreate(); $("flowInputMode").value = "single"; updateCreateFields(); });
  $("flowBackBatchBtn").addEventListener("click", () => flowState.flow?.batchId && document.dispatchEvent(new CustomEvent("video-batches:open", {detail: {id: flowState.flow.batchId}})));
  $("videoFlowsView").addEventListener("click", event => {
    const button = event.target.closest("[data-flow-prompt-config]");
    const module = button && promptModules[button.dataset.flowPromptConfig];
    if (module) setView("promptStudio", module.view);
  });
  $("flowRefreshListBtn").addEventListener("click", () => loadHistory().catch(error => notice(error.message, true)));
  $("flowRefreshBtn").addEventListener("click", () => refreshFlow().catch(error => notice(error.message, true)));
  $("flowNextBtn").addEventListener("click", () => runStep(null, false));
  $("flowRunAllBtn").addEventListener("click", () => runStep(null, true));
  $("flowStopBtn").addEventListener("click", () => flowState.flow && mutate(() => api(`${endpoint(flowState.flow)}/stop`, {}), "已请求停止；当前步骤结束后生效。"));
  $("flowHistory").addEventListener("click", event => {
    const button = event.target.closest("[data-flow-open]");
    if (button) openFlow(button.dataset.flowOpen).catch(error => notice(error.message, true));
  });
  $("flowSteps").addEventListener("click", event => {
    const run = event.target.closest("[data-step-run]");
    const save = event.target.closest("[data-step-save]");
    if (run) runStep(run.dataset.stepRun, false);
    if (save) saveStep(save.dataset.stepSave);
  });
  $("flowSteps").addEventListener("input", event => {
    if (!event.target.matches("[data-step-field]") || !flowState.flow) return;
    const card = event.target.closest("[data-step-id]");
    const step = flowState.flow.steps.find(item => item.id === card.dataset.stepId);
    const values = Object.fromEntries([...card.querySelectorAll("[data-step-field]")].map(input => [input.dataset.stepField, input.value]));
    const key = draftKey(flowState.flow.id, step.id);
    const dirty = Object.keys(values).some(field => values[field] !== String(step.settings?.[field] || ""));
    if (dirty) flowState.drafts.set(key, values); else flowState.drafts.delete(key);
    savePromptDrafts();
    card.querySelector("[data-dirty-label]").textContent = dirty ? " · 尚未保存" : "";
    updateControls();
  });
  document.addEventListener("studio:viewchange", async event => {
    store("studio:last-view", event.detail.view);
    if (event.detail.view !== "videoFlows") { stopPolling(); return; }
    try {
      await loadHistory();
      if (flowState.flow && flowState.panel === "single") { await refreshFlow(); startPolling(); }
      else if (!flowState.initialized) {
        flowState.initialized = true;
        const selected = stored("video-flows:selected");
        if (selected && ["", "single"].includes(stored("video-workspace:selection"))) await openFlow(selected);
      }
    } catch (error) { notice(`无法加载已保存流程：${error.message}`, true); }
  });
  window.addEventListener("beforeunload", event => {
    if (flowState.drafts.size) { event.preventDefault(); event.returnValue = ""; }
  });
  document.addEventListener("video-batches:show", () => {
    ++flowState.request;
    flowState.panel = "batch";
    stopPolling();
    $("flowCreatePanel").hidden = true;
    $("flowDetail").hidden = true;
  });
  window.VideoFlowUI = {getDefaults: createDefaults, uploadsPending: () => flowState.uploads, openFlow, showCreate, updateCreateFields};
  updateCreateFields();
})();
