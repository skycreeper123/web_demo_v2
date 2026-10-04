# Prompt Tool Web Demo 技术文档

## 1. 项目定位

`web_demo` 是一个可在本机或服务器运行的轻量单体项目，当前包含 4 个工作台：

- `视频流程工作台`
- `Prompt 生成工作台`
- `本地 Comfy 通信工作台`
- `视频剪辑工作台`

它更偏向个人生产辅助工具，而不是完整的线上多用户服务。

## 2. 技术栈

- 前端：原生 `HTML + CSS + JavaScript`
- 后端：Python 标准库 `http.server`
- 通信：本地 JSON API
- 任务执行：SQLite 持久化任务状态 + 后台线程
- 模型接口：OpenAI-compatible `chat/completions`
- 本地视频处理：`opencv-python` + `imageio-ffmpeg`
- 本地 Comfy 通信：HTTP + 可选 WebSocket 监听
- 日志：Python `logging` + `RotatingFileHandler`

## 3. 目录结构

```text
web_demo/
  frontend/
    index.html
    style.css
    app.js
  backend/
    api_config.json
    image_prompt_config.json
    image_edit_prompt_config.json
    video_prompt_config.json
    comfyui_comm_config.json
    app/
      main.py
      core/
        config.py
        llm_client.py
      services/
        prompt_generator.py
        image_edit_prompt_generator.py
        video_matcher.py
        video_prompt_generator.py
        video_clip_service.py
        comfyui_comm/
          __init__.py
          input_stager.py
          job_monitor.py
          path_resolver.py
          result_collector.py
          server_client.py
          workflow_binder.py
      utils/
        file_writer.py
        image_loader.py
        logging_utils.py
  logs/
  output/
  uploads/
  workflow/
  backend/jobs.sqlite3
  batch_editing/
```

## 4. 架构概览

### 4.1 前端

前端位于 `frontend/`，主要负责：

- 首页与工作台入口
- Prompt 子模块切换
- Comfy 工作台表单交互
- 模板 bindings 预览与载入
- 视频剪辑模式切换
- 文件选择 / 拖拽导入
- 配置读取与保存
- 发起任务
- 轮询任务状态
- 展示日志、进度、输出文件、失败详情

关键文件：

- `frontend/index.html`
- `frontend/style.css`
- `frontend/app.js`

### 4.2 后端

后端位于 `backend/app/`，主要负责：

- 托管静态页面
- 提供 JSON API
- 维护配置文件
- 创建和更新任务状态
- 调用模型接口
- 执行本地视频批处理
- 与本机 `ComfyUI` 通信
- 写出结果文件与失败信息

入口文件：

- `backend/app/main.py`

### 4.3 任务系统

任务系统使用轻量内存缓存配合 SQLite 持久化，核心结构：

- `JobState`
- `JobStore`

执行方式：

1. 创建任务对象并写入 `backend/jobs.sqlite3`
2. 通过后台线程执行服务函数
3. 实时同步日志、进度、输出路径、元数据、失败列表到 SQLite
4. 前端轮询 `/api/jobs/{jobId}`

恢复策略：

- 服务重启后会恢复历史任务
- 上次退出前处于 `queued` 或 `running` 的任务会被标记为 `failed`
- 已完成任务、失败详情、输出信息和 Comfy 重试原始参数会被保留

说明：

- `SQLite` 使用 Python 标准库 `sqlite3`，不需要单独安装或启动数据库服务
- `backend/jobs.sqlite3`、`-wal`、`-shm` 文件属于运行时状态，默认不纳入 Git
- 当前数据库保存的是任务快照；尚未拆分成批次、行项目、事件三张独立业务表

当前任务类型：

- `image`
- `image_edit`
- `video`
- `video_clip`
- `comfy_video`

### 4.4 自动关闭策略

浏览器会话由 `BrowserSessionStore` 管理。

当前自动关闭行为为：

- 浏览器会话全部断开
- 且 `JobStore` 中没有运行中任务
- 服务端才会自动关闭

这样可以保留桌面工具的自动退出体验，同时避免长任务在处理中被提前终止。

## 5. 核心模块划分

### 5.1 配置层

`backend/app/core/config.py` 负责：

- 默认 API 配置
- 默认 Prompt 配置
- 默认 Comfy 配置
- `api_config.json` 的读写
- 3 份 Prompt 配置文件的读写
- `comfyui_comm_config.json` 的读写
- 输出目录解析
- 相对路径优先策略
- 跨平台路径文本规范化

### 5.2 LLM 调用层

`backend/app/core/llm_client.py` 是轻量适配层，当前特点：

- 请求地址：`{base_url}/chat/completions`
- 消息结构：`user.content = [text, media...]`
- 支持显式 `image_url` 与 `video_url`
- 多媒体输入：`http(s)` URL 或 `data URL`
- 响应提取：`choices[0].message.content`

它是 OpenAI-compatible 调用，不是完整的多供应商 SDK 抽象层。

### 5.3 Prompt 服务层

#### 图片 Prompt

`backend/app/services/prompt_generator.py`

- 处理图片输入
- 读取图片 Prompt 配置
- 在 `mock` / 真实模型之间切换
- 写出 `json`、`txt`、`csv`
- 对浏览器本地上传图片优先落盘到 `source_media/images/`

#### 图生图 Prompt

`backend/app/services/image_edit_prompt_generator.py`

- 处理图生图输入
- 读取图生图 Prompt 配置
- 在 `mock` / 真实模型之间切换
- 写出 `json`、`txt`、`csv`
- 对浏览器本地上传图片优先落盘到 `source_media/images/`

#### 视频匹配

`backend/app/services/video_matcher.py`

- 过滤支持的扩展名
- 以主文件名做固定同名匹配
- 输出匹配列表和统计摘要

状态包括：

- `matched`
- `partial_match`
- `missing_reference`
- `naming_conflict`

#### 视频 Prompt

`backend/app/services/video_prompt_generator.py`

- 组织视频和参考图输入
- 生成视频编辑 Prompt
- 写出 `json`、`txt`、`csv`
- 对浏览器本地上传的视频和参考图优先落盘到 `source_media/videos/` 与 `source_media/references/`
- 调用模型时显式区分：
  - 源视频：`video_url`
  - 参考图：`image_url`

### 5.4 Comfy 通信服务层

目录：

- `backend/app/services/comfyui_comm/`

职责拆分：

- `server_client.py`
  - 与 `ComfyUI` 的 HTTP 接口交互
- `job_monitor.py`
  - WebSocket 监听、节点进度跟踪、任务注册
- `workflow_binder.py`
  - 模板扫描、工作流解析、绑定推断、最终工作流注入
- `input_stager.py`
  - 将 CSV 中声明的本地图片 / 视频复制到 Comfy 输入目录
- `result_collector.py`
  - 回收输出结果，优先定位视频主输出文件
- `path_resolver.py`
  - 解析 Comfy 根目录、输入目录、输出目录、临时目录、工作流目录
- `__init__.py`
  - 对外暴露健康检查、模板列表、批量执行、取消、重试等入口

当前实现特点：

- 采用 `CSV` 批量导入
- 支持模板选择或直接填写工作流 JSON / bindings JSON
- 支持原始 API 工作流 JSON 的常见绑定自动推断
- 模板列表会返回显式 bindings 内容，供前端直接预览
- 支持任务取消
- 支持失败后整批重试
- 支持仅重跑失败行
- 支持跳过已成功项续跑
- 行级结果部分成功时，任务状态会标记为 `partial`
- 支持结构化失败详情：
  - `row_index`
  - `stage`
  - `error_code`
  - `message`
  - `retryable`
- 支持 HTTP 轮询
- 可选启用 WebSocket 节点监听

bindings 自动推断规则：

- 根据 `class_type`、输入字段名和节点标题推断 `image_ref`、`video_ref`、正负 Prompt、`seed`、`output_prefix`
- 适合命名规范的常见 API workflow，不能可靠理解自定义节点或复杂图语义
- 推断结果应在 UI 中确认；确定量产 workflow 后，应保存显式 bindings 并作为唯一执行配置

### 5.5 视频剪辑服务层

`backend/app/services/video_clip_service.py`

- 定义 `CLIP_PRESETS`
- 暴露预设列表
- 执行本地批处理
- 支持单文件夹裁切、双文件夹顺序合并与首尾帧提取
- 写出 `manifest.json` 和 `summary.csv`

当前预设包括：

- `first_half_ffmpeg`
- `first_half_opencv`
- `first_30pct`
- `first_70pct`
- `first_3s`
- `first_5s`
- `first_7s`
- `last_3s`
- `last_5s`
- `last_7s`
- `tail_30pct`
- `tail_50pct`
- `tail_70pct`
- `extract_first_frame`
- `extract_last_frame`
- `extract_first_last_frames`
- `merge_pairwise`

首尾帧预设使用 `extract_frames` 模式，通过现有 `/api/clip/run` 提交。OpenCV 顺序解码至末尾获取最后一个可解码帧，不依赖帧数元数据定位；PNG 通过 `imencode` 与 `Path.write_bytes` 写出，兼容 Windows 中文路径。结果中的 `first_frame_image` / `last_frame_image` 记录图片路径，未请求的一项为空，`output_video` 为空。单目录任务返回 `completed` / `partial` / `failed`，前端在三种终态停止轮询。

## 6. 业务流程

### 6.1 图片 -> I2V Prompt

1. 前端读取图片或图片 URL
2. 本地文件会被转成 `data URL`
3. 后端接收 `images`
4. 若是本地上传，会把源图落盘到任务目录 `source_media/images/`
5. `use_mock=true` 或 `api_key` 为空时直接使用 `mock_result`
6. 否则调用模型接口
7. 写出 `*.prompt.json`、`*.prompt.txt`、`prompts.csv`

### 6.2 图片 -> 图生图 Prompt

1. 前端读取图片或图片 URL
2. 本地文件会被转成 `data URL`
3. 后端接收 `images`
4. 若是本地上传，会把源图落盘到任务目录 `source_media/images/`
5. 按图生图 Prompt 配置组装请求
6. 在 `mock` / 真实模型之间切换
7. 写出 `*.prompt.json`、`*.prompt.txt`、`prompts.csv`

### 6.3 视频 -> 视频编辑 Prompt

1. 前端先扫描视频与参考图匹配
2. 仅将可生成项送入生成流程
3. 本地文件会被转成 `data URL`
4. 后端将视频和参考图落盘到 `source_media/videos/` 与 `source_media/references/`
5. 调用模型接口生成 Prompt
6. 请求中显式区分视频媒体和图片媒体
7. 写出 `*.prompt.json`、`*.prompt.txt`、`prompts.csv`

### 6.4 Comfy 批量执行

1. 前端读取 `prompts.csv`
2. 后端载入 CSV 行
3. 如有需要，先根据 `rowIndices` 筛选待执行行
4. 解析模板或直接解析工作流 JSON / bindings JSON
5. 根据 `image_path` / `video_path` 将输入复制到 Comfy `input/jobs/<prompt_id>/`
6. 通过 bindings 将 prompt、媒体、seed、输出前缀绑定到目标节点
7. 提交到 `ComfyUI`
8. 通过 HTTP 与可选 WebSocket 跟踪执行状态
9. 回收结果并更新任务输出
10. 记录结构化失败信息，供前端续跑与导出

单机执行策略：

- 当前后端逐行提交并等待每行结果后再处理下一行
- 这与单个 ComfyUI 实例的视频生成队列相匹配，避免同时投递大量视频任务导致显存、队列和结果回收难以定位
- 因此当前优化目标是减少非生成阶段开销、保证失败续跑和任务可追踪，而不是在单机 GPU 上强行并发渲染

CSV 行优先字段：

- `image_path`
- `video_path`
- `positive_prompt`
- `negative_prompt`
- `seed`
- `output_prefix`
- `params_json`
- `workflow_type`

如果 `image_path` / `video_path` 为空，则会回退到：

- `imageRootDir + image_name`
- `videoRootDir + video_name`

### 6.5 Comfy 续跑策略

当前支持 3 种方式：

1. 整批重试
2. 仅重跑失败行
3. 跳过已成功项续跑

其中：

- 仅重跑失败行：基于上一任务的 `failures[].row_index`
- 跳过已成功项续跑：基于上一任务的已成功 `outputs[].row_index`
- 如果同一批次里同时存在成功与失败，任务会结束为 `partial`，便于继续续跑与区分纯失败

### 6.6 视频剪辑工作台

1. 前端读取 `/api/clip/presets`
2. 用户选择模式、预设、输入路径、输出目录
3. 前端发起 `POST /api/clip/run`
4. 后端创建 `video_clip` 任务
5. 服务层执行本地批处理
6. 输出视频、预览帧、`manifest.json`、`summary.csv`

## 7. 配置体系

### 7.1 API 配置

文件：

- `backend/api_config.json`

模块：

- `image`
- `image_edit`
- `video`

当前字段：

- `api_key`
- `base_url`
- `model`
- `output_dir`
- `source_root_dir`
- `video_source_root_dir`
- `reference_source_root_dir`
- `use_mock`
- `overwrite`

说明：

- `image` 与 `image_edit` 使用 `source_root_dir`
- `video` 使用 `video_source_root_dir` 与 `reference_source_root_dir`
- 这些字段主要用于前端辅助推导路径和保存配置
- 浏览器本地上传的媒体仍会优先落盘到任务目录 `source_media/`

### 7.2 Prompt 配置

文件：

- `backend/image_prompt_config.json`
- `backend/image_edit_prompt_config.json`
- `backend/video_prompt_config.json`

公共字段：

- `system_prompt`
- `user_text`
- `mock_result`

### 7.3 Comfy 配置

文件：

- `backend/comfyui_comm_config.json`

字段：

- `comfy_base_url`
- `comfy_root_dir`
- `comfy_input_dir`
- `comfy_output_dir`
- `temp_dir`
- `path_style`
- `request_timeout_sec`
- `job_timeout_sec`
- `poll_interval_sec`
- `ws_enabled`
- `workflow_manifest_dir`

说明：

- `comfy_root_dir`、`comfy_input_dir`、`comfy_output_dir`、`temp_dir`、`workflow_manifest_dir` 支持绝对路径和相对路径
- 相对路径默认相对于项目根目录解析
- 当 `path_style = linux` 时，`/home/...`、`/mnt/...` 等 Linux 绝对路径会按绝对路径处理

## 8. 后端 API

### 8.1 静态资源

- `GET /`
- `GET /app.js`
- `GET /style.css`

### 8.2 配置接口

- `GET /api/config`
- `GET /api/prompt-config/image`
- `POST /api/prompt-config/image`
- `GET /api/prompt-config/image_edit`
- `POST /api/prompt-config/image_edit`
- `GET /api/prompt-config/video`
- `POST /api/prompt-config/video`
- `GET /api/runtime-config/image`
- `POST /api/runtime-config/image`
- `GET /api/runtime-config/image_edit`
- `POST /api/runtime-config/image_edit`
- `GET /api/runtime-config/video`
- `POST /api/runtime-config/video`
- `GET /api/comfy/config`
- `POST /api/comfy/config`
- `GET /api/comfy/templates`
- `GET /api/comfy/health`

### 8.3 Prompt 接口

- `POST /api/generate`
- `POST /api/generate/image-prompt`
- `POST /api/generate/image-edit-prompt`
- `POST /api/generate/video-prompt`
- `POST /api/video/scan-match`

### 8.4 Comfy 接口

- `POST /api/comfy/run`
- `POST /api/comfy/cancel`
- `POST /api/comfy/retry`

`/api/comfy/retry` 当前支持：

- `failedOnly = true`
- `skipSucceeded = true`

### 8.5 剪辑接口

- `GET /api/clip/presets`
- `POST /api/clip/run`

### 8.6 任务接口

- `GET /api/jobs/{jobId}`
- `GET /api/jobs/{jobId}/files`
- `GET /api/jobs/{jobId}/files/{filename}`
- `POST /api/jobs/{jobId}/open-output`

### 8.7 会话与应用接口

- `POST /api/browser-session/register`
- `POST /api/browser-session/heartbeat`
- `POST /api/browser-session/close`
- `POST /api/app/terminate`

## 9. 输出设计

### 9.1 Prompt 任务

每次任务会创建时间戳目录，通常包含：

- `*.prompt.json`
- `*.prompt.txt`
- `prompts.csv`
- `source_media/`

`prompts.csv` 的关键列包括：

- `image_path`
- `video_path`
- `image_name`
- `video_name`
- `positive_prompt`
- `negative_prompt`
- `seed`
- `output_prefix`
- `params_json`
- `workflow_type`
- `prompt_module`

### 9.2 Comfy 任务

任务输出以回收到的 `ComfyUI` 结果为主，任务状态中会记录：

- `csv_path`
- `row_count`
- `selected_row_count`
- `selected_row_indices`
- `prompt_id`
- `current_row`
- `current_node`
- `result_path`
- `queue_pending`
- `queue_running`
- `failures`

结构化失败项字段包括：

- `row_index`
- `name`
- `stage`
- `error_code`
- `message`
- `retryable`
- `prompt_id`
- `detail`

### 9.3 视频剪辑任务

每次任务会创建独立时间戳目录。

常见输出：

- 裁切或合并后的视频
- 预览帧
- `manifest.json`
- `summary.csv`

## 10. 本地依赖与平台兼容

### 10.1 Prompt 与 Comfy

- 核心后端仅依赖 Python 标准库即可运行
- `ComfyUI` 需要用户本机已启动并可访问
- WebSocket 监听可关闭，关闭后回退到 HTTP 轮询

### 10.2 视频剪辑

视频剪辑模块依赖：

- `opencv-python`
- `imageio-ffmpeg`

技术要点：

- Windows 启动器优先使用 `.venv\Scripts\python.exe`
- Linux 启动脚本优先使用 `.venv/bin/python`
- `video_clip_service.py` 优先使用 `imageio-ffmpeg` 提供的 ffmpeg 二进制
- 不要求系统 PATH 预装全局 `ffmpeg`

### 10.3 路径兼容

- 配置与表单支持 Windows / Linux 常见路径文本
- 相对路径默认相对于项目根目录解析
- Comfy workflow 中写入的是逻辑相对引用，不是 App 原始绝对路径
- `open-output` 在 Windows 下走 `os.startfile`
- `open-output` 在 Linux 下走 `xdg-open`
- 浏览器目录选择同时声明 `webkitdirectory`、`directory` 和 `mozdirectory`，兼容 Linux 下常见浏览器，并保留目录内的相对路径

## 11. 已知限制

- SQLite 保存的是任务级快照；视频流程已提供批次历史，跨模块的统一筛选与归档仍未实现
- 服务异常退出时，运行中的后台线程无法续接，任务会恢复为失败状态，需要从失败项或未完成项续跑
- 没有登录、权限和多人协作
- 视频匹配还没有独立的手工修正 UI
- Prompt 结果还没有专门的二次编辑页
- Comfy 工作台当前仍以 `CSV` 批量导入为主
- 对复杂工作流的 bindings 自动推断仍是启发式，不保证覆盖所有社区工作流
- 不同 workflow 之间的输入节点、Prompt 节点、输出节点格式差异较大；量产前应按模板逐个校验并固化 bindings
- `overwrite` 当前更多是兼容字段；由于默认按任务时间戳目录输出，跨任务运行一般不会直接覆盖旧结果
- LLM 调用层缺少完整的重试、限流、多供应商适配

## 12. 视频流程编排

`video_flow_service.py` 将单条原视频组织为串行步骤。`video-flows.js` 提供独立入口、持久化历史、步骤编辑和产物预览。复用 `OpenAICompatibleClient` 和 `run_comfy_job`，媒体处理由 `video_flow_media.py` 的 FFmpeg 操作完成。

### 12.1 状态与素材

- 配方：`spatial`、`prefix`、`suffix`、`mixed`。混合固定先空间再时间，可选择时间替换方向。
- 流程状态：`draft / running / ready / completed / failed`；步骤状态：`pending / running / completed / failed`。
- JSON 清单写到 `output/video_flows/<id>/flow.json`，采用临时文件原子替换；运行日志及工作线程由原 SQLite JobStore 管理。
- 每步产物使用命名键登记到 `artifacts`，如 `source_video / start_image / boundary_frame / replacement_video / final_video`。
- 每次执行使用独立 `attempt_NNN` 目录；Comfy 阶段使用独立作业编号，避免首图、尾图或参考图覆盖先前阶段的暂存文件。
- 修改或重跑上游会撤销该步和后续步骤的有效产物引用。旧磁盘文件保留，不作为当前结果再使用。
- 同一流程只允许一个工作线程。停止请求只在步骤边界生效。进程重启时无法续接的步骤标记失败，避免假装仍在执行。

### 12.2 模型与媒体约定

三个生产角色固定映射到项目模板：V5 输出节点 `1400`、Qwen 输出节点 `144`、Wan 2.2 输出节点 `145`。运行前验证绑定与输出节点存在，模板改变时明确报错。指定输出节点无文件时不能退回对比视频。

Comfy 新增 `start_image_ref / end_image_ref`，分别来自表单或 CSV 的 `start_image_path / end_image_path`；文件投递为各自的 `start.ext / end.ext`。Qwen 正负提示词按 conditioning 上游关系推断，避免把正向文字填入负向分支。

后段替换的 `endImagePath` 为可选输入。未提供时，`prepare` 在提取保留前段的末帧 `boundary_frame` 之外，另从完整源视频提取最后一帧，登记为该步骤输出 `target_end`；混合模式的完整源视频为已归一化的空间处理结果。后续 Prompt 与 Comfy 仍按 `boundary_frame → target_end` 使用双图，结束画面默认为原片或空间处理后的结尾。手动尾图始终优先，作为输入素材保留，不作为 `prepare` 输出；因此重跑准备步骤会作废并重取自动尾图，但不会删除手动尾图引用。

V5 的前后景选择映射为 RMBG `invert_output`，新流程关闭 77 帧加载上限。I2V 使用 16fps，帧数向上选择 `4n+1`；成片阶段将生成段时长匹配待替换区间。固定 V5 模板先将源画面非等比缩放成方形，因此空间结果通过直接缩放到原片宽高反向还原；时间替换的生成片段仍使用等比缩放补边。混合任务先将空间结果匹配原片时间轴，再进行裁切。新媒体路径统一原片帧率和尺寸，可映射原片音轨；不改动旧剪辑工作台预设。

媒体导出将 OpenCV 读取的帧率还原为有理数，滤镜 `fps`、编码 `-r:v` 与 `-enc_time_base:v` 使用同一帧率，显式指定 `-fps_mode:v cfr`；MP4 轨道 timescale 取帧率分子的整数倍，确保每帧对应整数 ticks。保留 `30000/1001`、`1197/40` 等速率；可变帧率素材按已读取的平均帧率归一为恒定帧率。若旧版系统 FFmpeg 在开始编码前明确拒绝 `fps_mode` 选项，则仅将该选项替换为 `-vsync cfr` 重试；其他编码错误直接报告。参数语义参见 [FFmpeg 编码与帧率选项](https://ffmpeg.org/ffmpeg.html#Advanced-options) 和 [MP4 timescale](https://ffmpeg.org/ffmpeg-formats.html)。

输出独立检查时长、尺寸和帧率。超过原有 0.1% 帧率阈值时，只有相对差不超过 1%、累计差不超过一帧且输出帧数与目标相差不超过一帧，才按容器平均帧率的取整差异接受；不会将 30→16/25 等实质失配视作成功。错误包含目标/实际 FPS、帧数、时长。媒体测试独立模拟源文件和输出元数据，覆盖非整数/VFR 平均速率以及通过、拒绝两类校验结果。

每次执行自动 Prompt 生成时，按步骤 `settings.apiKind` 读取对应模块已保存的 API 配置以及 Prompt 配置中的 `system_prompt / user_text`。`video` 用于空间替换、`image_edit` 用于新首图、`image` 用于首尾帧过渡。以模块的 System Prompt 和 User Prompt 为基础，在 User Prompt 末尾追加本步任务范围、实际媒体顺序和时长；双图提示词同时输入首尾两张图。明确禁止 Mock 回退。手动保存正向提示词后可绕过该步的 LLM 调用。

配置在实际调用模型时读取，流程创建时不固化全局配置副本。修改全局配置不会自动作废已经生成的 Prompt 或下游产物；用户需重跑相应提示词步骤及后续步骤。`promptEdited` 保留手工提示词优先规则：已手动保存的正向文字继续使用，如需重新调用模型须清空并保存该步正向提示词。前端每个提示词步骤显示配置来源，并将 `image / image_edit / video` 分别导航到原工作台的 `image / imageEdit / video` 子模块。

结果复用对应模块的 JSON 解析及正负向提取规则：显式正负向字段优先，否则读取 `en_prompt / zh_prompt`，并从 `avoid` 与该模块默认负向词归一化负向提示词。自动调用在步骤目录保存 `prompt_request.json`，成功后登记为可下载产物，记录实际 System/User、配置路径和媒体角色；不写入 API 配置或媒体编码内容。

### 12.3 接口

时间范围由 `cutMode` 选择：`seconds` 使用 `cutSeconds`，`percent` 使用 `replacePercent`（有限数值，严格在 0–100 之间）。省略 `cutMode` 的旧请求和已保存流程按秒数解释；前端新建任务默认按比例。创建阶段仅校验配置，执行阶段在任何 Prompt/GPU 步骤之前读取原视频时长并计算切点：前段为 `duration * replacePercent / 100`，后段为 `duration * (1 - replacePercent / 100)`。混合模式也以原视频为基准。计算结果保存为流程的 `inputs.cutSeconds`，供剪辑、拼接和重试使用；两侧至少一帧的校验仍适用，日志记录比例与实际切点。

| 接口 | 用途 |
| --- | --- |
| `GET /api/video-flows` | 流程历史 |
| `GET /api/video-flows/options` | 模式及固定模板说明 |
| `POST /api/video-flows` | 创建配置，不执行生成 |
| `GET /api/video-flows/<id>` | 当前步骤、配置、产物和错误 |
| `POST /api/video-flows/<id>/run` | `stepId` 可选；`runAll` 控制单步或连续执行 |
| `POST /api/video-flows/<id>/stop` | 当前步骤结束后停止 |
| `POST /api/video-flows/<id>/steps/<stepId>` | 修改提示词、负向提示词或指令，并作废后续结果 |
| `GET /api/video-flows/<id>/files/<artifactKey>` | 流式读取已登记素材，支持 Range 视频预览 |

生成任务继续使用 `GET /api/jobs/<jobId>` 获取日志。上传复用 `/api/comfy/upload`。流程界面按真实完成步骤显示进度，不以单次工作线程结束作为全流程结束。

### 12.4 批量流程

`video_batch_inputs.py` 提供服务器目录递归扫描及浏览器文件元数据匹配，沿用视频与主参考图同名、`_1 / _2` 为补充图的规则。支持输入 `{defaults, inputMode, directories, files}`：目录和文件角色均为 `videos / references / startImages / endImages`。返回匹配条目、素材角色、问题及待创建的 `rows`；浏览器素材缺少服务器路径时标记需要上传。重复候选不静默选择。纯时间模式将参考目录解释为可选的新首图或目标尾图；混合模式的参考目录始终服务空间替换，时间目标走独立目录。`endImagePath` 不再列为必需素材，未匹配到尾图且无共用尾图的组在执行时自动取末帧；同一批可混用手动尾图与自动取帧，已提供但重名冲突的素材仍报错。

`video_batch_service.py` 管理同一配方的多组素材，`video-batches.js` 提供文件夹匹配、一键执行、高级 CSV、批次历史、行状态与成片入口。创建参数为 `{name, defaults, rows}`，`defaults` 复用单流程配置，`rows` 仅覆盖名称、素材、时间范围和编辑需求；所有行统一模式、方向、空间范围与自动 Prompt 来源。时间范围支持 `cutMode / replacePercent / cutSeconds`，行内显式 `cutMode` 优先；无显式模式时，非空 `replacePercent` 推断为按比例，否则非空 `cutSeconds` 推断为按秒，其余继承默认配置。每组按各自原视频的时长解析比例。要求至少一组，不人为限定总组数，先验证全体行，再保存批次和子流程。前端的一键执行依次调用扫描、必要的上传、创建和启动；扫描有阻塞项时整批不启动，创建成功但启动失败的批次仍可从历史恢复。

补充参考图登记为独立素材，按主图、补图1、补图2顺序交给空间 Prompt 模块；Comfy V5 始终绑定主图，导出的提示词 CSV 也保留主图路径。

每行引用一个独立子流程，继续使用 `video_flow_service.py` 的执行、重试、提示词和产物机制。批次由一个工作线程串行消费，同进程只允许一个批次活动；批次运行期间预留其子流程，拒绝从单流程接口独立启动或编辑。`batchId / batchLocked` 暴露所属批次及只读状态，单流程历史可过滤子流程，批次中仍可打开对应详情。

批次 JSON 位于 `output/video_batches/<id>/`，按步骤/条目记录进度、错误和停止状态。普通条目失败后继续下一条；仅重试失败项时不重做成功项，重试从各子流程未完成的步骤开始。停止在当前步骤结束后生效，且不再取下一行。进程重启或生成结果不确定的超时会中断批次，显式继续前需确认 Comfy 队列状态。

| 接口 | 用途 |
| --- | --- |
| `GET /api/video-batches` | 批次历史摘要 |
| `POST /api/video-batches/scan` | 按流程角色匹配服务器目录或浏览器文件元数据，不执行生成 |
| `POST /api/video-batches` | 校验素材表并创建批次，不执行 |
| `GET /api/video-batches/<id>` | 总进度、每条状态及成片引用 |
| `POST /api/video-batches/<id>/run` | 开始或继续；`retryFailed: true` 仅重试失败 |
| `POST /api/video-batches/<id>/stop` | 当前步骤结束后停止整批 |
| `GET /api/video-batches/<id>/manifest.csv` | 当前结果汇总，包含状态、路径及错误 |
| `GET /api/video-batches/<id>/logs` | 最近的批次日志，含此前重试记录 |
| `GET /api/video-batches/<id>/logs.txt` | 完整批次日志文本 |

批次作业复用 JobStore，并把带时间戳的运行日志追加到批次目录的 `batch.log`，保留各次执行与重试记录；每条完成后记录成片路径。日志 API 返回最近 1000 行，完整文本可下载。内部 Comfy 的单项进度不得覆盖批次总进度；工作线程结束时采用返回的实际 `progress`，停止或中断不显示为全量完成。已有 Prompt 配置仍在各步骤真实调用时读取，不将密钥写进批次文件。

## 13. 后续扩展建议

建议优先级：

1. 给视频匹配补手工修正能力
2. 给 Prompt 结果补二次编辑能力
3. 给任务系统补批次级历史视图、筛选和归档能力
4. 给 Comfy bindings 补更明确的可视化映射编辑器
5. 给视频剪辑补更细粒度参数与自定义预设
