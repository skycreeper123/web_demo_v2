# Prompt Tool Web Demo 使用说明

## 1. 使用前准备

建议先确认：

- 你在 Windows 或 Linux 环境下运行
- 已安装 Python
- 可以打开本地浏览器

如果使用项目内虚拟环境，推荐：

```text
Windows: .venv\Scripts\python.exe
Linux:   .venv/bin/python
```

如果你要使用 `视频剪辑工作台`，先安装依赖：

Windows:

```powershell
.venv\Scripts\python.exe -m pip install opencv-python imageio-ffmpeg
```

Linux:

```bash
.venv/bin/python -m pip install opencv-python imageio-ffmpeg
```

如果你要使用 `本地 Comfy 通信工作台`，还需要：

- 本机已安装并启动 `ComfyUI`
- 浏览器能访问 `http://127.0.0.1:8188`

## 2. 启动方式

### 命令行启动

Windows:

```powershell
python .\backend\app\main.py
```

Linux:

```bash
python3 ./backend/app/main.py
```

启动后打开：

```text
http://127.0.0.1:8000
```

### 平台启动器

Windows：

- 双击 `PromptToolLauncher.exe`

Linux：

```bash
bash ./run_linux.sh
```

## 3. 页面结构

首页当前有 3 个入口：

- `Prompt 生成工作台`
- `本地 Comfy 通信工作台`
- `视频剪辑工作台`

顶部导航包含：

- `首页`
- `返回`
- `退出`

说明：

- 关闭页面后，服务不会立刻退出
- 只有在“没有浏览器会话”且“没有运行中任务”时，后端才会自动关闭

## 4. Prompt 生成工作台

Prompt 工作台包含 3 个子模块：

- 图片 -> I2V Prompt
- 图片 -> 图生图 Prompt
- 视频 -> 视频编辑 Prompt

它们共用一套基本流程：

1. 选择输入
2. 配置 API
3. 编辑 Prompt 配置
4. 运行并查看结果

### 4.1 图片 -> I2V Prompt

适合批量生成图生视频前置 Prompt。

输入方式：

- 选择图片
- 拖拽图片
- 选择图片文件夹
- 填写图片 URL

常用配置：

- `API Key`
- `Base URL`
- `Model`
- `输出目录`
- `图片源目录`
- `use_mock`
- `overwrite`

输出文件通常包括：

- `*.prompt.json`
- `*.prompt.txt`
- `prompts.csv`
- `source_media/images/*`

### 4.2 图片 -> 图生图 Prompt

适合批量生成高保真、小改动的编辑 Prompt。

输入方式与图片模块一致：

- 图片文件
- 图片文件夹
- 图片 URL

输出文件通常包括：

- `*.prompt.json`
- `*.prompt.txt`
- `prompts.csv`
- `source_media/images/*`

### 4.3 视频 -> 视频编辑 Prompt

适合根据视频和参考图生成视频编辑 Prompt。

推荐顺序：

1. 导入视频
2. 导入参考图
3. 点击 `扫描`
4. 确认匹配结果
5. 点击 `开始`

当前匹配规则是固定同名规则。

例如：

```text
a001.mp4
```

会尝试匹配：

- `a001.*`
- `a001_1.*`
- `a001_2.*`

输出文件通常包括：

- `*.prompt.json`
- `*.prompt.txt`
- `prompts.csv`
- `source_media/videos/*`
- `source_media/references/*`

说明：

- 这个模块不是视频剪辑器
- 它更适合“视频 + 参考图 -> Prompt”的批量生成流程
- 本地视频与参考图会优先落盘到任务目录，再写入 `prompts.csv`

## 5. Prompt CSV 的路径说明

### 5.1 本地文件输入时

如果你是通过浏览器选择本地图片、视频、参考图：

- 后端会把源文件保存到当前任务目录下的 `source_media/`
- `prompts.csv` 里的 `image_path` / `video_path` 会优先写入这些已保存文件的完整路径

这样做的目的，是让后续 `ComfyUI` 批处理能稳定拿到可访问的本地文件路径。

### 5.2 URL 输入时

如果你使用的是图片 URL 或视频 URL：

- `image_path` / `video_path` 可能为空
- `image_name` / `video_name` 仍会保留

这是正常行为，因为 URL 本身不是本地文件。

### 5.3 源目录字段的作用

界面里新增的：

- `图片源目录`
- `视频源目录`
- `参考图源目录`

当前主要用于前端辅助推导路径和保存配置。

## 6. 本地 Comfy 通信工作台

这个模块用于把 `prompts.csv` 批量提交给本机 `ComfyUI`。

### 6.1 使用前准备

先确认：

- `ComfyUI` 已启动
- 你知道它的地址，默认是 `http://127.0.0.1:8188`
- 你已经有一份 `prompts.csv`

最常见来源：

- 先运行 Prompt 生成工作台
- 然后使用生成目录里的 `prompts.csv`

### 6.2 基础流程

推荐顺序：

1. 先点 `检查连接`
2. 读取或保存 Comfy 配置
3. 选择模板，或直接填写工作流 JSON
4. 确认模板 `bindings`
5. 填写 `CSV 路径`
6. 需要时填写 `图片根目录` / `视频根目录`
7. 点击 `开始`

执行时，系统会把 CSV 指向的本地图片和视频复制到 ComfyUI 输入目录：

```text
ComfyUI/input/jobs/<prompt_id>/input.<ext>
ComfyUI/input/jobs/<prompt_id>/source.<ext>
```

写进 workflow 的不是 Windows 或 Linux 绝对路径，而是 `jobs/<prompt_id>/...` 相对引用。文件名会保留原始扩展名，因此 App 与自托管 ComfyUI 同机或共享可访问文件系统时，视频不会经过浏览器 base64 再投递给 ComfyUI。

### 6.3 模板与工作流

当前模板目录默认是：

- `workflow/`

支持两种来源：

- 已整理好的模板清单
- 原始 API 工作流 JSON

如果是常见且命名规范的原始 API 工作流 JSON，系统会尝试自动推断常见 bindings，例如：

- `positive_prompt`
- `negative_prompt`
- `image_ref`
- `video_ref`
- `seed`
- `output_prefix`

现在模板区支持：

- 查看模板的 bindings 预览
- 一键把模板 bindings 载入到右侧 `Bindings JSON`
- 再按具体 workflow 继续手工修改

自动推断只用于加快首次配置，不保证识别自定义节点、多个相似 Prompt 节点或复杂工作流。某个 workflow 敲定后，建议把人工确认过的 `Bindings JSON` 固化到模板文件中，后续批量任务直接使用该显式配置。

### 6.4 CSV 相关字段

Comfy 工作台会优先读取：

- `image_path`
- `video_path`
- `positive_prompt`
- `negative_prompt`
- `seed`
- `output_prefix`
- `params_json`
- `workflow_type`

如果路径列为空，才会回退到：

- `图片根目录 + image_name`
- `视频根目录 + video_name`

### 6.5 任务控制

Comfy 任务支持：

- `开始`
- `刷新`
- `取消`
- `重试`
- `仅重跑失败项`
- `跳过已成功项续跑`
- `导出失败 CSV`

状态可能包括：

- `待开始`
- `运行中`
- `已完成`
- `部分成功`
- `失败`
- `已取消`
- `超时`

### 6.6 失败详情

失败详情会按行展示，并包含：

- 第几行失败
- 失败阶段
- 错误码
- 错误消息
- 是否可直接重试
- 对应 `prompt_id`（如果已经提交到 ComfyUI）

常见阶段包括：

- `输入准备`
- `工作流绑定`
- `提交任务`
- `执行阶段`
- `结果回收`
- `任务超时`

补充说明：

- 如果一批里有部分行已经成功产出、另一部分失败，任务状态会显示为 `部分成功`
- 这时可以直接使用 `仅重跑失败项` 或 `跳过已成功项续跑`
- 单个本机 ComfyUI 的视频生成通常按其自身队列串行执行；当前应用也按 CSV 行顺序等待结果，以稳定定位输入、输出和失败项

## 7. 视频剪辑工作台

视频剪辑工作台直接读取本地目录，不走浏览器上传。

### 7.1 处理模式

有两种模式：

- `单文件夹裁切`
- `双文件夹合并`

单文件夹裁切：

- 按固定预设批量处理一个目录中的视频

双文件夹合并：

- 将两个目录中的视频按排序后一一配对并顺序拼接

### 7.2 剪辑预设

当前已集成的常用预设包括：

- 保留前 50%（ffmpeg）
- 保留前 50%（OpenCV）
- 保留前 30%
- 保留前 70%
- 保留前 3 秒 / 5 秒 / 7 秒
- 保留后 3 秒 / 5 秒 / 7 秒
- 保留后 30% / 50% / 70%
- 双文件夹顺序合并

### 7.3 输入路径

单文件夹模式填写：

- `视频输入文件夹`

双文件夹模式填写：

- `文件夹 A`
- `文件夹 B`

说明：

- 输入框为空时现在会直接报错
- 不会再把空值误当成当前工作目录

### 7.4 输出目录

建议使用相对路径，例如：

```text
output/video_clip
```

每次运行都会自动创建新的时间戳目录。

### 7.5 结果内容

剪辑任务通常会生成：

- 输出视频
- 预览帧
- `manifest.json`
- `summary.csv`

## 8. 配置文件

### 8.1 API 配置

文件：

- `backend/api_config.json`

包含 3 个模块：

- `image`
- `image_edit`
- `video`

常见字段：

- `api_key`
- `base_url`
- `model`
- `output_dir`
- `source_root_dir`
- `video_source_root_dir`
- `reference_source_root_dir`
- `use_mock`
- `overwrite`

补充说明：

- 当前默认按时间戳目录输出
- 所以 `overwrite` 更多是兼容性配置，不会在普通跨任务运行里直接覆盖旧结果

### 8.2 Prompt 配置

文件：

- `backend/image_prompt_config.json`
- `backend/image_edit_prompt_config.json`
- `backend/video_prompt_config.json`

字段包括：

- `system_prompt`
- `user_text`
- `mock_result`

### 8.3 Comfy 配置

文件：

- `backend/comfyui_comm_config.json`

字段包括：

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

路径说明：

- 上述路径字段既可以填写绝对路径，也可以填写相对路径
- 相对路径默认相对于项目根目录解析
- 如果要填写 Linux 绝对路径，请在 Comfy 通信工作台勾选“使用 Linux 路径模式”，这样 `/home/...`、`/mnt/...` 会被按绝对路径识别

## 9. 日志与排错

日志目录：

- `logs/app.log`
- `logs/error.log`
- `logs/http.log`
- `logs/jobs/{job_id}.log`
- `backend/jobs.sqlite3`

排错建议：

- 接口有没有被调用
  - 看 `logs/http.log`
- 某个任务中途为什么失败
  - 看对应的 `logs/jobs/{job_id}.log`
- 程序有没有全局异常
  - 看 `logs/error.log`
- Comfy 某一行为什么失败
  - 先看界面的“失败详情”
  - 再结合任务日志定位具体阶段
- 重启后还能不能查看过去任务
  - `backend/jobs.sqlite3` 会保存任务状态、日志、输出和失败详情

## 10. 常见问题

### 为什么没填 API Key 也能运行

因为支持 `mock` 模式。

只要满足以下任一条件，就会走模拟结果：

- `use_mock = true`
- `API Key` 为空

### 为什么新的 CSV 里路径有时不是原始素材目录，而是 `source_media`

因为浏览器环境通常不能稳定提供本地原始绝对路径。

所以当前实现会把本地上传素材先保存到任务目录，再把这个真实存在的路径写入 CSV。这样后续 `ComfyUI` 批处理更稳定。

### 为什么 URL 模式下路径列还是空的

因为 URL 本身不是本地文件。

当前版本不会把远程 URL 自动下载成输入素材再写回 `image_path` / `video_path`。

### 为什么不同 workflow 不能一套参数直接通吃

因为不同 workflow 的节点输入名、Prompt 节点位置、媒体节点结构都可能不同。

所以当前推荐做法是：

- 用统一 `prompts.csv`
- 但按模板单独确认 `bindings`

对于已经验证过的量产工作流，应把 bindings 写进模板，不要每批都依赖自动推断。

### 服务重启后任务会怎样

已完成任务的状态、日志、输出和失败详情会保留在 `backend/jobs.sqlite3`。

如果服务在某个后台任务运行中退出，该线程无法在下次启动后继续执行；该任务会被恢复为失败状态。Comfy 批跑任务保留原始提交参数，可使用失败重跑或跳过成功项续跑。

### 为什么“仅重跑失败项”和“跳过已成功项续跑”是两种按钮

因为它们解决的问题不一样：

- `仅重跑失败项`
  - 只重试已失败的 CSV 行
- `跳过已成功项续跑`
  - 会把未成功的行重新跑一遍
  - 包括失败行，也包括上次未真正执行到的行

### 为什么视频剪辑模块跑不动

最常见原因是依赖未安装。

先执行：

Windows:

```powershell
.venv\Scripts\python.exe -m pip install opencv-python imageio-ffmpeg
```

Linux:

```bash
.venv/bin/python -m pip install opencv-python imageio-ffmpeg
```

### 为什么 Linux 下目录选择体验不一致

因为浏览器对目录选择属性的支持存在差异。前端同时使用 `webkitdirectory`、`directory` 和 `mozdirectory`，以兼容 Linux 下常见的 Chrome、Edge 和 Firefox。

建议：

- 使用 Chrome 或 Edge

### 为什么“打开目录”没有反应

Linux 下通常是因为：

- 缺少 `xdg-open`
- 没有关联文件管理器

## 11. 文档入口

- 项目总览：[README.md](./README.md)
- 技术实现：[TECHNICAL.md](./TECHNICAL.md)
