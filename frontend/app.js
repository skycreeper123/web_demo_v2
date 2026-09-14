const VIEW_META = {
  home: {
    title: "首页",
    subtitle: "统一入口，覆盖 Prompt 与视频剪辑。",
  },
  promptStudio: {
    title: "Prompt 生成工作台",
    subtitle: "统一切换多个 Prompt 模块。",
  },
  clipStudio: {
    title: "视频剪辑工作台",
    subtitle: "本地批量裁切与合并。",
  },
  comfyStudio: {
    title: "本地 Comfy 通信工作台",
    subtitle: "连接本机 ComfyUI 并提交工作流。",
  },
};

const PROMPT_MODULES = {
  image: {
    title: "图片 -> I2V Prompt",
    subtitle: "图片批量生成 I2V Prompt。",
    description: "I2V Prompt",
    panelId: "imageView",
  },
  imageEdit: {
    title: "图片 -> 图生图 Prompt",
    subtitle: "图片批量生成图生图 Prompt。",
    description: "图生图 Prompt",
    panelId: "imageEditView",
  },
  video: {
    title: "视频 -> 视频编辑 Prompt",
    subtitle: "视频与参考图生成编辑 Prompt。",
    description: "视频编辑 Prompt",
    panelId: "videoView",
  },
};

const state = {
  currentView: "home",
  activePromptModule: "image",
  defaults: null,
  browserSessionId: "",
  browserHeartbeatTimer: null,
  image: {
    files: [],
    filesExpanded: false,
    apiConfig: null,
    promptConfig: null,
    jobId: "",
    job: null,
    outputs: [],
    pollTimer: null,
  },
  imageEdit: {
    files: [],
    filesExpanded: false,
    apiConfig: null,
    promptConfig: null,
    jobId: "",
    job: null,
    outputs: [],
    pollTimer: null,
  },
  video: {
    videoFiles: [],
    videoFilesExpanded: false,
    referenceFiles: [],
    referenceFilesExpanded: false,
    apiConfig: null,
    promptConfig: null,
    matchResults: [],
    matchSummary: null,
    matchResultsExpanded: false,
    jobId: "",
    job: null,
    outputs: [],
    pollTimer: null,
  },
  clip: {
    presets: [],
    mode: "single",
    preset: "first_half_opencv",
    jobId: "",
    job: null,
    outputs: [],
    pollTimer: null,
  },
  comfy: {
    config: null,
    templates: [],
    health: null,
    jobId: "",
    job: null,
    outputs: [],
    pollTimer: null,
  },
};

const els = {
  viewTitle: document.getElementById("viewTitle"),
  viewSubtitle: document.getElementById("viewSubtitle"),
  navHomeBtn: document.getElementById("navHomeBtn"),
  navBackBtn: document.getElementById("navBackBtn"),
  shutdownAppBtn: document.getElementById("shutdownAppBtn"),
  homeView: document.getElementById("homeView"),
  promptStudioView: document.getElementById("promptStudioView"),
  clipStudioView: document.getElementById("clipStudioView"),
  comfyStudioView: document.getElementById("comfyStudioView"),
  goPromptStudioBtn: document.getElementById("goPromptStudioBtn"),
  goClipStudioBtn: document.getElementById("goClipStudioBtn"),
  goComfyStudioBtn: document.getElementById("goComfyStudioBtn"),
  promptModuleOverview: document.getElementById("promptModuleOverview"),
  promptModuleTabs: document.getElementById("promptModuleTabs"),
  imageView: document.getElementById("imageView"),
  imageEditView: document.getElementById("imageEditView"),
  videoView: document.getElementById("videoView"),
  promptModulePanels: Object.fromEntries(
    Object.entries(PROMPT_MODULES).map(([key, moduleMeta]) => [key, document.getElementById(moduleMeta.panelId)])
  ),

  clipPresetBadge: document.getElementById("clipPresetBadge"),
  clipPresetMeta: document.getElementById("clipPresetMeta"),
  clipInputCount: document.getElementById("clipInputCount"),
  clipInputMeta: document.getElementById("clipInputMeta"),
  clipStatusBadge: document.getElementById("clipStatusBadge"),
  clipJobMeta: document.getElementById("clipJobMeta"),
  clipResultCount: document.getElementById("clipResultCount"),
  clipOutputRootValue: document.getElementById("clipOutputRootValue"),
  clipSingleModeBtn: document.getElementById("clipSingleModeBtn"),
  clipMergeModeBtn: document.getElementById("clipMergeModeBtn"),
  clipModeDescription: document.getElementById("clipModeDescription"),
  clipPresetSelect: document.getElementById("clipPresetSelect"),
  clipPresetDescription: document.getElementById("clipPresetDescription"),
  clipSingleInputField: document.getElementById("clipSingleInputField"),
  clipMergeInputFields: document.getElementById("clipMergeInputFields"),
  clipInputDir: document.getElementById("clipInputDir"),
  clipInputDirA: document.getElementById("clipInputDirA"),
  clipInputDirB: document.getElementById("clipInputDirB"),
  clipOutputDir: document.getElementById("clipOutputDir"),
  clipLinuxPathEnabled: document.getElementById("clipLinuxPathEnabled"),
  startClipBtn: document.getElementById("startClipBtn"),
  refreshClipJobBtn: document.getElementById("refreshClipJobBtn"),
  openClipOutputBtn: document.getElementById("openClipOutputBtn"),
  clipProgressBar: document.getElementById("clipProgressBar"),
  clipProgressText: document.getElementById("clipProgressText"),
  clipProgressDetail: document.getElementById("clipProgressDetail"),
  clipLogBox: document.getElementById("clipLogBox"),
  clipOutputList: document.getElementById("clipOutputList"),

  imageInput: document.getElementById("imageInput"),
  imageDropzone: document.getElementById("imageDropzone"),
  imageFileList: document.getElementById("imageFileList"),
  imageSourceRootDir: document.getElementById("imageSourceRootDir"),
  imageUrlInput: document.getElementById("imageUrlInput"),
  imageSelectedCount: document.getElementById("imageSelectedCount"),
  imageStatusBadge: document.getElementById("imageStatusBadge"),
  imageJobMeta: document.getElementById("imageJobMeta"),
  imageResultCount: document.getElementById("imageResultCount"),
  imageOutputRootValue: document.getElementById("imageOutputRootValue"),
  imageApiKey: document.getElementById("imageApiKey"),
  imageBaseUrl: document.getElementById("imageBaseUrl"),
  imageModel: document.getElementById("imageModel"),
  imageOutputDir: document.getElementById("imageOutputDir"),
  imageLinuxPathEnabled: document.getElementById("imageLinuxPathEnabled"),
  imageUseMock: document.getElementById("imageUseMock"),
  imageOverwrite: document.getElementById("imageOverwrite"),
  imageModeBadge: document.getElementById("imageModeBadge"),
  imageApiConfigPath: document.getElementById("imageApiConfigPath"),
  reloadImageApiConfigBtn: document.getElementById("reloadImageApiConfigBtn"),
  saveImageApiConfigBtn: document.getElementById("saveImageApiConfigBtn"),
  imagePromptConfigPath: document.getElementById("imagePromptConfigPath"),
  imageSystemPrompt: document.getElementById("imageSystemPrompt"),
  imageUserPrompt: document.getElementById("imageUserPrompt"),
  reloadImagePromptConfigBtn: document.getElementById("reloadImagePromptConfigBtn"),
  saveImagePromptConfigBtn: document.getElementById("saveImagePromptConfigBtn"),
  imageProgressBar: document.getElementById("imageProgressBar"),
  imageProgressText: document.getElementById("imageProgressText"),
  imageProgressDetail: document.getElementById("imageProgressDetail"),
  startImageBtn: document.getElementById("startImageBtn"),
  refreshImageJobBtn: document.getElementById("refreshImageJobBtn"),
  reloadImageFilesBtn: document.getElementById("reloadImageFilesBtn"),
  openImageOutputBtn: document.getElementById("openImageOutputBtn"),
  imageLogBox: document.getElementById("imageLogBox"),
  imageOutputList: document.getElementById("imageOutputList"),

  imageEditInput: document.getElementById("imageEditInput"),
  imageEditDropzone: document.getElementById("imageEditDropzone"),
  imageEditFileList: document.getElementById("imageEditFileList"),
  imageEditSourceRootDir: document.getElementById("imageEditSourceRootDir"),
  imageEditUrlInput: document.getElementById("imageEditUrlInput"),
  imageEditSelectedCount: document.getElementById("imageEditSelectedCount"),
  imageEditStatusBadge: document.getElementById("imageEditStatusBadge"),
  imageEditJobMeta: document.getElementById("imageEditJobMeta"),
  imageEditResultCount: document.getElementById("imageEditResultCount"),
  imageEditOutputRootValue: document.getElementById("imageEditOutputRootValue"),
  imageEditApiKey: document.getElementById("imageEditApiKey"),
  imageEditBaseUrl: document.getElementById("imageEditBaseUrl"),
  imageEditModel: document.getElementById("imageEditModel"),
  imageEditOutputDir: document.getElementById("imageEditOutputDir"),
  imageEditLinuxPathEnabled: document.getElementById("imageEditLinuxPathEnabled"),
  imageEditUseMock: document.getElementById("imageEditUseMock"),
  imageEditOverwrite: document.getElementById("imageEditOverwrite"),
  imageEditModeBadge: document.getElementById("imageEditModeBadge"),
  imageEditApiConfigPath: document.getElementById("imageEditApiConfigPath"),
  reloadImageEditApiConfigBtn: document.getElementById("reloadImageEditApiConfigBtn"),
  saveImageEditApiConfigBtn: document.getElementById("saveImageEditApiConfigBtn"),
  imageEditPromptConfigPath: document.getElementById("imageEditPromptConfigPath"),
  imageEditSystemPrompt: document.getElementById("imageEditSystemPrompt"),
  imageEditUserPrompt: document.getElementById("imageEditUserPrompt"),
  reloadImageEditPromptConfigBtn: document.getElementById("reloadImageEditPromptConfigBtn"),
  saveImageEditPromptConfigBtn: document.getElementById("saveImageEditPromptConfigBtn"),
  imageEditProgressBar: document.getElementById("imageEditProgressBar"),
  imageEditProgressText: document.getElementById("imageEditProgressText"),
  imageEditProgressDetail: document.getElementById("imageEditProgressDetail"),
  startImageEditBtn: document.getElementById("startImageEditBtn"),
  refreshImageEditJobBtn: document.getElementById("refreshImageEditJobBtn"),
  reloadImageEditFilesBtn: document.getElementById("reloadImageEditFilesBtn"),
  openImageEditOutputBtn: document.getElementById("openImageEditOutputBtn"),
  imageEditLogBox: document.getElementById("imageEditLogBox"),
  imageEditOutputList: document.getElementById("imageEditOutputList"),

  videoInput: document.getElementById("videoInput"),
  videoDropzone: document.getElementById("videoDropzone"),
  videoFileList: document.getElementById("videoFileList"),
  videoSourceRootDir: document.getElementById("videoSourceRootDir"),
  videoUrlInput: document.getElementById("videoUrlInput"),
  referenceInput: document.getElementById("referenceInput"),
  referenceDropzone: document.getElementById("referenceDropzone"),
  referenceFileList: document.getElementById("referenceFileList"),
  referenceSourceRootDir: document.getElementById("referenceSourceRootDir"),
  referenceUrlInput: document.getElementById("referenceUrlInput"),
  videoSelectedCount: document.getElementById("videoSelectedCount"),
  referenceSelectedCount: document.getElementById("referenceSelectedCount"),
  videoMatchBadge: document.getElementById("videoMatchBadge"),
  videoMatchMeta: document.getElementById("videoMatchMeta"),
  videoResultCount: document.getElementById("videoResultCount"),
  scanVideoMatchBtn: document.getElementById("scanVideoMatchBtn"),
  videoApiKey: document.getElementById("videoApiKey"),
  videoBaseUrl: document.getElementById("videoBaseUrl"),
  videoModel: document.getElementById("videoModel"),
  videoOutputDir: document.getElementById("videoOutputDir"),
  videoLinuxPathEnabled: document.getElementById("videoLinuxPathEnabled"),
  videoUseMock: document.getElementById("videoUseMock"),
  videoOverwrite: document.getElementById("videoOverwrite"),
  videoModeBadge: document.getElementById("videoModeBadge"),
  videoApiConfigPath: document.getElementById("videoApiConfigPath"),
  reloadVideoApiConfigBtn: document.getElementById("reloadVideoApiConfigBtn"),
  saveVideoApiConfigBtn: document.getElementById("saveVideoApiConfigBtn"),
  videoPromptConfigPath: document.getElementById("videoPromptConfigPath"),
  videoSystemPrompt: document.getElementById("videoSystemPrompt"),
  videoUserPrompt: document.getElementById("videoUserPrompt"),
  reloadVideoPromptConfigBtn: document.getElementById("reloadVideoPromptConfigBtn"),
  saveVideoPromptConfigBtn: document.getElementById("saveVideoPromptConfigBtn"),
  videoMatchSummary: document.getElementById("videoMatchSummary"),
  videoMatchTable: document.getElementById("videoMatchTable"),
  videoProgressBar: document.getElementById("videoProgressBar"),
  videoProgressText: document.getElementById("videoProgressText"),
  videoProgressDetail: document.getElementById("videoProgressDetail"),
  startVideoBtn: document.getElementById("startVideoBtn"),
  refreshVideoJobBtn: document.getElementById("refreshVideoJobBtn"),
  reloadVideoFilesBtn: document.getElementById("reloadVideoFilesBtn"),
  openVideoOutputBtn: document.getElementById("openVideoOutputBtn"),
  videoLogBox: document.getElementById("videoLogBox"),
  videoOutputList: document.getElementById("videoOutputList"),

  comfyServerBadge: document.getElementById("comfyServerBadge"),
  comfyServerMeta: document.getElementById("comfyServerMeta"),
  comfyTemplateCount: document.getElementById("comfyTemplateCount"),
  comfyTemplateMeta: document.getElementById("comfyTemplateMeta"),
  comfyStatusBadge: document.getElementById("comfyStatusBadge"),
  comfyJobMeta: document.getElementById("comfyJobMeta"),
  comfyResultCount: document.getElementById("comfyResultCount"),
  comfyOutputRootValue: document.getElementById("comfyOutputRootValue"),
  comfyConfigPath: document.getElementById("comfyConfigPath"),
  comfyBaseUrl: document.getElementById("comfyBaseUrl"),
  comfyRootDir: document.getElementById("comfyRootDir"),
  comfyInputDir: document.getElementById("comfyInputDir"),
  comfyOutputDir: document.getElementById("comfyOutputDir"),
  comfyTempDir: document.getElementById("comfyTempDir"),
  comfyPathStyle: document.getElementById("comfyPathStyle"),
  comfyRequestTimeout: document.getElementById("comfyRequestTimeout"),
  comfyJobTimeout: document.getElementById("comfyJobTimeout"),
  comfyPollInterval: document.getElementById("comfyPollInterval"),
  comfyWorkflowManifestDir: document.getElementById("comfyWorkflowManifestDir"),
  comfyLinuxPathEnabled: document.getElementById("comfyLinuxPathEnabled"),
  comfyWsEnabled: document.getElementById("comfyWsEnabled"),
  reloadComfyConfigBtn: document.getElementById("reloadComfyConfigBtn"),
  saveComfyConfigBtn: document.getElementById("saveComfyConfigBtn"),
  checkComfyHealthBtn: document.getElementById("checkComfyHealthBtn"),
  reloadComfyTemplatesBtn: document.getElementById("reloadComfyTemplatesBtn"),
  comfyTemplateSelect: document.getElementById("comfyTemplateSelect"),
  comfyTemplateDescription: document.getElementById("comfyTemplateDescription"),
  applyComfyTemplateBindingsBtn: document.getElementById("applyComfyTemplateBindingsBtn"),
  comfyBindingsPreview: document.getElementById("comfyBindingsPreview"),
  comfyWorkflowType: document.getElementById("comfyWorkflowType"),
  comfyOutputPrefix: document.getElementById("comfyOutputPrefix"),
  comfyParamsJson: document.getElementById("comfyParamsJson"),
  comfyCsvPath: document.getElementById("comfyCsvPath"),
  comfyImageRootDir: document.getElementById("comfyImageRootDir"),
  comfyVideoRootDir: document.getElementById("comfyVideoRootDir"),
  comfyDefaultSeed: document.getElementById("comfyDefaultSeed"),
  comfyWorkflowJson: document.getElementById("comfyWorkflowJson"),
  comfyBindingsJson: document.getElementById("comfyBindingsJson"),
  cancelComfyJobBtn: document.getElementById("cancelComfyJobBtn"),
  retryComfyJobBtn: document.getElementById("retryComfyJobBtn"),
  retryFailedComfyJobBtn: document.getElementById("retryFailedComfyJobBtn"),
  resumePendingComfyJobBtn: document.getElementById("resumePendingComfyJobBtn"),
  exportComfyFailuresBtn: document.getElementById("exportComfyFailuresBtn"),
  refreshComfyJobBtn: document.getElementById("refreshComfyJobBtn"),
  startComfyJobBtn: document.getElementById("startComfyJobBtn"),
  comfyProgressBar: document.getElementById("comfyProgressBar"),
  comfyProgressText: document.getElementById("comfyProgressText"),
  comfyProgressDetail: document.getElementById("comfyProgressDetail"),
  comfyLogBox: document.getElementById("comfyLogBox"),
  comfyFailureList: document.getElementById("comfyFailureList"),
  reloadComfyFilesBtn: document.getElementById("reloadComfyFilesBtn"),
  openComfyOutputBtn: document.getElementById("openComfyOutputBtn"),
  comfyOutputList: document.getElementById("comfyOutputList"),
};

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function createBrowserSessionId() {
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID();
  }
  return `browser-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function normalizeDisplayPath(value) {
  const text = String(value || "").trim();
  if (!text) return "";

  const normalized = text.replaceAll("\\", "/");
  const markers = [
    "output/",
    "workflow/",
    "backend/",
    "frontend/",
    "uploads/",
    "outputs/",
    "comfyui_workflows/",
    "image_prompt_config.json",
    "image_edit_prompt_config.json",
    "video_prompt_config.json",
    "api_config.json",
    "comfyui_comm_config.json",
  ];

  for (const marker of markers) {
    const index = normalized.toLowerCase().indexOf(marker.toLowerCase());
    if (index >= 0) {
      return normalized.slice(index);
    }
  }

  return normalized;
}

function normalizeLogLines(lines) {
  return (lines || []).map((line) => normalizeDisplayPath(line));
}

function pathStyleGroupToggles(groupName) {
  return Array.from(document.querySelectorAll(`input[data-path-style-group="${groupName}"]`));
}

function setPathStyleGroupChecked(groupName, checked) {
  pathStyleGroupToggles(groupName).forEach((toggle) => {
    toggle.checked = checked;
  });
}

function isPathStyleGroupChecked(groupName) {
  return pathStyleGroupToggles(groupName).some((toggle) => toggle.checked);
}

async function postBrowserSession(path, payload) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    keepalive: true,
  });
  if (!res.ok) {
    throw new Error(`Browser session request failed: ${res.status}`);
  }
  return res.json();
}

async function registerBrowserSession() {
  if (!state.browserSessionId) {
    state.browserSessionId = createBrowserSessionId();
  }
  await postBrowserSession("/api/browser-session/register", { sessionId: state.browserSessionId });
}

async function heartbeatBrowserSession() {
  if (!state.browserSessionId) return;
  try {
    await postBrowserSession("/api/browser-session/heartbeat", { sessionId: state.browserSessionId });
  } catch {
    // Ignore transient heartbeat failures; the next tick or page refresh can recover.
  }
}

function closeBrowserSession() {
  if (!state.browserSessionId) return;
  const payload = JSON.stringify({ sessionId: state.browserSessionId });
  const blob = new Blob([payload], { type: "application/json" });
  if (navigator.sendBeacon) {
    navigator.sendBeacon("/api/browser-session/close", blob);
    return;
  }
  fetch("/api/browser-session/close", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: payload,
    keepalive: true,
  }).catch(() => {});
}

function startBrowserHeartbeat() {
  if (state.browserHeartbeatTimer) {
    clearInterval(state.browserHeartbeatTimer);
  }
  state.browserHeartbeatTimer = setInterval(() => {
    heartbeatBrowserSession();
  }, 5000);
}

async function shutdownApp() {
  if (state.browserHeartbeatTimer) {
    clearInterval(state.browserHeartbeatTimer);
    state.browserHeartbeatTimer = null;
  }

  try {
    await fetch("/api/app/terminate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId: state.browserSessionId || "" }),
      keepalive: true,
    });
  } catch {
    // Ignore fetch errors here because the backend may already be shutting down.
  }

  closeBrowserSession();

  try {
    window.open("", "_self");
    window.close();
  } catch {
    // Ignore browser close restrictions and fall through to the fallback UI.
  }

  setTimeout(() => {
    document.body.innerHTML = `
      <main style="font-family: sans-serif; padding: 32px; line-height: 1.6;">
        <h1>服务已退出</h1>
        <p>后端进程已收到退出指令。这个页面现在可以手动关闭。</p>
      </main>
    `;
  }, 150);
}

function isRealApiMode(apiKeyInput, mockCheckbox) {
  return apiKeyInput.value.trim().length > 0 && !mockCheckbox.checked;
}

function isRemoteHttpUrl(value) {
  try {
    const parsed = new URL(String(value).trim());
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

function inferNameFromUrl(url, fallbackPrefix, index) {
  const parsed = new URL(url);
  const rawName = decodeURIComponent(parsed.pathname.split("/").pop() || "").trim();
  return rawName || `${fallbackPrefix}-${index + 1}`;
}

function parseRemoteMediaLines(text, fallbackPrefix) {
  return String(text || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const parts = line.includes("|") ? line.split("|") : [line];
      const url = String(parts.at(-1) || "").trim();
      if (!isRemoteHttpUrl(url)) {
        throw new Error(`发现无效媒体 URL：${url}`);
      }
      const name = String(parts.length > 1 ? parts.slice(0, -1).join("|") : "").trim() || inferNameFromUrl(url, fallbackPrefix, index);
      return { name, url };
    });
}

function getImageRemoteItems() {
  return parseRemoteMediaLines(els.imageUrlInput.value, "image");
}

function getImageEditRemoteItems() {
  return parseRemoteMediaLines(els.imageEditUrlInput.value, "image-edit");
}

function getVideoRemoteItems() {
  return parseRemoteMediaLines(els.videoUrlInput.value, "video");
}

function getReferenceRemoteItems() {
  return parseRemoteMediaLines(els.referenceUrlInput.value, "reference");
}

function getImageItemsForSubmission() {
  const remoteItems = getImageRemoteItems();
  if (remoteItems.length) {
    return remoteItems.map((item) => ({ name: item.name, imageUrl: item.url }));
  }
  return null;
}

function getImageEditItemsForSubmission() {
  const remoteItems = getImageEditRemoteItems();
  if (remoteItems.length) {
    return remoteItems.map((item) => ({ name: item.name, imageUrl: item.url }));
  }
  return null;
}

function getVideoAndReferenceEntries() {
  const remoteVideos = getVideoRemoteItems();
  const remoteReferences = getReferenceRemoteItems();
  return {
    videos: remoteVideos.length
      ? remoteVideos
      : state.video.videoFiles.map((file) => ({
          name: file.name,
          file,
          sourcePath: resolveSourcePath(file, els.videoSourceRootDir.value),
          relativePath: getLocalRelativePath(file),
        })),
    references: remoteReferences.length
      ? remoteReferences
      : state.video.referenceFiles.map((file) => ({
          name: file.name,
          file,
          sourcePath: resolveSourcePath(file, els.referenceSourceRootDir.value),
          relativePath: getLocalRelativePath(file),
        })),
  };
}

function getLocalSourcePath(file) {
  return typeof file?.path === "string" ? file.path.trim() : "";
}

function getLocalRelativePath(file) {
  return typeof file?.webkitRelativePath === "string" ? file.webkitRelativePath.trim() : "";
}

function normalizeJoinedPath(rootDir, childPath) {
  const root = String(rootDir || "").trim().replace(/[\\/]+$/, "");
  const child = String(childPath || "").trim().replaceAll("\\", "/").replace(/^\/+/, "");
  if (!root || !child) return "";
  return `${root}/${child}`;
}

function resolveSourcePath(file, configuredRootDir) {
  const directPath = getLocalSourcePath(file);
  if (directPath) return directPath;

  const relativePath = getLocalRelativePath(file);
  if (relativePath && configuredRootDir) {
    return normalizeJoinedPath(configuredRootDir, relativePath);
  }

  if (configuredRootDir && file?.name) {
    return normalizeJoinedPath(configuredRootDir, file.name);
  }

  return "";
}

function getFileExtension(file) {
  const match = file.name.match(/\.([^.]+)$/);
  if (match) return match[1].toUpperCase();
  if (file.type) return file.type.split("/").pop().toUpperCase();
  return "FILE";
}

function summarizeFormats(files) {
  const formats = [...new Set(files.map(getFileExtension))];
  if (!formats.length) return "FILE";
  const visible = formats.slice(0, 4);
  return formats.length > 4
    ? `${visible.join(" / ")} +${formats.length - 4}`
    : visible.join(" / ");
}

function toReadableJobStatus(status) {
  switch (status) {
    case "running":
      return "运行中";
    case "completed":
      return "已完成";
    case "partial":
      return "部分成功";
    case "failed":
      return "失败";
    case "queued":
      return "排队中";
    case "cancelled":
      return "已取消";
    case "timeout":
      return "超时";
    default:
      return "待开始";
  }
}

function toReadableMatchStatus(status) {
  switch (status) {
    case "matched":
      return "已匹配";
    case "partial_match":
      return "部分匹配";
    case "missing_reference":
      return "缺少参考图";
    case "naming_conflict":
      return "命名冲突";
    default:
      return "未扫描";
  }
}

function statusClass(status) {
  switch (status) {
    case "matched":
      return "status-matched";
    case "partial_match":
      return "status-partial";
    case "missing_reference":
      return "status-missing";
    case "naming_conflict":
      return "status-conflict";
    default:
      return "status-partial";
  }
}

function renderPromptModuleOverview() {
  els.promptModuleOverview.innerHTML = Object.entries(PROMPT_MODULES).map(([key, moduleMeta], index) => `
    <article class="module-card ${state.activePromptModule === key ? "is-active" : ""}">
      <div>
        <p class="panel-kicker">Module ${String(index + 1).padStart(2, "0")}</p>
        <strong>${escapeHtml(moduleMeta.title)}</strong>
        <small>${escapeHtml(moduleMeta.description)}</small>
      </div>
      <button type="button" class="btn btn-ghost" data-open-prompt-module="${escapeHtml(key)}">
        进入子模块
      </button>
    </article>
  `).join("");
}

function renderPromptModuleTabs() {
  els.promptModuleTabs.innerHTML = Object.entries(PROMPT_MODULES).map(([key, moduleMeta]) => `
    <button
      type="button"
      class="module-tab ${state.activePromptModule === key ? "is-active" : ""}"
      data-prompt-module="${escapeHtml(key)}"
      aria-pressed="${state.activePromptModule === key ? "true" : "false"}"
    >
      <strong>${escapeHtml(moduleMeta.title)}</strong>
      <small>${escapeHtml(moduleMeta.description)}</small>
    </button>
  `).join("");
}

function updatePromptModuleNavigation() {
  els.promptModuleOverview.querySelectorAll(".module-card").forEach((card) => {
    const button = card.querySelector("[data-open-prompt-module]");
    if (!button) return;
    card.classList.toggle("is-active", button.dataset.openPromptModule === state.activePromptModule);
  });

  els.promptModuleTabs.querySelectorAll("[data-prompt-module]").forEach((button) => {
    const isActive = button.dataset.promptModule === state.activePromptModule;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-pressed", isActive ? "true" : "false");
  });
}

function updateViewHeader() {
  if (state.currentView === "promptStudio") {
    const moduleMeta = PROMPT_MODULES[state.activePromptModule];
    els.viewTitle.textContent = VIEW_META.promptStudio.title;
    els.viewSubtitle.textContent = `${moduleMeta.title} · ${moduleMeta.subtitle}`;
    return;
  }

  if (state.currentView === "clipStudio") {
    els.viewTitle.textContent = VIEW_META.clipStudio.title;
    els.viewSubtitle.textContent = VIEW_META.clipStudio.subtitle;
    return;
  }

  if (state.currentView === "comfyStudio") {
    els.viewTitle.textContent = VIEW_META.comfyStudio.title;
    els.viewSubtitle.textContent = VIEW_META.comfyStudio.subtitle;
    return;
  }

  els.viewTitle.textContent = VIEW_META.home.title;
  els.viewSubtitle.textContent = VIEW_META.home.subtitle;
}

function setActivePromptModule(moduleKey) {
  if (!PROMPT_MODULES[moduleKey]) return;
  state.activePromptModule = moduleKey;
  Object.entries(els.promptModulePanels).forEach(([key, panel]) => {
    panel.hidden = key !== moduleKey;
  });
  updatePromptModuleNavigation();
  updateViewHeader();
}

function setView(view, moduleKey = state.activePromptModule) {
  state.currentView = view;
  els.homeView.hidden = view !== "home";
  els.promptStudioView.hidden = view !== "promptStudio";
  els.clipStudioView.hidden = view !== "clipStudio";
  els.comfyStudioView.hidden = view !== "comfyStudio";
  els.navBackBtn.disabled = view === "home";

  if (view === "promptStudio") {
    setActivePromptModule(moduleKey);
    return;
  }

  updateViewHeader();
}

function setModuleModeBadge(apiInput, mockCheckbox, badgeEl) {
  const hasKey = apiInput.value.trim().length > 0;
  const useMock = mockCheckbox.checked;
  if (useMock && hasKey) {
    badgeEl.textContent = "Hybrid";
  } else if (useMock) {
    badgeEl.textContent = "Mock";
  } else {
    badgeEl.textContent = "API";
  }
}

function renderFileRows(files) {
  return files.map((file) => `
    <div class="file-row">
      <div>
        <strong>${escapeHtml(file.name)}</strong>
        <small>${formatBytes(file.size)}</small>
      </div>
      <small>${escapeHtml(file.type || getFileExtension(file))}</small>
    </div>
  `).join("");
}

function renderStackList(files, target, emptyText, options = {}) {
  if (!files.length) {
    target.classList.add("empty");
    target.textContent = emptyText;
    return;
  }

  const {
    label = "文件",
    previewCount = 4,
    expanded = false,
    toggleKey = "",
  } = options;

  const previewFiles = files.slice(0, previewCount);
  const remainingFiles = files.slice(previewCount);
  const totalBytes = files.reduce((sum, file) => sum + (file.size || 0), 0);

  target.classList.remove("empty");
  target.innerHTML = `
    <div class="file-summary-card">
      <div class="file-summary-copy">
        <strong>${files.length} 个${escapeHtml(label)}</strong>
        <small>总大小 ${formatBytes(totalBytes)} · 格式 ${escapeHtml(summarizeFormats(files))}</small>
      </div>
      ${remainingFiles.length ? `
        <button
          type="button"
          class="btn btn-ghost file-toggle"
          data-list-toggle="${escapeHtml(toggleKey)}"
          aria-expanded="${expanded ? "true" : "false"}"
        >
          ${expanded ? "收起" : `展开 (${files.length})`}
        </button>
      ` : `
        <span class="chip chip-soft">已全部显示</span>
      `}
    </div>
    <div class="file-preview-note">默认显示前 ${Math.min(files.length, previewCount)} 项</div>
    <div class="file-preview-list">
      ${renderFileRows(previewFiles)}
    </div>
    ${remainingFiles.length ? `
      <div class="file-expand-shell ${expanded ? "is-open" : ""}">
        <div class="file-expand-note">其余 ${remainingFiles.length} 个${escapeHtml(label)}</div>
        ${expanded ? `<div class="file-list-scroll">${renderFileRows(remainingFiles)}</div>` : ""}
      </div>
    ` : ""}
  `;
}

function listViewConfig(toggleKey) {
  switch (toggleKey) {
    case "image":
      return {
        files: state.image.files,
        expanded: state.image.filesExpanded,
        target: els.imageFileList,
        emptyText: "未选择图片",
        label: "图片",
      };
    case "imageEdit":
      return {
        files: state.imageEdit.files,
        expanded: state.imageEdit.filesExpanded,
        target: els.imageEditFileList,
        emptyText: "未选择图片",
        label: "图片",
      };
    case "video":
      return {
        files: state.video.videoFiles,
        expanded: state.video.videoFilesExpanded,
        target: els.videoFileList,
        emptyText: "未选择视频",
        label: "视频",
      };
    case "reference":
      return {
        files: state.video.referenceFiles,
        expanded: state.video.referenceFilesExpanded,
        target: els.referenceFileList,
        emptyText: "未选择参考图",
        label: "参考图",
      };
    default:
      return null;
  }
}

function renderNamedStackList(toggleKey) {
  const config = listViewConfig(toggleKey);
  if (!config) return;
  renderStackList(config.files, config.target, config.emptyText, {
    label: config.label,
    previewCount: 4,
    expanded: config.expanded,
    toggleKey,
  });
}

function setListExpanded(toggleKey, expanded) {
  switch (toggleKey) {
    case "image":
      state.image.filesExpanded = expanded;
      break;
    case "imageEdit":
      state.imageEdit.filesExpanded = expanded;
      break;
    case "video":
      state.video.videoFilesExpanded = expanded;
      break;
    case "reference":
      state.video.referenceFilesExpanded = expanded;
      break;
    default:
      return;
  }
  renderNamedStackList(toggleKey);
}

function renderMatchRows(items) {
  return items.map((item) => `
    <div class="match-row">
      <div>
        <strong>${escapeHtml(item.video)}</strong>
        <small>${item.canGenerate ? "可生成" : "需修正"}</small>
      </div>
      <div>${escapeHtml(item.matchKey)}</div>
      <div>${escapeHtml(item.referenceMain || "-")}</div>
      <div>${escapeHtml(item.referenceAlt1 || "-")}</div>
      <div>${escapeHtml(item.referenceAlt2 || "-")}</div>
      <div><span class="status-pill ${statusClass(item.status)}">${toReadableMatchStatus(item.status)}</span></div>
    </div>
  `).join("");
}

function renderOutputList(files, target, counter, emptyText) {
  counter.textContent = String(files.length);
  if (!files.length) {
    target.classList.add("empty");
    target.textContent = emptyText;
    return;
  }
  target.classList.remove("empty");
  target.innerHTML = files.map((file) => `
    <div class="output-row">
      <div>
        <strong>${escapeHtml(file.name)}</strong>
        <small>已生成</small>
      </div>
      <a href="${file.url}" target="_blank" rel="noreferrer">打开</a>
    </div>
  `).join("");
}

function renderImageJob(job) {
  state.image.job = job;
  const percent = job.total ? Math.round((job.progress / job.total) * 100) : 0;
  els.imageProgressBar.style.width = `${percent}%`;
  els.imageStatusBadge.textContent = toReadableJobStatus(job.status);
  els.imageJobMeta.textContent = job.id ? `Job ${job.id} · ${job.progress}/${job.total}` : "未运行";
  els.imageProgressText.textContent = toReadableJobStatus(job.status);
  els.imageProgressDetail.textContent = job.status === "completed"
    ? "已完成"
    : job.status === "failed"
      ? `任务失败：${job.error || "unknown"}`
      : job.status === "running"
        ? "处理中"
        : "等待";
  els.imageOutputRootValue.textContent = normalizeDisplayPath(job.output_dir) || normalizeDisplayPath(els.imageOutputDir.value.trim()) || "未设置";
}

function renderImageEditJob(job) {
  state.imageEdit.job = job;
  const percent = job.total ? Math.round((job.progress / job.total) * 100) : 0;
  els.imageEditProgressBar.style.width = `${percent}%`;
  els.imageEditStatusBadge.textContent = toReadableJobStatus(job.status);
  els.imageEditJobMeta.textContent = job.id ? `Job ${job.id} · ${job.progress}/${job.total}` : "未运行";
  els.imageEditProgressText.textContent = toReadableJobStatus(job.status);
  els.imageEditProgressDetail.textContent = job.status === "completed"
    ? "已完成"
    : job.status === "failed"
      ? `任务失败：${job.error || "unknown"}`
      : job.status === "running"
        ? "处理中"
        : "等待";
  els.imageEditOutputRootValue.textContent = normalizeDisplayPath(job.output_dir) || normalizeDisplayPath(els.imageEditOutputDir.value.trim()) || "未设置";
}

function renderVideoJob(job) {
  state.video.job = job;
  const percent = job.total ? Math.round((job.progress / job.total) * 100) : 0;
  els.videoProgressBar.style.width = `${percent}%`;
  els.videoProgressText.textContent = toReadableJobStatus(job.status);
  els.videoProgressDetail.textContent = job.status === "completed"
    ? "已完成"
    : job.status === "failed"
      ? `任务失败：${job.error || "unknown"}`
      : job.status === "running"
        ? "处理中"
        : "等待";
}

function setImageLog(lines) {
  const normalizedLines = normalizeLogLines(lines);
  els.imageLogBox.textContent = normalizedLines.length ? normalizedLines.join("\n") : "暂无日志";
}

function setImageEditLog(lines) {
  const normalizedLines = normalizeLogLines(lines);
  els.imageEditLogBox.textContent = normalizedLines.length ? normalizedLines.join("\n") : "暂无日志";
}

function setVideoLog(lines) {
  const normalizedLines = normalizeLogLines(lines);
  els.videoLogBox.textContent = normalizedLines.length ? normalizedLines.join("\n") : "暂无日志";
}

function setComfyLog(lines) {
  const normalizedLines = normalizeLogLines(lines);
  els.comfyLogBox.textContent = normalizedLines.length ? normalizedLines.join("\n") : "暂无日志";
}

function selectedComfyTemplate() {
  return state.comfy.templates.find((template) => template.key === els.comfyTemplateSelect.value) || null;
}

function formatTemplateBindings(template) {
  if (!template?.bindings || typeof template.bindings !== "object" || Array.isArray(template.bindings)) {
    return "";
  }
  return JSON.stringify(template.bindings, null, 2);
}

function renderComfyTemplateDescription() {
  const template = selectedComfyTemplate();
  els.comfyTemplateDescription.textContent = template
    ? [
      template.workflow_type || "未声明类型",
      template.source_type === "raw_api_workflow" ? "自动识别 API 工作流" : "Manifest 模板",
      template.bindings_count ? `${template.bindings_count} 个绑定` : "无绑定",
      template.bindings_inferred ? "含自动推断绑定" : "",
      template.description || "无描述",
    ].filter(Boolean).join(" · ")
    : "当前没有可用模板。你也可以直接在右侧填写 Workflow JSON 与 Bindings JSON。";
  if (template && !els.comfyWorkflowType.value.trim()) {
    els.comfyWorkflowType.value = template.workflow_type || "";
  }
  const bindingsText = formatTemplateBindings(template);
  els.comfyBindingsPreview.textContent = bindingsText || "当前模板没有显式 bindings。";
  els.applyComfyTemplateBindingsBtn.disabled = !bindingsText;
}

function renderComfyTemplates(data) {
  state.comfy.templates = data.templates || [];
  els.comfyTemplateCount.textContent = String(state.comfy.templates.length);
  els.comfyTemplateMeta.textContent = normalizeDisplayPath(data.path) || "未找到模板目录";

  if (!state.comfy.templates.length) {
    els.comfyTemplateSelect.innerHTML = `<option value="">无模板，可直接填写 Workflow JSON</option>`;
    renderComfyTemplateDescription();
    return;
  }

  els.comfyTemplateSelect.innerHTML = state.comfy.templates.map((template) => `
    <option value="${escapeHtml(template.key)}">${escapeHtml(template.source_type === "raw_api_workflow" ? `[自动] ${template.label || template.key}` : (template.label || template.key))}</option>
  `).join("");
  renderComfyTemplateDescription();
}

function renderComfyHealth(data) {
  state.comfy.health = data || null;
  const online = Boolean(data?.online);
  els.comfyServerBadge.textContent = online ? "在线" : "离线";
  if (!online) {
    els.comfyServerMeta.textContent = data?.error || "无法连接";
    return;
  }
  const queuePending = Number(data?.queue_pending || 0);
  const queueRunning = Number(data?.queue_running || 0);
  const ws = data?.ws || {};
  const wsText = ws.enabled
    ? (ws.connected ? "WS 已连接" : "WS 启动中")
    : "WS 已关闭";
  els.comfyServerMeta.textContent = `${queuePending} 待执行 / ${queueRunning} 运行中 · ${wsText}`;
}

function toReadableFailureStage(stage) {
  return {
    INPUT_PREPARE: "输入准备",
    WORKFLOW_BIND: "工作流绑定",
    SUBMIT: "提交任务",
    RUNNING: "执行阶段",
    RESULT_FETCH: "结果回收",
    TIMEOUT: "任务超时",
  }[String(stage || "").trim()] || String(stage || "未知阶段");
}

function renderComfyFailures(failures) {
  const items = Array.isArray(failures) ? failures : [];
  if (!items.length) {
    els.comfyFailureList.classList.add("empty");
    els.comfyFailureList.textContent = "失败项会显示在这里";
    return;
  }

  els.comfyFailureList.classList.remove("empty");
  els.comfyFailureList.innerHTML = items.map((item) => {
    const stage = toReadableFailureStage(item.stage);
    const code = item.error_code || "UNKNOWN";
    const promptId = item.prompt_id ? ` · Prompt ${escapeHtml(item.prompt_id)}` : "";
    const retryable = item.retryable ? "可重试" : "需先修正配置";
    const detail = item.detail ? `<small>${escapeHtml(typeof item.detail === "string" ? item.detail : JSON.stringify(item.detail))}</small>` : "";
    return `
      <div class="output-row failure-row">
        <div>
          <strong>第 ${escapeHtml(item.row_index)} 行 · ${escapeHtml(item.name || "-")}</strong>
          <small>${escapeHtml(stage)} · ${escapeHtml(code)}${promptId}</small>
          <small>${escapeHtml(item.message || "unknown error")}</small>
          ${detail}
        </div>
        <span class="status-pill ${item.retryable ? "status-partial" : "status-missing"}">${escapeHtml(retryable)}</span>
      </div>
    `;
  }).join("");
}

function renderComfyJob(job) {
  state.comfy.job = job;
  const percent = job.total ? Math.round((job.progress / job.total) * 100) : 0;
  const meta = job.meta || {};
  const failures = Array.isArray(job.failures) ? job.failures : [];
  const selectedRowCount = Number(meta.selected_row_count || meta.row_count || job.total || 0);
  els.comfyProgressBar.style.width = `${percent}%`;
  els.comfyStatusBadge.textContent = toReadableJobStatus(job.status);
  els.comfyJobMeta.textContent = job.id
    ? `Job ${job.id}${meta.prompt_id ? ` · Prompt ${meta.prompt_id}` : ""}${selectedRowCount ? ` · ${job.progress}/${selectedRowCount}` : ""}`
    : "未运行";
  els.comfyProgressText.textContent = toReadableJobStatus(job.status);
  if (job.status === "completed") {
    els.comfyProgressDetail.textContent = normalizeDisplayPath(meta.result_path || job.output_dir) || "已完成";
  } else if (job.status === "partial") {
    const firstFailure = failures[0];
    const failureText = firstFailure
      ? `第 ${firstFailure.row_index} 行失败：${firstFailure.message || job.error || "unknown"}`
      : (job.error || "存在失败项");
    els.comfyProgressDetail.textContent = `${normalizeDisplayPath(meta.result_path || job.output_dir) || "已有部分结果"} · ${failureText}`;
  } else if (job.status === "failed") {
    const firstFailure = failures[0];
    els.comfyProgressDetail.textContent = firstFailure
      ? `失败：第 ${firstFailure.row_index} 行 · ${firstFailure.message || job.error || "unknown"}`
      : `任务失败：${job.error || "unknown"}`;
  } else if (job.status === "cancelled") {
    els.comfyProgressDetail.textContent = "任务已取消";
  } else if (job.status === "timeout") {
    els.comfyProgressDetail.textContent = "任务超时";
  } else if (meta.current_node) {
    els.comfyProgressDetail.textContent = `当前节点：${meta.current_node}`;
  } else if (meta.queue_pending || meta.queue_running) {
    els.comfyProgressDetail.textContent = `队列：${meta.queue_pending || 0} 待执行 / ${meta.queue_running || 0} 运行中`;
  } else {
    els.comfyProgressDetail.textContent = "等待";
  }
  els.comfyOutputRootValue.textContent = normalizeDisplayPath(job.output_dir)
    || normalizeDisplayPath(els.comfyOutputDir.value.trim())
    || "未设置";
  renderComfyFailures(failures);
}

function getClipPreset(key = state.clip.preset) {
  return state.clip.presets.find((preset) => preset.key === key) || null;
}

function renderClipPresetDescription() {
  const preset = getClipPreset();
  els.clipPresetDescription.textContent = preset
    ? `${preset.group} · ${preset.description}`
    : "暂无预设";
}

function updateClipSummary() {
  const preset = getClipPreset();
  const isMergeMode = state.clip.mode === "merge";
  els.clipPresetBadge.textContent = preset?.label || "未选择";
  els.clipPresetMeta.textContent = preset ? `${preset.group} · ${preset.description}` : "读取中";
  els.clipInputCount.textContent = isMergeMode ? "2" : "1";
  els.clipInputMeta.textContent = isMergeMode
    ? "双目录配对"
    : "单目录裁切";
  els.clipOutputRootValue.textContent = normalizeDisplayPath(els.clipOutputDir.value.trim()) || "output/video_clip";
}

function renderClipPresetOptions() {
  const availablePresets = state.clip.presets.filter((preset) => (
    state.clip.mode === "merge"
      ? preset.mode === "merge_pairwise"
      : preset.mode !== "merge_pairwise"
  ));

  if (!availablePresets.length) {
    els.clipPresetSelect.innerHTML = "";
    state.clip.preset = "";
    renderClipPresetDescription();
    updateClipSummary();
    return;
  }

  if (!availablePresets.some((preset) => preset.key === state.clip.preset)) {
    state.clip.preset = availablePresets[0].key;
  }

  const groups = new Map();
  availablePresets.forEach((preset) => {
    const group = groups.get(preset.group) || [];
    group.push(preset);
    groups.set(preset.group, group);
  });

  els.clipPresetSelect.innerHTML = [...groups.entries()].map(([group, presets]) => `
    <optgroup label="${escapeHtml(group)}">
      ${presets.map((preset) => `
        <option value="${escapeHtml(preset.key)}">${escapeHtml(preset.label)}</option>
      `).join("")}
    </optgroup>
  `).join("");
  els.clipPresetSelect.value = state.clip.preset;
  renderClipPresetDescription();
  updateClipSummary();
}

function setClipMode(mode) {
  if (!["single", "merge"].includes(mode)) return;
  state.clip.mode = mode;
  const isSingleMode = mode === "single";

  els.clipSingleModeBtn.classList.toggle("btn-primary", isSingleMode);
  els.clipSingleModeBtn.classList.toggle("btn-ghost", !isSingleMode);
  els.clipMergeModeBtn.classList.toggle("btn-primary", !isSingleMode);
  els.clipMergeModeBtn.classList.toggle("btn-ghost", isSingleMode);
  els.clipSingleModeBtn.setAttribute("aria-pressed", isSingleMode ? "true" : "false");
  els.clipMergeModeBtn.setAttribute("aria-pressed", isSingleMode ? "false" : "true");
  els.clipSingleInputField.hidden = !isSingleMode;
  els.clipMergeInputFields.hidden = isSingleMode;
  els.clipModeDescription.textContent = isSingleMode
    ? "单目录批量裁切。"
    : "双目录顺序合并。";

  renderClipPresetOptions();
}

async function loadClipPresets() {
  const res = await fetch("/api/clip/presets");
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || "无法读取剪辑预设");
  }

  state.clip.presets = data.presets || [];
  if (!getClipPreset(state.clip.preset)) {
    state.clip.preset = state.clip.presets.find((preset) => preset.key === "first_half_opencv")?.key
      || state.clip.presets[0]?.key
      || "";
  }
  setClipMode(state.clip.mode);
}

function setClipLog(lines) {
  const normalizedLines = normalizeLogLines(lines);
  els.clipLogBox.textContent = normalizedLines.length ? normalizedLines.join("\n") : "暂无日志";
}

function clipPathName(pathText) {
  return String(pathText || "").replaceAll("\\", "/").split("/").filter(Boolean).at(-1) || "-";
}

function renderClipOutputs(items) {
  state.clip.outputs = items || [];
  const completedCount = state.clip.outputs.filter((item) => item.status === "done").length;
  els.clipResultCount.textContent = String(completedCount);

  if (!state.clip.outputs.length) {
    els.clipOutputList.classList.add("empty");
    els.clipOutputList.textContent = "结果将在这里显示";
    return;
  }

  els.clipOutputList.classList.remove("empty");
  els.clipOutputList.innerHTML = state.clip.outputs.map((item) => {
    const source = item.source
      ? clipPathName(item.source)
      : `${clipPathName(item.source_a)} + ${clipPathName(item.source_b)}`;
    const outputVideo = item.output_video ? `视频：${clipPathName(item.output_video)}` : "未生成输出视频";
    const preview = item.preview_image ? ` · 预览：${clipPathName(item.preview_image)}` : "";
    const isDone = item.status === "done";
    return `
      <div class="output-row">
        <div>
          <strong>${escapeHtml(source)}</strong>
          <small>${escapeHtml(item.detail || outputVideo)}</small>
          <small>${escapeHtml(`${outputVideo}${preview}`)}</small>
        </div>
        <span class="status-pill ${isDone ? "status-matched" : "status-missing"}">${isDone ? "已完成" : "失败"}</span>
      </div>
    `;
  }).join("");
}

function renderClipJob(job) {
  state.clip.job = job;
  const percent = job.total ? Math.round((job.progress / job.total) * 100) : 0;
  els.clipProgressBar.style.width = `${percent}%`;
  els.clipStatusBadge.textContent = toReadableJobStatus(job.status);
  els.clipJobMeta.textContent = job.id
    ? job.total
      ? `Job ${job.id} · ${job.progress}/${job.total}`
      : `Job ${job.id} · 扫描中`
    : "未运行";
  els.clipProgressText.textContent = toReadableJobStatus(job.status);
  els.clipProgressDetail.textContent = job.status === "completed"
    ? "已完成"
    : job.status === "failed"
      ? `任务失败：${job.error || "unknown"}`
      : job.status === "running"
        ? "处理中"
        : "等待";
  els.clipOutputRootValue.textContent = normalizeDisplayPath(job.output_dir)
    || normalizeDisplayPath(els.clipOutputDir.value.trim())
    || "output/video_clip";

  if (Array.isArray(job.outputs)) {
    renderClipOutputs(job.outputs);
  }
}

async function startClipJob() {
  try {
    const preset = getClipPreset();
    if (!preset) {
      throw new Error("请先选择剪辑预设。");
    }

    const outputDir = els.clipOutputDir.value.trim() || "output/video_clip";
    if (state.clip.mode === "single" && !els.clipInputDir.value.trim()) {
      throw new Error("请填写视频输入文件夹路径。");
    }
    if (state.clip.mode === "merge" && (!els.clipInputDirA.value.trim() || !els.clipInputDirB.value.trim())) {
      throw new Error("请同时填写文件夹 A 和文件夹 B 的路径。");
    }

    els.startClipBtn.disabled = true;
    els.clipProgressText.textContent = "准备中";
    els.clipProgressDetail.textContent = "正在提交任务。";

    const res = await fetch("/api/clip/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        preset: preset.key,
        inputDir: els.clipInputDir.value.trim(),
        inputDirA: els.clipInputDirA.value.trim(),
        inputDirB: els.clipInputDirB.value.trim(),
        outputDir,
        pathStyle: isPathStyleGroupChecked("clip") ? "linux" : "",
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || "启动剪辑任务失败");
    }

    state.clip.jobId = data.jobId;
    renderClipJob(data.job);
    setClipLog(data.job?.logs || []);
    pollClipJob();
  } catch (error) {
    els.startClipBtn.disabled = false;
    alert(error.message);
  }
}

async function pollClipJob() {
  if (state.clip.pollTimer) clearInterval(state.clip.pollTimer);
  const tick = async () => {
    if (!state.clip.jobId) return;
    const res = await fetch(`/api/jobs/${state.clip.jobId}`);
    const job = await res.json();
    renderClipJob(job);
    setClipLog(job.logs || []);

    if (job.status === "completed" || job.status === "failed") {
      els.startClipBtn.disabled = false;
      clearInterval(state.clip.pollTimer);
      state.clip.pollTimer = null;
    }
  };
  await tick();
  state.clip.pollTimer = setInterval(tick, 1000);
}

async function openClipOutput() {
  if (!state.clip.jobId) {
    alert("请先运行剪辑任务");
    return;
  }
  const res = await fetch(`/api/jobs/${state.clip.jobId}/open-output`, { method: "POST" });
  const data = await res.json();
  if (!res.ok) {
    alert(data.error || "无法打开输出目录");
  }
}

function getImagePromptPayload() {
  return {
    system_prompt: els.imageSystemPrompt.value,
    user_text: els.imageUserPrompt.value,
  };
}

function getImageEditPromptPayload() {
  return {
    system_prompt: els.imageEditSystemPrompt.value,
    user_text: els.imageEditUserPrompt.value,
  };
}

function getVideoPromptPayload() {
  return {
    system_prompt: els.videoSystemPrompt.value,
    user_text: els.videoUserPrompt.value,
  };
}

function renderImagePromptConfig(data) {
  state.image.promptConfig = data.config || null;
  els.imagePromptConfigPath.textContent = normalizeDisplayPath(data.path) || "未找到配置文件";
  els.imageSystemPrompt.value = data.config?.system_prompt || "";
  els.imageUserPrompt.value = data.config?.user_text || "";
}

function renderImageEditPromptConfig(data) {
  state.imageEdit.promptConfig = data.config || null;
  els.imageEditPromptConfigPath.textContent = normalizeDisplayPath(data.path) || "未找到配置文件";
  els.imageEditSystemPrompt.value = data.config?.system_prompt || "";
  els.imageEditUserPrompt.value = data.config?.user_text || "";
}

function renderVideoPromptConfig(data) {
  state.video.promptConfig = data.config || null;
  els.videoPromptConfigPath.textContent = normalizeDisplayPath(data.path) || "未找到配置文件";
  els.videoSystemPrompt.value = data.config?.system_prompt || "";
  els.videoUserPrompt.value = data.config?.user_text || "";
}

async function loadDefaults() {
  const res = await fetch("/api/config");
  const data = await res.json();
  state.defaults = data;

  els.imageBaseUrl.value = data.baseUrl || "";
  els.imageModel.value = data.model || "";
  els.imageOutputDir.value = data.imageOutputRoot || data.outputRoot || "";
  els.imageUseMock.checked = data.useMock ?? true;
  els.imageApiKey.placeholder = "直接粘贴 API Key";
  els.imageOutputRootValue.textContent = data.imageOutputRoot || data.outputRoot || "未设置";

  els.videoBaseUrl.value = data.baseUrl || "";
  els.videoModel.value = data.model || "";
  els.videoOutputDir.value = data.videoOutputRoot || data.outputRoot || "";
  els.videoUseMock.checked = data.useMock ?? true;
  els.videoApiKey.placeholder = "直接粘贴 API Key";

  setModuleModeBadge(els.imageApiKey, els.imageUseMock, els.imageModeBadge);
  setModuleModeBadge(els.videoApiKey, els.videoUseMock, els.videoModeBadge);
}

async function loadImagePromptConfig() {
  const res = await fetch("/api/prompt-config/image");
  const data = await res.json();
  renderImagePromptConfig(data);
}

async function loadImageEditPromptConfig() {
  const res = await fetch("/api/prompt-config/image_edit");
  const data = await res.json();
  renderImageEditPromptConfig(data);
}

async function loadVideoPromptConfig() {
  const res = await fetch("/api/prompt-config/video");
  const data = await res.json();
  renderVideoPromptConfig(data);
}

async function savePromptConfig(kind, config) {
  const res = await fetch(`/api/prompt-config/${kind}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config }),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || "保存配置失败");
  }
  return data;
}

async function saveImagePromptConfig() {
  try {
    const data = await savePromptConfig("image", {
      ...(state.image.promptConfig || {}),
      ...getImagePromptPayload(),
    });
    renderImagePromptConfig(data);
    alert("图片 Prompt 配置已保存");
  } catch (error) {
    alert(error.message);
  }
}

async function saveImageEditPromptConfig() {
  try {
    const data = await savePromptConfig("image_edit", {
      ...(state.imageEdit.promptConfig || {}),
      ...getImageEditPromptPayload(),
    });
    renderImageEditPromptConfig(data);
    alert("图生图 Prompt 配置已保存");
  } catch (error) {
    alert(error.message);
  }
}

async function saveVideoPromptConfig() {
  try {
    const data = await savePromptConfig("video", {
      ...(state.video.promptConfig || {}),
      ...getVideoPromptPayload(),
    });
    renderVideoPromptConfig(data);
    alert("视频 Prompt 配置已保存");
  } catch (error) {
    alert(error.message);
  }
}

function getImageApiConfigPayload() {
  return {
    api_key: els.imageApiKey.value.trim(),
    base_url: els.imageBaseUrl.value.trim(),
    model: els.imageModel.value.trim(),
    output_dir: els.imageOutputDir.value.trim(),
    source_root_dir: els.imageSourceRootDir.value.trim(),
    path_style: isPathStyleGroupChecked("image") ? "linux" : "",
    use_mock: els.imageUseMock.checked,
    overwrite: els.imageOverwrite.checked,
  };
}

function getImageEditApiConfigPayload() {
  return {
    api_key: els.imageEditApiKey.value.trim(),
    base_url: els.imageEditBaseUrl.value.trim(),
    model: els.imageEditModel.value.trim(),
    output_dir: els.imageEditOutputDir.value.trim(),
    source_root_dir: els.imageEditSourceRootDir.value.trim(),
    path_style: isPathStyleGroupChecked("imageEdit") ? "linux" : "",
    use_mock: els.imageEditUseMock.checked,
    overwrite: els.imageEditOverwrite.checked,
  };
}

function getVideoApiConfigPayload() {
  return {
    api_key: els.videoApiKey.value.trim(),
    base_url: els.videoBaseUrl.value.trim(),
    model: els.videoModel.value.trim(),
    output_dir: els.videoOutputDir.value.trim(),
    video_source_root_dir: els.videoSourceRootDir.value.trim(),
    reference_source_root_dir: els.referenceSourceRootDir.value.trim(),
    path_style: isPathStyleGroupChecked("video") ? "linux" : "",
    use_mock: els.videoUseMock.checked,
    overwrite: els.videoOverwrite.checked,
  };
}

function renderImageApiConfig(data) {
  state.image.apiConfig = data.config || null;
  els.imageApiConfigPath.textContent = normalizeDisplayPath(data.path) || "未找到配置文件";
  els.imageApiKey.value = data.config?.api_key || "";
  els.imageBaseUrl.value = data.config?.base_url || "";
  els.imageModel.value = data.config?.model || "";
  els.imageOutputDir.value = normalizeDisplayPath(data.config?.output_dir || "");
  els.imageSourceRootDir.value = data.config?.source_root_dir || "";
  setPathStyleGroupChecked("image", (data.config?.path_style || "") === "linux");
  els.imageUseMock.checked = data.config?.use_mock ?? true;
  els.imageOverwrite.checked = data.config?.overwrite ?? false;
  els.imageApiKey.placeholder = "直接粘贴 API Key";
  els.imageOutputRootValue.textContent = normalizeDisplayPath(els.imageOutputDir.value.trim()) || "未设置";
  setModuleModeBadge(els.imageApiKey, els.imageUseMock, els.imageModeBadge);
}

function renderImageEditApiConfig(data) {
  state.imageEdit.apiConfig = data.config || null;
  els.imageEditApiConfigPath.textContent = normalizeDisplayPath(data.path) || "未找到配置文件";
  els.imageEditApiKey.value = data.config?.api_key || "";
  els.imageEditBaseUrl.value = data.config?.base_url || "";
  els.imageEditModel.value = data.config?.model || "";
  els.imageEditOutputDir.value = normalizeDisplayPath(data.config?.output_dir || "");
  els.imageEditSourceRootDir.value = data.config?.source_root_dir || "";
  setPathStyleGroupChecked("imageEdit", (data.config?.path_style || "") === "linux");
  els.imageEditUseMock.checked = data.config?.use_mock ?? true;
  els.imageEditOverwrite.checked = data.config?.overwrite ?? false;
  els.imageEditApiKey.placeholder = "直接粘贴 API Key";
  els.imageEditOutputRootValue.textContent = normalizeDisplayPath(els.imageEditOutputDir.value.trim()) || "未设置";
  setModuleModeBadge(els.imageEditApiKey, els.imageEditUseMock, els.imageEditModeBadge);
}

function renderVideoApiConfig(data) {
  state.video.apiConfig = data.config || null;
  els.videoApiConfigPath.textContent = normalizeDisplayPath(data.path) || "未找到配置文件";
  els.videoApiKey.value = data.config?.api_key || "";
  els.videoBaseUrl.value = data.config?.base_url || "";
  els.videoModel.value = data.config?.model || "";
  els.videoOutputDir.value = normalizeDisplayPath(data.config?.output_dir || "");
  els.videoSourceRootDir.value = data.config?.video_source_root_dir || "";
  els.referenceSourceRootDir.value = data.config?.reference_source_root_dir || "";
  setPathStyleGroupChecked("video", (data.config?.path_style || "") === "linux");
  els.videoUseMock.checked = data.config?.use_mock ?? true;
  els.videoOverwrite.checked = data.config?.overwrite ?? false;
  els.videoApiKey.placeholder = "直接粘贴 API Key";
  setModuleModeBadge(els.videoApiKey, els.videoUseMock, els.videoModeBadge);
}

async function loadDefaults() {
  const res = await fetch("/api/config");
  const data = await res.json();
  state.defaults = data;
  renderImageApiConfig({ path: data.imageApiConfigPath, config: data.imageApiConfig });
  renderImageEditApiConfig({ path: data.imageEditApiConfigPath, config: data.imageEditApiConfig });
  renderVideoApiConfig({ path: data.videoApiConfigPath, config: data.videoApiConfig });
}

async function loadImageApiConfig() {
  const res = await fetch("/api/runtime-config/image");
  const data = await res.json();
  renderImageApiConfig(data);
}

async function loadVideoApiConfig() {
  const res = await fetch("/api/runtime-config/video");
  const data = await res.json();
  renderVideoApiConfig(data);
}

async function loadImageEditApiConfig() {
  const res = await fetch("/api/runtime-config/image_edit");
  const data = await res.json();
  renderImageEditApiConfig(data);
}

async function saveApiConfig(kind, config) {
  const res = await fetch(`/api/runtime-config/${kind}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config }),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || "保存配置失败");
  }
  return data;
}

async function saveImageApiConfig() {
  try {
    const data = await saveApiConfig("image", {
      ...(state.image.apiConfig || {}),
      ...getImageApiConfigPayload(),
    });
    renderImageApiConfig(data);
    alert("图片 API 配置已保存");
  } catch (error) {
    alert(error.message);
  }
}

async function saveImageEditApiConfig() {
  try {
    const data = await saveApiConfig("image_edit", {
      ...(state.imageEdit.apiConfig || {}),
      ...getImageEditApiConfigPayload(),
    });
    renderImageEditApiConfig(data);
    alert("图生图 API 配置已保存");
  } catch (error) {
    alert(error.message);
  }
}

async function saveVideoApiConfig() {
  try {
    const data = await saveApiConfig("video", {
      ...(state.video.apiConfig || {}),
      ...getVideoApiConfigPayload(),
    });
    renderVideoApiConfig(data);
    alert("视频 API 配置已保存");
  } catch (error) {
    alert(error.message);
  }
}

function getComfyConfigPayload() {
  return {
    ...(state.comfy.config || {}),
    comfy_base_url: els.comfyBaseUrl.value.trim(),
    comfy_root_dir: els.comfyRootDir.value.trim(),
    comfy_input_dir: els.comfyInputDir.value.trim(),
    comfy_output_dir: els.comfyOutputDir.value.trim(),
    temp_dir: els.comfyTempDir.value.trim(),
    path_style: isPathStyleGroupChecked("comfy") ? "linux" : els.comfyPathStyle.value === "linux" ? "" : els.comfyPathStyle.value,
    request_timeout_sec: Number(els.comfyRequestTimeout.value || 30),
    job_timeout_sec: Number(els.comfyJobTimeout.value || 1800),
    poll_interval_sec: Number(els.comfyPollInterval.value || 2),
    ws_enabled: els.comfyWsEnabled.checked,
    workflow_manifest_dir: els.comfyWorkflowManifestDir.value.trim(),
  };
}

function renderComfyConfig(data) {
  state.comfy.config = data.config || null;
  els.comfyConfigPath.textContent = normalizeDisplayPath(data.path) || "未找到配置文件";
  els.comfyBaseUrl.value = data.config?.comfy_base_url || "http://127.0.0.1:8188";
  els.comfyRootDir.value = data.config?.comfy_root_dir || "";
  els.comfyInputDir.value = data.config?.comfy_input_dir || "";
  els.comfyOutputDir.value = data.config?.comfy_output_dir || "";
  els.comfyTempDir.value = normalizeDisplayPath(data.config?.temp_dir || "");
  const configuredPathStyle = data.config?.path_style || "";
  els.comfyPathStyle.value = configuredPathStyle === "linux" ? "" : configuredPathStyle;
  setPathStyleGroupChecked("comfy", configuredPathStyle === "linux");
  els.comfyRequestTimeout.value = String(data.config?.request_timeout_sec ?? 30);
  els.comfyJobTimeout.value = String(data.config?.job_timeout_sec ?? 1800);
  els.comfyPollInterval.value = String(data.config?.poll_interval_sec ?? 2);
  els.comfyWsEnabled.checked = data.config?.ws_enabled ?? true;
  els.comfyWorkflowManifestDir.value = normalizeDisplayPath(data.config?.workflow_manifest_dir || "");
  els.comfyOutputRootValue.textContent = normalizeDisplayPath(els.comfyOutputDir.value.trim()) || "未设置";
}

async function loadComfyConfig() {
  const res = await fetch("/api/comfy/config");
  const data = await res.json();
  renderComfyConfig(data);
}

async function saveComfyConfig() {
  try {
    const res = await fetch("/api/comfy/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config: getComfyConfigPayload() }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || "保存 ComfyUI 配置失败");
    }
    renderComfyConfig(data);
    alert("ComfyUI 配置已保存");
  } catch (error) {
    alert(error.message);
  }
}

async function loadComfyTemplates() {
  const res = await fetch("/api/comfy/templates");
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || "无法读取 ComfyUI 模板");
  }
  renderComfyTemplates(data);
}

async function checkComfyHealth() {
  try {
    els.comfyServerBadge.textContent = "检查中";
    els.comfyServerMeta.textContent = "正在请求 /system_stats 与 /queue";
    const res = await fetch("/api/comfy/health");
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || "ComfyUI 健康检查失败");
    }
    renderComfyHealth(data);
  } catch (error) {
    renderComfyHealth({ online: false, error: error.message });
    alert(error.message);
  }
}

function parseComfyParamsJson() {
  const text = els.comfyParamsJson.value.trim();
  if (!text) return {};
  const value = JSON.parse(text);
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Params JSON 必须是对象。");
  }
  return value;
}

function getComfyRunPayload() {
  const seedText = els.comfyDefaultSeed.value.trim();
  return {
    templateKey: els.comfyTemplateSelect.value,
    workflowType: els.comfyWorkflowType.value.trim(),
    csvPath: els.comfyCsvPath.value.trim(),
    imageRootDir: els.comfyImageRootDir.value.trim(),
    videoRootDir: els.comfyVideoRootDir.value.trim(),
    pathStyle: isPathStyleGroupChecked("comfy") ? "linux" : els.comfyPathStyle.value,
    defaultSeed: seedText ? Number(seedText) : null,
    defaultOutputPrefixBase: els.comfyOutputPrefix.value.trim(),
    defaultParams: parseComfyParamsJson(),
    workflowJsonText: els.comfyWorkflowJson.value.trim(),
    bindingsJsonText: els.comfyBindingsJson.value.trim(),
  };
}

async function startComfyJob() {
  try {
    els.startComfyJobBtn.disabled = true;
    els.comfyProgressText.textContent = "准备中";
    els.comfyProgressDetail.textContent = "正在提交到 ComfyUI。";
    const payload = getComfyRunPayload();
    if (!payload.csvPath) {
      throw new Error("请先填写 Prompt CSV 路径。");
    }
    const res = await fetch("/api/comfy/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || "ComfyUI 任务启动失败");
    }
    state.comfy.jobId = data.jobId;
    setComfyLog(data.job?.logs || []);
    renderComfyJob(data.job);
    pollComfyJob();
  } catch (error) {
    els.startComfyJobBtn.disabled = false;
    alert(error.message);
  }
}

function applySelectedTemplateBindings() {
  const template = selectedComfyTemplate();
  if (!template) {
    alert("当前没有可用模板");
    return;
  }
  const bindingsText = formatTemplateBindings(template);
  if (!bindingsText) {
    alert("当前模板没有显式 bindings");
    return;
  }
  els.comfyBindingsJson.value = bindingsText;
}

function buildCsvRow(values) {
  return values.map((value) => {
    const text = String(value ?? "");
    if (/[",\r\n]/.test(text)) {
      return `"${text.replaceAll('"', '""')}"`;
    }
    return text;
  }).join(",");
}

function downloadTextFile(filename, content, mimeType = "text/plain;charset=utf-8") {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function pollComfyJob() {
  if (state.comfy.pollTimer) clearInterval(state.comfy.pollTimer);
  const tick = async () => {
    if (!state.comfy.jobId) return;
    const res = await fetch(`/api/jobs/${state.comfy.jobId}`);
    const job = await res.json();
    renderComfyJob(job);
    setComfyLog(job.logs || []);

    if (job.output_dir) {
      const filesRes = await fetch(`/api/jobs/${state.comfy.jobId}/files`);
      const filesData = await filesRes.json();
      state.comfy.outputs = filesData.files || [];
      renderOutputList(state.comfy.outputs, els.comfyOutputList, els.comfyResultCount, "结果将在这里显示");
    }

    if (["completed", "partial", "failed", "cancelled", "timeout"].includes(job.status)) {
      els.startComfyJobBtn.disabled = false;
      clearInterval(state.comfy.pollTimer);
      state.comfy.pollTimer = null;
    }
  };
  await tick();
  state.comfy.pollTimer = setInterval(tick, 1000);
}

async function cancelComfyJob() {
  try {
    if (!state.comfy.jobId) {
      throw new Error("请先运行 ComfyUI 任务");
    }
    const res = await fetch("/api/comfy/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jobId: state.comfy.jobId }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || "取消失败");
    }
    setComfyLog(data.job?.logs || []);
    renderComfyJob(data.job);
  } catch (error) {
    alert(error.message);
  }
}

async function retryComfyJob() {
  try {
    if (!state.comfy.jobId) {
      throw new Error("请先运行或选择一个 ComfyUI 任务");
    }
    const res = await fetch("/api/comfy/retry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jobId: state.comfy.jobId }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || "重试失败");
    }
    state.comfy.jobId = data.jobId;
    setComfyLog(data.job?.logs || []);
    renderComfyJob(data.job);
    pollComfyJob();
  } catch (error) {
    alert(error.message);
  }
}

async function retryFailedComfyJob() {
  try {
    if (!state.comfy.jobId) {
      throw new Error("请先运行或选择一个 ComfyUI 任务");
    }
    const failures = Array.isArray(state.comfy.job?.failures) ? state.comfy.job.failures : [];
    if (!failures.length) {
      throw new Error("当前任务没有可重跑的失败项");
    }
    const retryableFailures = failures.filter((item) => item.retryable !== false);
    if (!retryableFailures.length) {
      throw new Error("当前失败项都需要先修正配置，不能直接重跑");
    }
    const res = await fetch("/api/comfy/retry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jobId: state.comfy.jobId, failedOnly: true }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || "仅重跑失败项失败");
    }
    state.comfy.jobId = data.jobId;
    setComfyLog(data.job?.logs || []);
    renderComfyJob(data.job);
    pollComfyJob();
  } catch (error) {
    alert(error.message);
  }
}

async function resumePendingComfyJob() {
  try {
    if (!state.comfy.jobId) {
      throw new Error("请先运行或选择一个 ComfyUI 任务");
    }
    const outputs = Array.isArray(state.comfy.job?.outputs) ? state.comfy.job.outputs : [];
    const meta = state.comfy.job?.meta || {};
    const selectedRowCount = Number(meta.selected_row_count || meta.row_count || 0);
    if (!selectedRowCount) {
      throw new Error("当前任务没有可续跑的行信息");
    }
    if (outputs.length >= selectedRowCount) {
      throw new Error("当前任务中的已选行都已经成功完成，无需续跑");
    }
    const res = await fetch("/api/comfy/retry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jobId: state.comfy.jobId, skipSucceeded: true }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || "跳过已成功项续跑失败");
    }
    state.comfy.jobId = data.jobId;
    setComfyLog(data.job?.logs || []);
    renderComfyJob(data.job);
    pollComfyJob();
  } catch (error) {
    alert(error.message);
  }
}

function exportComfyFailuresCsv() {
  const failures = Array.isArray(state.comfy.job?.failures) ? state.comfy.job.failures : [];
  if (!failures.length) {
    alert("当前没有失败项可导出");
    return;
  }
  const headers = ["row_index", "name", "stage", "error_code", "message", "retryable", "prompt_id", "detail"];
  const lines = [buildCsvRow(headers)];
  failures.forEach((item) => {
    lines.push(
      buildCsvRow([
        item.row_index ?? "",
        item.name ?? "",
        item.stage ?? "",
        item.error_code ?? "",
        item.message ?? "",
        item.retryable ?? "",
        item.prompt_id ?? "",
        item.detail ? (typeof item.detail === "string" ? item.detail : JSON.stringify(item.detail)) : "",
      ])
    );
  });
  const jobId = state.comfy.job?.id || "comfy_job";
  downloadTextFile(`${jobId}_failures.csv`, `${lines.join("\r\n")}\r\n`, "text/csv;charset=utf-8");
}

async function openComfyOutput() {
  if (!state.comfy.jobId) {
    alert("请先运行 ComfyUI 任务");
    return;
  }
  const res = await fetch(`/api/jobs/${state.comfy.jobId}/open-output`, { method: "POST" });
  const data = await res.json();
  if (!res.ok) {
    alert(data.error || "无法打开输出目录");
  }
}

function toDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function bindDropzone(dropzone, input, onFiles) {
  const prevent = (event) => {
    event.preventDefault();
    event.stopPropagation();
  };

  ["dragenter", "dragover", "dragleave", "drop"].forEach((eventName) => {
    dropzone.addEventListener(eventName, prevent, false);
  });
  ["dragenter", "dragover"].forEach((eventName) => {
    dropzone.addEventListener(eventName, () => dropzone.classList.add("dragover"));
  });
  ["dragleave", "drop"].forEach((eventName) => {
    dropzone.addEventListener(eventName, () => dropzone.classList.remove("dragover"));
  });
  // Chromium on Linux can expose a directory picker that reliably traverses
  // nested folders, while older browsers continue to use the input fallback.
  dropzone.addEventListener("click", async (event) => {
    if (event.target === input || typeof window.showDirectoryPicker !== "function") return;
    event.preventDefault();
    event.stopPropagation();
    try {
      const root = await window.showDirectoryPicker({ mode: "read" });
      const files = [];
      async function walk(directory, relativePrefix = "") {
        for await (const entry of directory.values()) {
          const relativePath = relativePrefix ? `${relativePrefix}/${entry.name}` : entry.name;
          if (entry.kind === "file") {
            const file = await entry.getFile();
            Object.defineProperty(file, "webkitRelativePath", { value: relativePath });
            files.push(file);
          } else if (entry.kind === "directory") {
            await walk(entry, relativePath);
          }
        }
      }
      await walk(root, root.name);
      const dataTransfer = new DataTransfer();
      files.forEach((file) => dataTransfer.items.add(file));
      input.files = dataTransfer.files;
      onFiles(files);
    } catch (error) {
      if (error?.name !== "AbortError") console.error("Directory selection failed", error);
    }
  });
  dropzone.addEventListener("drop", (event) => {
    const dt = new DataTransfer();
    Array.from(event.dataTransfer.files || []).forEach((file) => dt.items.add(file));
    input.files = dt.files;
    onFiles(Array.from(dt.files));
  });
}

async function startImageGeneration() {
  try {
    els.startImageBtn.disabled = true;
    els.imageProgressText.textContent = "准备中";
    els.imageProgressDetail.textContent = "正在提交任务。";

    let images = getImageItemsForSubmission();
    if (!images) {
      if (!state.image.files.length) {
        throw new Error("请先选择图片或填写图片 URL。");
      }
      images = [];
      for (const file of state.image.files) {
        const dataUrl = await toDataUrl(file);
        images.push({
          name: file.name,
          dataUrl,
          sourcePath: resolveSourcePath(file, els.imageSourceRootDir.value),
          relativePath: getLocalRelativePath(file),
        });
      }
    }

    const res = await fetch("/api/generate/image-prompt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        apiKey: els.imageApiKey.value.trim(),
        baseUrl: els.imageBaseUrl.value.trim(),
        model: els.imageModel.value.trim(),
        outputDir: els.imageOutputDir.value.trim(),
        pathStyle: isPathStyleGroupChecked("image") ? "linux" : "",
        overwrite: els.imageOverwrite.checked,
        useMock: els.imageUseMock.checked,
        promptConfig: {
          ...(state.image.promptConfig || {}),
          ...getImagePromptPayload(),
        },
        images,
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || "启动失败");
    }

    state.image.jobId = data.jobId;
    setImageLog(data.job?.logs || []);
    renderImageJob(data.job);
    pollImageJob();
  } catch (error) {
    els.startImageBtn.disabled = false;
    alert(error.message);
  }
}

async function pollImageJob() {
  if (state.image.pollTimer) clearInterval(state.image.pollTimer);
  const tick = async () => {
    if (!state.image.jobId) return;
    const res = await fetch(`/api/jobs/${state.image.jobId}`);
    const job = await res.json();
    renderImageJob(job);
    setImageLog(job.logs || []);

    if (job.output_dir) {
      const filesRes = await fetch(`/api/jobs/${state.image.jobId}/files`);
      const filesData = await filesRes.json();
      state.image.outputs = filesData.files || [];
      renderOutputList(state.image.outputs, els.imageOutputList, els.imageResultCount, "结果将在这里显示");
    }

    if (job.status === "completed" || job.status === "failed") {
      els.startImageBtn.disabled = false;
      clearInterval(state.image.pollTimer);
      state.image.pollTimer = null;
    }
  };
  await tick();
  state.image.pollTimer = setInterval(tick, 1000);
}

async function openImageOutput() {
  if (!state.image.jobId) {
    alert("请先运行图片任务");
    return;
  }
  const res = await fetch(`/api/jobs/${state.image.jobId}/open-output`, { method: "POST" });
  const data = await res.json();
  if (!res.ok) {
    alert(data.error || "无法打开输出目录");
  }
}

async function startImageEditGeneration() {
  try {
    els.startImageEditBtn.disabled = true;
    els.imageEditProgressText.textContent = "准备中";
    els.imageEditProgressDetail.textContent = "正在提交任务。";

    let images = getImageEditItemsForSubmission();
    if (!images) {
      if (!state.imageEdit.files.length) {
        throw new Error("请先选择图片或填写图片 URL。");
      }
      images = [];
      for (const file of state.imageEdit.files) {
        const dataUrl = await toDataUrl(file);
        images.push({
          name: file.name,
          dataUrl,
          sourcePath: resolveSourcePath(file, els.imageEditSourceRootDir.value),
          relativePath: getLocalRelativePath(file),
        });
      }
    }

    const res = await fetch("/api/generate/image-edit-prompt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        apiKey: els.imageEditApiKey.value.trim(),
        baseUrl: els.imageEditBaseUrl.value.trim(),
        model: els.imageEditModel.value.trim(),
        outputDir: els.imageEditOutputDir.value.trim(),
        pathStyle: isPathStyleGroupChecked("imageEdit") ? "linux" : "",
        overwrite: els.imageEditOverwrite.checked,
        useMock: els.imageEditUseMock.checked,
        promptConfig: {
          ...(state.imageEdit.promptConfig || {}),
          ...getImageEditPromptPayload(),
        },
        images,
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || "启动失败");
    }

    state.imageEdit.jobId = data.jobId;
    setImageEditLog(data.job?.logs || []);
    renderImageEditJob(data.job);
    pollImageEditJob();
  } catch (error) {
    els.startImageEditBtn.disabled = false;
    alert(error.message);
  }
}

async function pollImageEditJob() {
  if (state.imageEdit.pollTimer) clearInterval(state.imageEdit.pollTimer);
  const tick = async () => {
    if (!state.imageEdit.jobId) return;
    const res = await fetch(`/api/jobs/${state.imageEdit.jobId}`);
    const job = await res.json();
    renderImageEditJob(job);
    setImageEditLog(job.logs || []);

    if (job.output_dir) {
      const filesRes = await fetch(`/api/jobs/${state.imageEdit.jobId}/files`);
      const filesData = await filesRes.json();
      state.imageEdit.outputs = filesData.files || [];
      renderOutputList(state.imageEdit.outputs, els.imageEditOutputList, els.imageEditResultCount, "结果将在这里显示");
    }

    if (job.status === "completed" || job.status === "failed") {
      els.startImageEditBtn.disabled = false;
      clearInterval(state.imageEdit.pollTimer);
      state.imageEdit.pollTimer = null;
    }
  };
  await tick();
  state.imageEdit.pollTimer = setInterval(tick, 1000);
}

async function openImageEditOutput() {
  if (!state.imageEdit.jobId) {
    alert("请先运行图生图任务");
    return;
  }
  const res = await fetch(`/api/jobs/${state.imageEdit.jobId}/open-output`, { method: "POST" });
  const data = await res.json();
  if (!res.ok) {
    alert(data.error || "无法打开输出目录");
  }
}

async function scanVideoMatches() {
  try {
    const { videos, references } = getVideoAndReferenceEntries();
    if (!videos.length) {
      throw new Error("请先选择视频或填写视频 URL。");
    }
    if (!references.length) {
      throw new Error("请先选择参考图或填写参考图 URL。");
    }

    const res = await fetch("/api/video/scan-match", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        videos: videos.map((item) => ({ name: item.name })),
        references: references.map((item) => ({ name: item.name })),
      }),
    });
    const data = await res.json();
    state.video.matchResults = data.matches || [];
    state.video.matchSummary = data.summary || null;
    state.video.matchResultsExpanded = false;
    renderVideoMatches();
  } catch (error) {
    alert(error.message);
  }
}

function renderVideoMatches() {
  const summary = state.video.matchSummary || {
    total: 0,
    matched: 0,
    partial_match: 0,
    missing_reference: 0,
    naming_conflict: 0,
  };
  els.videoMatchSummary.innerHTML = `
    <span class="chip">总数 ${summary.total}</span>
    <span class="chip">成功 ${summary.matched}</span>
    <span class="chip">部分 ${summary.partial_match}</span>
    <span class="chip">缺失 ${summary.missing_reference}</span>
    <span class="chip">冲突 ${summary.naming_conflict}</span>
  `;

  const validCount = state.video.matchResults.filter((item) => item.canGenerate).length;
  els.videoMatchBadge.textContent = summary.total ? `${validCount}/${summary.total}` : "未扫描";
  els.videoMatchMeta.textContent = summary.total
    ? `${validCount} 可用 / ${summary.missing_reference + summary.naming_conflict} 阻塞`
    : "待扫描";

  if (!state.video.matchResults.length) {
    els.videoMatchTable.classList.add("empty");
    els.videoMatchTable.textContent = "扫描后显示结果";
    return;
  }

  els.videoMatchTable.classList.remove("empty");
  els.videoMatchTable.innerHTML = `
    <div class="table-head">
      <div>视频</div>
      <div>匹配键</div>
      <div>主参考图</div>
      <div>参考图 1</div>
      <div>参考图 2</div>
      <div>状态</div>
    </div>
    ${state.video.matchResults.map((item) => `
      <div class="match-row">
        <div>
          <strong>${escapeHtml(item.video)}</strong>
          <small>${item.canGenerate ? "可生成" : "需修正"}</small>
        </div>
        <div>${escapeHtml(item.matchKey)}</div>
        <div>${escapeHtml(item.referenceMain || "-")}</div>
        <div>${escapeHtml(item.referenceAlt1 || "-")}</div>
        <div>${escapeHtml(item.referenceAlt2 || "-")}</div>
        <div><span class="status-pill ${statusClass(item.status)}">${toReadableMatchStatus(item.status)}</span></div>
      </div>
    `).join("")}
  `;
}

function renderVideoMatches() {
  const summary = state.video.matchSummary || {
    total: 0,
    matched: 0,
    partial_match: 0,
    missing_reference: 0,
    naming_conflict: 0,
  };
  els.videoMatchSummary.innerHTML = `
    <span class="chip">总数 ${summary.total}</span>
    <span class="chip">成功 ${summary.matched}</span>
    <span class="chip">部分 ${summary.partial_match}</span>
    <span class="chip">缺失 ${summary.missing_reference}</span>
    <span class="chip">冲突 ${summary.naming_conflict}</span>
  `;

  const validCount = state.video.matchResults.filter((item) => item.canGenerate).length;
  els.videoMatchBadge.textContent = summary.total ? `${validCount}/${summary.total}` : "未扫描";
  els.videoMatchMeta.textContent = summary.total
    ? `${validCount} 可用 / ${summary.missing_reference + summary.naming_conflict} 阻塞`
    : "待扫描";

  if (!state.video.matchResults.length) {
    els.videoMatchTable.classList.add("empty");
    els.videoMatchTable.textContent = "扫描后显示结果";
    return;
  }

  const previewCount = 5;
  const previewMatches = state.video.matchResults.slice(0, previewCount);
  const remainingMatches = state.video.matchResults.slice(previewCount);

  els.videoMatchTable.classList.remove("empty");
  els.videoMatchTable.innerHTML = `
    <div class="match-preview-shell">
      <div class="file-summary-card">
        <div class="file-summary-copy">
          <strong>${state.video.matchResults.length} 条匹配</strong>
          <small>默认显示前 ${Math.min(state.video.matchResults.length, previewCount)} 条</small>
        </div>
        ${remainingMatches.length ? `
          <button
            type="button"
            class="btn btn-ghost file-toggle"
            data-match-toggle="video"
            aria-expanded="${state.video.matchResultsExpanded ? "true" : "false"}"
          >
            ${state.video.matchResultsExpanded ? "收起" : `展开 (${state.video.matchResults.length})`}
          </button>
        ` : `
          <span class="chip chip-soft">已全部显示</span>
        `}
      </div>

      <div class="match-table-preview">
        <div class="table-head">
          <div>视频</div>
          <div>匹配键</div>
          <div>主参考图</div>
          <div>参考图 1</div>
          <div>参考图 2</div>
          <div>状态</div>
        </div>
        ${renderMatchRows(previewMatches)}
      </div>

      ${remainingMatches.length ? `
        <div class="match-expand-shell ${state.video.matchResultsExpanded ? "is-open" : ""}">
          <div class="file-expand-note">其余 ${remainingMatches.length} 条</div>
          ${state.video.matchResultsExpanded ? `
            <div class="match-table-scroll">
              ${renderMatchRows(remainingMatches)}
            </div>
          ` : ""}
        </div>
      ` : ""}
    </div>
  `;
}

async function prepareVideoGenerationItems() {
  const candidates = state.video.matchResults.filter((item) => item.canGenerate);
  if (!candidates.length) {
    throw new Error("没有可生成条目，请先扫描并修正匹配。");
  }

  const { videos, references } = getVideoAndReferenceEntries();
  const videoEntryMap = new Map(videos.map((item) => [item.name, item]));
  const referenceEntryMap = new Map(references.map((item) => [item.name, item]));
  const items = [];

  for (const match of candidates) {
    const videoEntry = videoEntryMap.get(match.video);
    if (!videoEntry) {
      throw new Error(`未找到视频文件：${match.video}`);
    }

    let videoPayload = {};
    if (videoEntry.url) {
      els.videoProgressDetail.textContent = `正在使用视频 URL：${match.video}`;
      videoPayload = { videoUrl: videoEntry.url };
    } else {
      els.videoProgressDetail.textContent = `正在读取视频文件：${match.video}`;
      videoPayload = {
        videoDataUrl: await toDataUrl(videoEntry.file),
        sourcePath: videoEntry.sourcePath || resolveSourcePath(videoEntry.file, els.videoSourceRootDir.value),
        relativePath: videoEntry.relativePath || getLocalRelativePath(videoEntry.file),
      };
    }

    const references = [];
    for (const referenceName of [match.referenceMain, match.referenceAlt1, match.referenceAlt2]) {
      if (!referenceName) continue;
      const referenceEntry = referenceEntryMap.get(referenceName);
      if (!referenceEntry) continue;
      if (referenceEntry.url) {
        references.push({
          name: referenceName,
          url: referenceEntry.url,
        });
      } else {
        references.push({
          name: referenceName,
          dataUrl: await toDataUrl(referenceEntry.file),
          sourcePath: referenceEntry.sourcePath || resolveSourcePath(referenceEntry.file, els.referenceSourceRootDir.value),
          relativePath: referenceEntry.relativePath || getLocalRelativePath(referenceEntry.file),
        });
      }
    }

    items.push({
      name: match.video,
      matchKey: match.matchKey,
      referenceMain: match.referenceMain,
      referenceAlt1: match.referenceAlt1,
      referenceAlt2: match.referenceAlt2,
      ...videoPayload,
      references,
    });
  }

  return items;
}

async function startVideoGeneration() {
  try {
    els.startVideoBtn.disabled = true;
    els.videoProgressText.textContent = "准备中";
    els.videoProgressDetail.textContent = "正在读取文件。";

    const videos = await prepareVideoGenerationItems();
    const res = await fetch("/api/generate/video-prompt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        apiKey: els.videoApiKey.value.trim(),
        baseUrl: els.videoBaseUrl.value.trim(),
        model: els.videoModel.value.trim(),
        outputDir: els.videoOutputDir.value.trim(),
        pathStyle: isPathStyleGroupChecked("video") ? "linux" : "",
        overwrite: els.videoOverwrite.checked,
        useMock: els.videoUseMock.checked,
        promptConfig: {
          ...(state.video.promptConfig || {}),
          ...getVideoPromptPayload(),
        },
        videos,
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || "启动失败");
    }

    state.video.jobId = data.jobId;
    setVideoLog(data.job?.logs || []);
    renderVideoJob(data.job);
    pollVideoJob();
  } catch (error) {
    els.startVideoBtn.disabled = false;
    alert(error.message);
  }
}

async function pollVideoJob() {
  if (state.video.pollTimer) clearInterval(state.video.pollTimer);
  const tick = async () => {
    if (!state.video.jobId) return;
    const res = await fetch(`/api/jobs/${state.video.jobId}`);
    const job = await res.json();
    renderVideoJob(job);
    setVideoLog(job.logs || []);

    if (job.output_dir) {
      const filesRes = await fetch(`/api/jobs/${state.video.jobId}/files`);
      const filesData = await filesRes.json();
      state.video.outputs = filesData.files || [];
      renderOutputList(state.video.outputs, els.videoOutputList, els.videoResultCount, "结果将在这里显示");
    }

    if (job.status === "completed" || job.status === "failed") {
      els.startVideoBtn.disabled = false;
      clearInterval(state.video.pollTimer);
      state.video.pollTimer = null;
    }
  };
  await tick();
  state.video.pollTimer = setInterval(tick, 1000);
}

async function openVideoOutput() {
  if (!state.video.jobId) {
    alert("请先运行视频任务");
    return;
  }
  const res = await fetch(`/api/jobs/${state.video.jobId}/open-output`, { method: "POST" });
  const data = await res.json();
  if (!res.ok) {
    alert(data.error || "无法打开输出目录");
  }
}

function bindEvents() {
  els.navHomeBtn.addEventListener("click", () => setView("home"));
  els.navBackBtn.addEventListener("click", () => setView("home"));
  els.shutdownAppBtn.addEventListener("click", shutdownApp);
  els.goPromptStudioBtn.addEventListener("click", () => setView("promptStudio", state.activePromptModule));
  els.goClipStudioBtn.addEventListener("click", () => setView("clipStudio"));
  els.goComfyStudioBtn.addEventListener("click", () => setView("comfyStudio"));

  document.addEventListener("click", (event) => {
    const overviewButton = event.target.closest("[data-open-prompt-module]");
    if (overviewButton) {
      setView("promptStudio", overviewButton.dataset.openPromptModule);
      return;
    }

    const moduleTabButton = event.target.closest("[data-prompt-module]");
    if (moduleTabButton) {
      setActivePromptModule(moduleTabButton.dataset.promptModule);
      return;
    }

    const clipModeButton = event.target.closest("[data-clip-mode]");
    if (clipModeButton) {
      setClipMode(clipModeButton.dataset.clipMode);
      return;
    }

    const matchToggleButton = event.target.closest("[data-match-toggle]");
    if (matchToggleButton) {
      state.video.matchResultsExpanded = !state.video.matchResultsExpanded;
      renderVideoMatches();
      return;
    }

    const toggleButton = event.target.closest("[data-list-toggle]");
    if (!toggleButton) return;
    const toggleKey = toggleButton.dataset.listToggle;
    const config = listViewConfig(toggleKey);
    if (!config) return;
    setListExpanded(toggleKey, !config.expanded);
  });

  document.addEventListener("change", (event) => {
    const pathStyleToggle = event.target.closest("input[data-path-style-group]");
    if (!pathStyleToggle) return;
    setPathStyleGroupChecked(pathStyleToggle.dataset.pathStyleGroup, pathStyleToggle.checked);
  });

  els.imageInput.addEventListener("change", () => {
    state.image.files = Array.from(els.imageInput.files || []);
    state.image.filesExpanded = false;
    renderNamedStackList("image");
    els.imageSelectedCount.textContent = String(state.image.files.length);
  });
  els.imageEditInput.addEventListener("change", () => {
    state.imageEdit.files = Array.from(els.imageEditInput.files || []);
    state.imageEdit.filesExpanded = false;
    renderNamedStackList("imageEdit");
    els.imageEditSelectedCount.textContent = String(state.imageEdit.files.length);
  });
  els.videoInput.addEventListener("change", () => {
    state.video.videoFiles = Array.from(els.videoInput.files || []);
    state.video.videoFilesExpanded = false;
    renderNamedStackList("video");
    els.videoSelectedCount.textContent = String(state.video.videoFiles.length);
  });
  els.referenceInput.addEventListener("change", () => {
    state.video.referenceFiles = Array.from(els.referenceInput.files || []);
    state.video.referenceFilesExpanded = false;
    renderNamedStackList("reference");
    els.referenceSelectedCount.textContent = String(state.video.referenceFiles.length);
  });

  bindDropzone(els.imageDropzone, els.imageInput, (files) => {
    state.image.files = files.filter((file) => file.type.startsWith("image/"));
    state.image.filesExpanded = false;
    renderNamedStackList("image");
    els.imageSelectedCount.textContent = String(state.image.files.length);
  });
  bindDropzone(els.imageEditDropzone, els.imageEditInput, (files) => {
    state.imageEdit.files = files.filter((file) => file.type.startsWith("image/"));
    state.imageEdit.filesExpanded = false;
    renderNamedStackList("imageEdit");
    els.imageEditSelectedCount.textContent = String(state.imageEdit.files.length);
  });
  bindDropzone(els.videoDropzone, els.videoInput, (files) => {
    state.video.videoFiles = files.filter((file) => file.type.startsWith("video/") || /\.(mp4|mov|avi|mkv|webm)$/i.test(file.name));
    state.video.videoFilesExpanded = false;
    renderNamedStackList("video");
    els.videoSelectedCount.textContent = String(state.video.videoFiles.length);
  });
  bindDropzone(els.referenceDropzone, els.referenceInput, (files) => {
    state.video.referenceFiles = files.filter((file) => file.type.startsWith("image/"));
    state.video.referenceFilesExpanded = false;
    renderNamedStackList("reference");
    els.referenceSelectedCount.textContent = String(state.video.referenceFiles.length);
  });

  els.imageApiKey.addEventListener("input", () => setModuleModeBadge(els.imageApiKey, els.imageUseMock, els.imageModeBadge));
  els.imageUseMock.addEventListener("change", () => setModuleModeBadge(els.imageApiKey, els.imageUseMock, els.imageModeBadge));
  els.imageOutputDir.addEventListener("input", () => {
    els.imageOutputRootValue.textContent = els.imageOutputDir.value.trim() || "未设置";
  });

  els.imageEditApiKey.addEventListener("input", () => setModuleModeBadge(els.imageEditApiKey, els.imageEditUseMock, els.imageEditModeBadge));
  els.imageEditUseMock.addEventListener("change", () => setModuleModeBadge(els.imageEditApiKey, els.imageEditUseMock, els.imageEditModeBadge));
  els.imageEditOutputDir.addEventListener("input", () => {
    els.imageEditOutputRootValue.textContent = els.imageEditOutputDir.value.trim() || "未设置";
  });

  els.videoApiKey.addEventListener("input", () => setModuleModeBadge(els.videoApiKey, els.videoUseMock, els.videoModeBadge));
  els.videoUseMock.addEventListener("change", () => setModuleModeBadge(els.videoApiKey, els.videoUseMock, els.videoModeBadge));

  els.comfyTemplateSelect.addEventListener("change", renderComfyTemplateDescription);
  els.applyComfyTemplateBindingsBtn.addEventListener("click", applySelectedTemplateBindings);
  els.comfyOutputDir.addEventListener("input", () => {
    els.comfyOutputRootValue.textContent = normalizeDisplayPath(els.comfyOutputDir.value.trim()) || "未设置";
  });
  els.reloadComfyConfigBtn.addEventListener("click", loadComfyConfig);
  els.saveComfyConfigBtn.addEventListener("click", saveComfyConfig);
  els.checkComfyHealthBtn.addEventListener("click", checkComfyHealth);
  els.reloadComfyTemplatesBtn.addEventListener("click", async () => {
    try {
      await loadComfyTemplates();
    } catch (error) {
      alert(error.message);
    }
  });
  els.startComfyJobBtn.addEventListener("click", startComfyJob);
  els.cancelComfyJobBtn.addEventListener("click", cancelComfyJob);
  els.retryComfyJobBtn.addEventListener("click", retryComfyJob);
  els.retryFailedComfyJobBtn.addEventListener("click", retryFailedComfyJob);
  els.resumePendingComfyJobBtn.addEventListener("click", resumePendingComfyJob);
  els.exportComfyFailuresBtn.addEventListener("click", exportComfyFailuresCsv);
  els.refreshComfyJobBtn.addEventListener("click", () => state.comfy.jobId && pollComfyJob());
  els.reloadComfyFilesBtn.addEventListener("click", async () => {
    if (!state.comfy.jobId) return;
    const res = await fetch(`/api/jobs/${state.comfy.jobId}/files`);
    const data = await res.json();
    state.comfy.outputs = data.files || [];
    renderOutputList(state.comfy.outputs, els.comfyOutputList, els.comfyResultCount, "结果将在这里显示");
  });
  els.openComfyOutputBtn.addEventListener("click", openComfyOutput);

  els.clipPresetSelect.addEventListener("change", () => {
    state.clip.preset = els.clipPresetSelect.value;
    renderClipPresetDescription();
    updateClipSummary();
  });
  els.clipInputDir.addEventListener("input", updateClipSummary);
  els.clipInputDirA.addEventListener("input", updateClipSummary);
  els.clipInputDirB.addEventListener("input", updateClipSummary);
  els.clipOutputDir.addEventListener("input", updateClipSummary);
  els.startClipBtn.addEventListener("click", startClipJob);
  els.refreshClipJobBtn.addEventListener("click", () => state.clip.jobId && pollClipJob());
  els.openClipOutputBtn.addEventListener("click", openClipOutput);

  els.reloadImageApiConfigBtn.addEventListener("click", loadImageApiConfig);
  els.saveImageApiConfigBtn.addEventListener("click", saveImageApiConfig);
  els.reloadImagePromptConfigBtn.addEventListener("click", loadImagePromptConfig);
  els.saveImagePromptConfigBtn.addEventListener("click", saveImagePromptConfig);
  els.startImageBtn.addEventListener("click", startImageGeneration);
  els.refreshImageJobBtn.addEventListener("click", () => state.image.jobId && pollImageJob());
  els.reloadImageFilesBtn.addEventListener("click", async () => {
    if (!state.image.jobId) return;
    const res = await fetch(`/api/jobs/${state.image.jobId}/files`);
    const data = await res.json();
    state.image.outputs = data.files || [];
    renderOutputList(state.image.outputs, els.imageOutputList, els.imageResultCount, "结果将在这里显示");
  });
  els.openImageOutputBtn.addEventListener("click", openImageOutput);

  els.reloadImageEditApiConfigBtn.addEventListener("click", loadImageEditApiConfig);
  els.saveImageEditApiConfigBtn.addEventListener("click", saveImageEditApiConfig);
  els.reloadImageEditPromptConfigBtn.addEventListener("click", loadImageEditPromptConfig);
  els.saveImageEditPromptConfigBtn.addEventListener("click", saveImageEditPromptConfig);
  els.startImageEditBtn.addEventListener("click", startImageEditGeneration);
  els.refreshImageEditJobBtn.addEventListener("click", () => state.imageEdit.jobId && pollImageEditJob());
  els.reloadImageEditFilesBtn.addEventListener("click", async () => {
    if (!state.imageEdit.jobId) return;
    const res = await fetch(`/api/jobs/${state.imageEdit.jobId}/files`);
    const data = await res.json();
    state.imageEdit.outputs = data.files || [];
    renderOutputList(state.imageEdit.outputs, els.imageEditOutputList, els.imageEditResultCount, "结果将在这里显示");
  });
  els.openImageEditOutputBtn.addEventListener("click", openImageEditOutput);

  els.reloadVideoApiConfigBtn.addEventListener("click", loadVideoApiConfig);
  els.saveVideoApiConfigBtn.addEventListener("click", saveVideoApiConfig);
  els.scanVideoMatchBtn.addEventListener("click", scanVideoMatches);
  els.reloadVideoPromptConfigBtn.addEventListener("click", loadVideoPromptConfig);
  els.saveVideoPromptConfigBtn.addEventListener("click", saveVideoPromptConfig);
  els.startVideoBtn.addEventListener("click", startVideoGeneration);
  els.refreshVideoJobBtn.addEventListener("click", () => state.video.jobId && pollVideoJob());
  els.reloadVideoFilesBtn.addEventListener("click", async () => {
    if (!state.video.jobId) return;
    const res = await fetch(`/api/jobs/${state.video.jobId}/files`);
    const data = await res.json();
    state.video.outputs = data.files || [];
    renderOutputList(state.video.outputs, els.videoOutputList, els.videoResultCount, "结果将在这里显示");
  });
  els.openVideoOutputBtn.addEventListener("click", openVideoOutput);

}

async function init() {
  renderPromptModuleOverview();
  renderPromptModuleTabs();
  bindEvents();
  await registerBrowserSession();
  startBrowserHeartbeat();
  setView("home");
  await loadClipPresets();
  setClipMode(state.clip.mode);
  updateClipSummary();
  renderClipOutputs([]);
  renderClipJob({ id: "", status: "idle", progress: 0, total: 0, error: "", output_dir: "", outputs: [] });
  renderNamedStackList("image");
  renderNamedStackList("imageEdit");
  renderNamedStackList("video");
  renderNamedStackList("reference");
  setClipLog([]);
  renderOutputList([], els.imageOutputList, els.imageResultCount, "结果将在这里显示");
  renderOutputList([], els.imageEditOutputList, els.imageEditResultCount, "结果将在这里显示");
  renderOutputList([], els.videoOutputList, els.videoResultCount, "结果将在这里显示");
  renderOutputList([], els.comfyOutputList, els.comfyResultCount, "结果将在这里显示");
  renderImageJob({ id: "", status: "idle", progress: 0, total: 0, error: "", output_dir: "" });
  renderImageEditJob({ id: "", status: "idle", progress: 0, total: 0, error: "", output_dir: "" });
  renderVideoJob({ id: "", status: "idle", progress: 0, total: 0, error: "", output_dir: "" });
  renderComfyJob({ id: "", status: "idle", progress: 0, total: 0, error: "", output_dir: "", meta: {} });
  renderVideoMatches();
  setImageLog([]);
  setImageEditLog([]);
  setVideoLog([]);
  setComfyLog([]);
  renderComfyHealth({ online: false, error: "待检查" });
  await loadDefaults();
  await loadImagePromptConfig();
  await loadImageEditPromptConfig();
  await loadVideoPromptConfig();
  await loadComfyConfig();
  await loadComfyTemplates();
}

init();
