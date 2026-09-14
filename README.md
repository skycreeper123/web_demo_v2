# Prompt Tool Web Demo

`web_demo` 是一个本地运行的单体 Web 工具，当前包含 3 个工作台：

- `Prompt 生成工作台`
  - 图片 -> I2V Prompt
  - 图片 -> 图生图 Prompt
  - 视频 + 参考图 -> 视频编辑 Prompt
- `本地 Comfy 通信工作台`
  - 从 `prompts.csv` 批量读取任务
  - 与本机 `ComfyUI` 通信并回收结果
  - 显式查看 / 载入 workflow `bindings`
  - 支持整批重试、仅重跑失败项、跳过已成功项续跑
- `视频剪辑工作台`
  - 单文件夹批量裁切
  - 双文件夹顺序合并

项目使用内置 `SQLite` 保存任务状态，没有前端构建链。前端使用原生 `HTML + CSS + JavaScript`，后端使用 Python 标准库 `http.server`。

## 当前能力

- 3 个 Prompt 子模块统一收口到一个工作台
- `workflow/` 根目录中的工作流模板可自动扫描；重复模板副本已清理
- 对原始 API 工作流 JSON 支持常见字段绑定自动推断
- 模板 bindings 可显式预览，并可一键载入到编辑区
- Prompt 任务支持 `mock` / 真实 API 两种模式
- Prompt 输出会生成 `json`、`txt`、`csv`
- 浏览器本地上传的图片 / 视频 / 参考图会优先落盘到任务目录 `source_media/`
- 视频 Prompt 链路会显式区分视频媒体与图片媒体
- Comfy 批跑支持结构化失败详情：
  - `row_index`
  - `stage`
  - `error_code`
  - `message`
  - `retryable`
- Comfy 批跑支持：
  - 整批重试
  - 仅重跑失败项
  - 跳过已成功项续跑
  - 前端导出失败项 CSV
  - 部分成功时保留成功产物并标记为 `partial`
- Comfy 输入使用本地文件投递：
  - 根据 CSV 中的本地媒体路径复制到 `ComfyUI/input/jobs/<prompt_id>/`
  - 写入 workflow 的是 `jobs/<prompt_id>/...` 形式的相对引用
- 全程序日志系统已落地，支持应用日志、HTTP 日志、任务日志
- 自动关闭策略已改为：
  - 无浏览器会话
  - 且没有运行中任务
  - 才自动关闭服务
- 视频剪辑优先使用项目内 `.venv` 的 `imageio-ffmpeg`
- 支持 Windows 启动器 `PromptToolLauncher.exe`
- 支持 Linux 启动脚本 `run_linux.sh`

## 快速启动

### 1. 准备 Python 环境

推荐优先使用项目内虚拟环境：

```text
Windows: .venv\Scripts\python.exe
Linux:   .venv/bin/python
```

### 2. 安装可选依赖

如果你要使用 `视频剪辑工作台`，需要安装：

Windows:

```powershell
.venv\Scripts\python.exe -m pip install opencv-python imageio-ffmpeg
```

Linux:

```bash
.venv/bin/python -m pip install opencv-python imageio-ffmpeg
```

`Prompt 生成工作台` 与 `ComfyUI 通信工作台` 不依赖这两个包。

### 3. 启动服务

Windows:

```powershell
python .\backend\app\main.py
```

Linux:

```bash
python3 ./backend/app/main.py
```

浏览器打开：

```text
http://127.0.0.1:8000
```

### 4. 平台启动器

Windows:

- 双击 `PromptToolLauncher.exe`

Linux:

```bash
bash ./run_linux.sh
```

## 目录结构

```text
web_demo/
  frontend/
  backend/
  batch_editing/
  logs/
  output/
  uploads/
  workflow/
  backend/jobs.sqlite3  # 运行时任务状态库，默认不纳入 Git
  .venv/
  PromptToolLauncher.cs
  PromptToolLauncher.exe
  run_linux.sh
  README.md
  USER_GUIDE.md
  TECHNICAL.md
```

## 三个关键说明

### Prompt 生成工作台

它负责批量生成 Prompt，不直接做成片。

如果输入来自浏览器本地文件选择：

- 任务目录下会生成 `source_media/`
- `prompts.csv` 中的 `image_path` / `video_path` 会优先写入这些已落盘文件的完整路径

如果输入来自远程 URL：

- `image_path` / `video_path` 可能为空
- `image_name` / `video_name` 仍会保留

### 本地 Comfy 通信工作台

它当前以 `CSV` 批量导入为核心入口。

典型流程是：

1. 先用 Prompt 模块生成 `prompts.csv`
2. 在 Comfy 工作台选择模板，或直接填写工作流 JSON / bindings JSON
3. 根据 workflow 需要确认 `bindings`
4. 提交到本机 `ComfyUI`
5. 查看结果文件、失败详情，必要时做失败续跑

Comfy 视频生成仍由单个本机实例按其自身队列执行。应用当前按 CSV 行顺序提交并等待结果，重点是稳定回收、失败续跑和可追踪性，而不是对单机 GPU 做并行渲染。

### 视频剪辑工作台

它是本地批处理能力，不依赖远程模型，主要依赖：

- `ffmpeg`
- `OpenCV`

当前实现里，ffmpeg 能力优先来自 `.venv` 中的 `imageio-ffmpeg`。

## 平台兼容

- 核心 Web 应用支持 Windows 和 Linux 本地运行
- 路径字段支持 Windows 和 Linux 常见写法
- `打开输出目录` 在 Windows 下使用 `os.startfile`
- `打开输出目录` 在 Linux 下使用 `xdg-open`
- Windows 启动器是 `PromptToolLauncher.exe`
- Linux 推荐使用 `bash ./run_linux.sh`
- 浏览器目录选择依赖 `webkitdirectory`
- Linux 下建议使用 Chrome 或 Edge

## 日志系统

日志目录：

- `logs/app.log`
- `logs/error.log`
- `logs/http.log`
- `logs/jobs/{job_id}.log`

用途：

- `app.log`
  - 应用生命周期与通用运行日志
- `error.log`
  - 错误与异常
- `http.log`
  - HTTP 请求访问记录
- `jobs/*.log`
  - 每个任务单独日志

## 文档入口

- 使用说明：[USER_GUIDE.md](./USER_GUIDE.md)
- 技术文档：[TECHNICAL.md](./TECHNICAL.md)

## 当前限制

- 任务状态保存在 `backend/jobs.sqlite3`，服务重启后可保留任务历史、日志、输出与失败详情
- 如果服务在任务运行中异常退出，任务会在下次启动时标记为失败；原始 Comfy 提交参数会保留，便于重试
- SQLite 当前保存任务快照，尚未提供可筛选的历史批次管理界面
- Prompt 结果页没有专门的二次编辑器
- 视频匹配当前仍以固定同名规则为主
- Comfy 工作台当前仍以 `CSV` 批量导入模式为主
- 对复杂工作流的 bindings 自动推断仍是启发式，不保证覆盖所有社区工作流；自动结果只适合首轮填充
- 工作流敲定后，建议将人工确认过的 bindings 固化在模板中，批量生产时不要依赖自动推断
- `overwrite` 字段当前更多是兼容性配置；由于默认按时间戳目录输出，跨任务运行一般不会直接覆盖旧结果
- LLM 调用层仍然是轻量 OpenAI-compatible 适配，没有完整的多供应商抽象与限流体系；对瞬态 SSL/连接中断提供有限自动重试
