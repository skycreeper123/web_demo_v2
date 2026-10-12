from pathlib import Path
from urllib.parse import quote, unquote
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parent
rows = json.loads((ROOT / 'reference_manifest.json').read_text(encoding='utf-8'))
notes = {
    'f5_tts.json': (
        'R19 · MikeBot 语音参考（API 图）', '历史参考，暂不直接接生产',
        'LoadAudio → F5TTSAudioInputs → SaveAudio；Textbox 分别提供参考音频转录和目标台词。',
        '参考音频必须由你提供，参考转录必须逐字匹配。交付文件已改为 reference_voice.wav 和中性示例文案，不包含原作者身份音频。节点包来源及与当前 F5 模型的兼容性尚需在安装前确认；不同权重的许可也应单独核对。',
        '这是 class_type/inputs 形式的 API JSON，没有 UI 节点坐标。不能按常规画布图的导入方式保证恢复；先在 ComfyUI 里重建短链，再核对其 /object_info 与实际 API 字段。音频投递是工作台接入的前置条件。'),
    'latentsync_with_frame_interpolation.json': (
        'R20 · MikeBot 旧口型参考（API 图）', '历史参考；优先采用第一轮当前 wrapper 图',
        'VHS_LoadVideo ＋ LoadAudio → D_VideoLengthAdjuster → D_LatentSyncNode → VHS_VideoCombine。',
        '原作者示例仍引用 Mike_Test.mp4 与 MichaelPoundVoice4.mp3；这些媒体未提供，应改为自备视频和音频。图中加载、长度调节和导出均为 25fps；默认 pingpong 会为较长音频往返重复帧。',
        '当前 ShmuelRonen wrapper 注册 LatentSyncNode / VideoLengthAdjuster，没有这些 D_ 名称。不能只改类名就假设输入字段兼容。文件名含 interpolation，但静态图没有独立 FILM/RIFE 插帧节点。第一轮的 UI 示例也要核对所选 checkpoint，文件名 1.5 不等于实际运行版本。'),
    'Lightweight VACE Clip Joiner v1.0.4.json': (
        'R21 · 两片段接缝（UI 图）', '第二批，先于 full 验证',
        '两路 LoadVideo → GetVideoComponents → WanVACEPrep → WanVaceToVideo → 采样／解码 → 视频保存。',
        '原作者的 ComfyUI-Wan-VACE-Prep 是核心附加节点；地址为 https://github.com/stuttlepress/ComfyUI-Wan-VACE-Prep 。当前快照默认使用 Wan2.2 Fun VACE 高低噪 14B 与匹配 LoRA，轻量指图结构，不能推导显存低。',
        '两路视频要分别投递，统一尺寸／帧率并保留必要上下文。先避免可选编译或非本机支持的加速路径。要改 Wan2.1 VACE 时，应按作者说明替换完整采样配置，不能把普通 T2V 权重当 VACE 使用。'),
    'VACE Clip Joiner v2.5.json': (
        'R22 · 多片段／循环接缝（UI 图）', 'R21 通过后再研究批处理',
        '视频目录排序 → 逐接缝上下文生成 → 颜色／交叉淡化选项 → 合并；图含多个嵌套子图。',
        '作者列出的依赖包含 Wan-VACE-Prep、KJNodes、VideoHelperSuite、Basic data handling、mxToolkit。静态图还出现 rgthree 标签节点；以实际启用节点和 Manager 缺失清单核对，不只照抄摘要。',
        '先将输入限定为两段，确认顺序、帧数和声音去向。色亮变化和帧对齐问题需要验收。图的目录路径、子图展开和前端版本可能影响 API 导出；本次没有导出成适配本工作台的生产图。'),
    'wanvideo_1_3B_UniLumos_relight_example_01.json': (
        'R23 · 前景／背景视频重打光（UI 图）', '优先做对照，不自动替代普通调色',
        '两路 VHS_LoadVideo → 尺寸／帧数对齐 → 前景去背景与条件编码 → WanVideoUniLumosEmbeds → WanVideoSampler → 解码。',
        '主要涉及 WanVideoWrapper、VideoHelperSuite、KJNodes，以及提供 TransparentBGSession+ / ImageRemoveBackground+ 的背景移除节点包。模型为 UniLumos 1.3B，配套 T5、VAE；图另加载 CausVid 1.3B LoRA。背景移除包版本需导入时继续核对。',
        '图内模型说明节点 84 的链接指向 FlashVSR，不能照它下载模型；节点 149 才指向 UniLumos 权重。图默认蒸馏采样与无蒸馏说明不同；保留成组配置做基线。前景视频 141 和背景视频 123 是不同资产，现有单 videoPath 投递需扩展。'),
    'droz_WanVaceAdvanced_VaceContextWindows_1.0.json': (
        'R24 · VACE 上下文窗口（UI 图）', '研究储备，尚未纳入首批实验',
        'WanVaceAdvanced 条件／窗口节点与模型补丁，配合遮罩、姿态及分段采样；用于研究更细的时间窗口控制。',
        '静态图包含 VaceAdvancedModelPatch、WanContextWindowsManual、WanVacePhantomSimpleV2、RES4LYF 的 Clown 系列采样节点、SAM2、姿态检测、KJNodes 与 VideoHelperSuite 等。依赖明显多于单一 VACE 编辑图。',
        '不能把有 context windows 解释为任意时长无缝处理，也不能直接等同于 Clip Joiner。先用简单 VACE 跑通短片，只有跨窗口一致性成为明确瓶颈时再研究此图。当前未验证量化、兼容性、3090 峰值显存或长片效果。'),
}

lines = ['# 第二轮新增工作流与静态核查结果', '',
         '2026-09-29 · 6 个文件：4 个 UI 图、2 个 API 图。与第一轮 18 个文件合计 24 个参考 JSON。', '',
         '**这些是研究参考，尚未在本机执行。** JSON 能解析不等于模型、插件、路径和显存都满足要求。UI 图需在 ComfyUI 中验证后导出 API；旧 API 图需核对当前节点注册与输入模式。', '',
         '来源固定到下载时仓库提交；manifest 同时保存源字节哈希与交付字节哈希。只有 R19 的占位文案和路径被修改，另外 5 个文件原样保存。仓库提交只是参考文件版本，不代表全部插件、模型和前端的锁定环境。', '',
         '| 编号／用途 | 格式 | 文件 | 建议 |', '| --- | --- | --- | --- |']
for row in rows:
    name = Path(row['path']).name
    title, status, chain, deps, caveat = notes[name]
    url = quote(row['local'], safe='/')
    lines.append(f'| {title.split(" · ")[0]} · {title.split(" · ")[1]} | {row["format"].upper()} | [{name}]({url}) | {status} |')

for row in rows:
    name = Path(row['path']).name
    title, status, chain, deps, caveat = notes[name]
    source = f'https://github.com/{row["repo"]}/blob/{row["commit"]}/{quote(row["path"], safe="/")}'
    lines += ['', f'## {title}', '', f'[本地文件]({quote(row["local"], safe="/")}) · [固定版本来源]({source})', '',
              f'**建议：{status}。**', '', f'链路：{chain}', '', f'准备：{deps}', '', f'核查发现：{caveat}', '',
              f'根图节点数：{row["top_level_nodes"]}。子图节点类型已递归登记在 manifest；未做所有连线语义验证。']
    if row['model_names']:
        lines += ['', '图中出现的模型文件名（包含候选／非激活分支，不能当作全部必需下载项）：', '']
        lines += [f'- `{m}`' for m in row['model_names']]
    if row['modifications']:
        lines += ['', '交付修改：参考转录和目标台词改为中性原创示例，音频路径改为自备素材占位，输出前缀改为 research/voice。实际参考转录仍需与你自己的音频完全一致。']

lines += ['', '## 本轮优先使用哪个文件', '',
          '补光试验先看 R23；接缝探索先看 R21。真人口型优先沿用[第一轮 wrapper UI 图](../reference_workflows/ShmuelRonen__ComfyUI-LatentSyncWrapper/latentsync1.5_comfyui_basic.json)，结合当前插件核对版本。R19、R20 帮助理解真实创作者链路；R22、R24 留作后续能力研究。', '',
          '关键来源：[MikeBot 作者说明](https://github.com/Lewis-Stuart-11/MikeBot)、[当前 LatentSync 节点映射](https://raw.githubusercontent.com/ShmuelRonen/ComfyUI-LatentSyncWrapper/main/nodes.py)、[Clip Joiner 说明](https://github.com/stuttlepress/ComfyUI-Wan-VACE-Video-Joiner)、[轻量版说明](https://github.com/stuttlepress/ComfyUI-Wan-VACE-Video-Joiner/blob/main/README-lightweight.md)、[WanVaceAdvanced](https://github.com/drozbay/ComfyUI-WanVaceAdvanced)。', '',
          '[返回案例报告](案例驱动迭代报告.md) · [机器可读来源记录](reference_manifest.json)', '']
(ROOT / '新增工作流与核查结果.md').write_text('\n'.join(lines), encoding='utf-8')

verified = []
for row in rows:
    file = ROOT / row['local']
    content = file.read_bytes()
    graph = json.loads(content)
    assert hashlib.sha256(content).hexdigest() == row['sha256']
    assert isinstance(graph.get('nodes'), list) if row['format'] == 'ui' else all('class_type' in n and 'inputs' in n for n in graph.values())
    verified.append({'file': row['local'], 'format': row['format'], 'json_valid': True,
                     'delivery_hash_matches': True, 'unchanged_from_source': not row['modifications']})
report = {'checked_on': '2026-09-29', 'new_json_count': len(rows), 'total_reference_json_count': 24,
          'ui_count': 4, 'api_count': 2, 'gpu_executed': False, 'video_frame_review_completed': False,
          'files': verified}
(ROOT / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'new_files': len(rows), 'ui': 4, 'api': 2, 'json_and_hash_check': 'passed'}, ensure_ascii=False))
