from pathlib import Path
import json
import hashlib
import re

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent.parent
rows = json.loads((ROOT / 'reference_workflows_manifest.json').read_text(encoding='utf-8-sig'))
descriptions = {
    'wanvideo_1_3B_ReCamMaster_example_01.json': ('W10 重运镜', '研究候选', 'WanVideoWrapper、VideoHelperSuite、KJNodes；图含 Florence2 辅助分支，按实际启用路径核对。', '从小角度变化开始；新露出区域不保证商品几何准确。'),
    'wanvideo_1_3B_VACE_examples_03.json': ('W01/W07/W08 VACE 多能力', '优先测试', 'WanVideoWrapper、VideoHelperSuite、KJNodes；深度分支需要对应 DepthAnything 节点。', '1.3B 用于条件链调通；综合图应先只保留一种任务分支。'),
    'wanvideo_2_1_14B_SCAIL_pose_control_example_01.json': ('W04 动作迁移', '第二批', 'WanVideoWrapper、SCAIL-Pose、WanAnimatePreprocess、VideoHelperSuite、KJNodes。', '第一代 SCAIL 示例；不要与 SCAIL-2 的模型和条件混用。'),
    'wanvideo_WanAnimate_preprocess_example_02.json': ('W03 人物替换与预处理', '现有基线对照', 'WanVideoWrapper、WanAnimatePreprocess、SAM2、VideoHelperSuite、KJNodes。', '姿态、分割与生成分阶段运行；参考图、mask、视频帧数要一致。'),
    'LTX-2.3_ICLoRA_DubIt_Two_Stage_Distilled.json': ('W12 音视频编辑候选', '资源储备', 'Lightricks/ComfyUI-LTXVideo 及模板要求的辅助节点。', '存在 GemmaAPITextEncode；必须核实激活分支。DubIt 不等同于已验证的任意音轨口型驱动。'),
    'LTX-2.5_ICLoRA_Inpaint_Two_Stage_Distilled.json': ('W12 局部修补候选', '资源储备', 'Lightricks/ComfyUI-LTXVideo；包含子图及本地/API 编码路径。', '官方插件前提 32GB+，3090 优化未测试；静态模型名包含候选/历史说明，按激活图下载。'),
    'video_wan21_scail2_character_replacement_int8.json': ('W03/W04 SCAIL-2 人物替换', '第二批', '当前 Comfy 原生 SCAIL 节点与 SAM3 分割相关依赖，检查子图。', 'INT8 仅代表权重方案，不能保证整条图 24GB 运行；需与旧基线对照。'),
    'video_wan2_2_14B_animate.json': ('W03 Wan2.2-Animate', '现有基线对照', '原生 WanAnimateToVideo；姿态与 SAM2 等预处理节点。', '与 Kijai Wrapper 路线区别对待；模型与 LoRA 按该图配套。'),
    'video_wan2_2_5B_fun_control.json': ('B04/F03 结构控制生成', '第二批', '原生 Wan22FunControlToVideo、Canny 等节点。', '控制结构不等于原片像素保持；使用 Fun Control 权重和 Wan2.2 VAE。'),
    'video_wan2_2_5B_fun_inpaint.json': ('W08 首尾帧桥接', '第二批', '原生 WanFunInpaintToVideo；两个 LoadImage 输入。', '核验图输入为首图和尾图；不能直接当成任意视频区域修补工作流。'),
    'video_wan2_2_5B_ti2v.json': ('W06 AI 补充镜头', '优先测试', '原生 Wan22ImageToVideoLatent、5B 主模型、UMT5、Wan2.2 VAE。', '可从真实照片或实拍帧起步；一次只生成一个简单镜头动作。'),
    'video_wan_animate2_distilled.json': ('W04 直接动作驱动', '第二批', '新原生 WanAnimate2ToVideo、WanAnimate2Cache 及配套模型。', '不需要骨架预处理；背景与视角可重新生成，不承诺原背景保留。'),
    'video_wan_vace_14B_v2v.json': ('B04 受控视频重绘', '第二批', '原生 WanVaceToVideo、Canny 等节点。', '先做写实结构保持；身份和包装精度需额外验收。'),
    'video_wan_vace_flf2v.json': ('W08 首尾帧生成', '第二批', '原生 WanVaceToVideo 与首尾参考输入。', '工作台需独立首图/尾图槽位；检查转场中间是否物理可信。'),
    'video_wan_vace_inpainting.json': ('W01 局部编辑', '优先测试', '原生 WanVaceToVideo、SAM3 分割、遮罩与 ImageCompositeMasked。', '当前图含 SAM3 与 fp8_fast 配置；3090 不照抄，先检查兼容并降低尺寸。'),
    'video_wan_vace_outpainting.json': ('W07 扩画', '第二批', '原生 WanVaceToVideo、画布与遮罩处理。', '先小幅扩边，合成时保留原画幅；不要用拉伸替代扩画。'),
    'latentsync1.5_comfyui_basic.json': ('W05 真人口型改写', '优先测试', 'ComfyUI-LatentSyncWrapper、VideoHelperSuite；LatentSyncNode、LoadAudio。', '文件名为 1.5，包装说明为 1.6；核对实际配置和 checkpoint。需新增音频投递。'),
    'propainter-inpainting-workflow.json': ('W01 物体移除对照', '仅技术研究', 'ComfyUI_ProPainter_Nodes、VideoHelperSuite 及图内尺寸/遮罩辅助节点。', '原作者明确非商业用途；该图不作为商业默认生产模板。'),
}

out = ['# ComfyUI 工作流目录与本地参考文件', '',
       '核查日期：2026-09-29。下列 18 张公开 UI JSON 已下载并解析。未安装依赖、未执行 GPU 推理；配套示例图片、视频和模型权重未下载。', '',
       '导入方法：在 ComfyUI 中打开对应 JSON，补齐依赖和素材，先单次验证；成功后导出 API 格式并人工绑定输入，才适合当前工作台批量调用。', '',
       '“原始快照”链接保留下载时的固定来源标识；附件 manifest 另记录文件 SHA-256。固定来源不代表全部插件的发布版本或锁定环境。依赖摘要用于选型，完整节点列表见 manifest；应按实际激活图核对节点包。', '',
       '| 序号 | 文件 | 用途 | 建议状态 |', '| --- | --- | --- | --- |']
verified = []
for i, row in enumerate(rows, 1):
    if row.get('error'):
        raise RuntimeError(row)
    file = WORKSPACE / row['local']
    wf = json.loads(file.read_text(encoding='utf-8-sig'))
    assert isinstance(wf.get('nodes'), list), file
    digest = hashlib.sha256(file.read_bytes()).hexdigest().upper()
    assert digest == row['sha256'], file
    desc = descriptions[row['file']]
    local = file.relative_to(ROOT).as_posix()
    out.append(f'| {i:02} | [{row["file"]}]({local}) | {desc[0]} | {desc[1]} |')
    verified.append({'file': row['file'], 'sha256': digest, 'json_valid': True, 'source_match': True})

for i, row in enumerate(rows, 1):
    desc = descriptions[row['file']]
    local = (WORKSPACE / row['local']).relative_to(ROOT).as_posix()
    url = row['source'].replace('https://raw.githubusercontent.com/', 'https://github.com/')
    parts = url.split('/')
    parts.insert(5, 'blob')
    url = '/'.join(parts)
    models = [x for x in row['models'] if len(x) < 140 and 'https:' not in x and '\\n' not in x]
    out += ['', f'## {i:02} · {desc[0]}', '',
            f'文件：[{row["file"]}]({local}) ｜ [原始快照]({url}) ｜ [原始 JSON 下载]({row["source"]})', '',
            f'建议：{desc[1]}。{desc[3]}', '', f'主要依赖：{desc[2]}', '']
    if models:
        out += ['图内出现的模型名（包含候选和未启用分支，不代表全部必须下载）：', '']
        out += [f'- `{x.replace(chr(92)+chr(92), chr(92))}`' for x in models]
    else:
        out += ['模型未以标准文件名出现在这张图中；需按对应节点包的模型下载说明准备。']

out += ['', '## 本次未交付的完整链路', '',
        '固定机位真人与 AI 背景合成、UniLumos 重打光、CosyVoice 旁白和多镜头成片编排，已给出路线与来源，但本次未保存成完整可执行的新工作流。不能将它们与以上已下载原始图混计。', '',
        '主报告：[调研报告](调研报告.md)；验收：[实验记录模板](实验记录模板.md)。', '']
(ROOT / '工作流目录.md').write_text('\n'.join(out), encoding='utf-8')
(ROOT / 'verification.json').write_text(json.dumps({'checked_on':'2026-09-29', 'count':len(verified), 'gpu_execution':False, 'files':verified}, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'workflow_count':len(verified),'json_and_hash_checks':'passed','catalog_written':True}, ensure_ascii=False))
