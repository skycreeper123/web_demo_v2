# AI 视频生视频 Prompt 模板汇报文档

## 1. 汇报目的

本文档参考多篇 **视频生视频 Video-to-Video, V2V** 相关真实文献，整理这些论文中实际采用的 prompt 组织方式，并进一步归纳出一个可直接落地的通用视频生视频 prompt 模板。

这里的目标不是把一段视频完全重画一遍，而是在已有输入视频的前提下，让模型明确理解：

- 哪些内容必须保留；
- 哪些内容需要被编辑；
- 编辑后希望呈现什么新属性、新主体或新风格；
- 原有动作、镜头和时序关系是否需要保持；
- 哪些闪烁、漂移、跳变或形变必须避免。

## 2. 文献中的 Prompt 格式总结

| 文献 | Prompt 使用方式 | 对视频生视频 Prompt 的启发 |
| --- | --- | --- |
| FateZero | 使用 `source prompt + target prompt`；论文中明确写到目标 prompt 往往通过“替换或增加几个词”来设计，并支持 style、attribute、shape editing。 | 视频生视频 prompt 很适合采用“保留原视频语义骨架，只替换少量关键词”的写法。 |
| Video-P2P | 明确沿用 Prompt-to-Prompt 思路到视频，支持 `word swap`、`prompt refinement`、`attention re-weighting`。 | 视频编辑中，文字改动越克制，越有利于保留原视频姿态、场景和镜头。 |
| TokenFlow | 输入是 `source video + target text prompt`；目标是“符合 target text，同时保持原视频 spatial layout 和 motion”。 | 视频生视频模板必须同时写“编辑目标”和“时序保持要求”。 |
| Rerender A Video | 输入是文本引导的 V2V prompt，重点是 key frame translation + full video translation，并兼容 LoRA、ControlNet 等额外条件。 | 对视频生视频来说，prompt 里需要明确全局风格、局部纹理变化，以及帧间连续性。 |
| AnyV2V | 将 V2V 拆成“先编辑第一帧，再用 I2V 模型扩展整段视频”；支持 prompt-based editing、reference-based style transfer、subject-driven editing、identity manipulation。 | 视频生视频 prompt 不应只描述单帧结果，还应写清第一帧编辑结果如何在全视频中持续保持。 |

## 3. 综合结论

从这些文献可以看出，视频生视频 prompt 的核心不是“把视频重画一遍”，而是“在保持原视频时序、运动、镜头逻辑的前提下进行可控编辑”。

文献中最常见的三种 prompt 组织方式是：

1. **源视频语义 prompt + 编辑后目标 prompt**
2. **源视频 + 目标文本描述**
3. **先编辑第一帧，再将编辑结果扩展到整段视频**

因此，一个完整的视频生视频 prompt 往往应包含以下信息层：

- 原视频保持层：主体身份、动作轨迹、场景布局、镜头运动、物体数量；
- 编辑目标层：要改的主体、属性、材质、风格或对象类别；
- 时序一致性层：跨帧连续、不要闪烁、不要跳变、不要身份漂移；
- 运动保持层：保留原动作节奏、镜头路径、交互关系；
- 风格质量层：整体风格、颜色体系、材质表现、清晰度；
- 负向约束层：不要帧间不一致、不要背景重构、不要形体崩坏、不要突然新增元素。

## 4. 推荐 Prompt 模板

```text
基于输入视频生成一段编辑后的视频。保持原视频中的主体身份、动作节奏、场景布局、镜头运动、物体数量和主要时序关系一致，只对指定内容进行编辑。

编辑对象：
[要修改的主体/物体/区域]

编辑类型：
[替换主体/改属性/改材质/改风格/改背景/局部增强/整体风格迁移]

目标效果：
[最终希望变成什么]

时序一致性要求：
[跨帧保持一致；不要闪烁；不要跳帧；不要身份漂移；不要局部忽隐忽现]

运动与镜头保持：
[保留原动作轨迹、速度、镜头推进/平移/跟拍方式]

保持不变：
[主体身份、姿态节奏、场景结构、空间关系、物体数量、镜头路径等]

风格与画质：
[写实/电影感/水彩/动漫/油画/高质量/清晰纹理/稳定光照]

避免：
[不要改变未指定主体；不要背景大幅重构；不要帧间颜色跳变；不要肢体或物体形变；不要新增无关元素；不要水印、乱码、闪烁或抖动]
```

## 5. 英文精简模板

```text
Edit the input video while preserving the subject identity, motion trajectory, scene layout, camera path, object count, and temporal coherence of the original video.

Modify [target subject or region] by [edit operation]. Change it into [desired result], while keeping [important unchanged elements] consistent across frames.

Preserve the original motion rhythm and camera movement. Maintain strong temporal consistency with no flicker, no sudden appearance changes, no identity drift, and no structural collapse. Use a [visual style] look with [lighting / texture / quality].
```

## 6. 示例 Prompt

### 示例 1：人物视频风格化

```text
基于输入视频生成一段编辑后的视频。保持人物身份、动作轨迹、镜头跟拍方式和场景布局一致，只改变整体视觉风格。

将整段视频改为吉卜力动画电影风格，保留人物的动作、表情、服装轮廓和背景构图。画面色彩柔和，光影温暖，线条干净，整体具有高质量手绘动画感。

保持跨帧风格一致，不要闪烁，不要人物脸部漂移，不要背景突然变化，不要出现多余角色、畸形手部或水印。
```

### 示例 2：车辆替换

```text
基于输入视频生成一段编辑后的视频。保持道路、镜头运动、车辆行驶轨迹和周围环境一致。

将视频中的黑色轿车替换为红色复古跑车，保留原有的速度、转向路径、光照方向和地面接触关系。整体保持真实电影感和高细节反射。

不要改变道路布局，不要让车体在不同帧中形状不一致，不要新增其他车辆，不要出现轮胎漂浮、闪烁、拖影或背景重构。
```

### 示例 3：局部材质增强

```text
基于输入视频生成一段编辑后的视频。保持鸟的飞行动作、镜头视角、背景河流和岸边环境一致。

将鸟的羽毛材质改成水晶质感，保留鸟的体型、飞行轨迹和整体结构。让水晶反光在不同帧中连续稳定，整体画面仍然清晰、自然、具有高级视觉质感。

不要改变鸟的种类和动作，不要让羽毛闪烁或忽明忽暗，不要破坏背景结构，不要新增无关元素或出现形体崩坏。
```

## 7. 使用建议

填写视频生视频 prompt 时，建议优先保证以下顺序：

1. 先写清楚“原视频哪些时序和结构要保持”。
2. 再写“要改哪个主体/属性/风格”。
3. 然后写“动作、镜头、运动轨迹是否保持”。
4. 接着写“跨帧一致性要求”。
5. 最后补充“风格画质”和“避免事项”。

视频生视频里最常见的问题不是“单帧不够像”，而是“帧与帧之间不一致”。因此 prompt 需要比图生图更明确地写时序稳定要求。

## 8. 质量检查清单

- 编辑目标是否在所有帧中都保持一致；
- 主体身份、动作轨迹和镜头路径是否保留；
- 是否存在闪烁、跳变、局部忽隐忽现；
- 替换对象或材质是否跨帧稳定；
- 背景和空间布局是否被错误重构；
- 动作速度和节奏是否自然；
- 视频整体风格是否统一；
- 是否出现水印、乱码、抖动、拖影或形体崩坏。

## 9. 最终推荐公式

```text
视频生视频 Prompt =
原视频保持要求
+ 编辑对象
+ 编辑类型
+ 目标结果
+ 时序一致性要求
+ 动作/镜头保持
+ 风格画质
+ 保持不变项
+ 负向约束
```

最核心的写法可以概括为：

```text
在不破坏原视频主体、动作、镜头和场景结构的前提下，对指定内容进行稳定、连续、跨帧一致的编辑，并明确禁止闪烁、漂移、跳变和背景重构。
```

## 10. 参考文献链接

以下链接均为本文档归纳时直接参考的真实论文或官方项目页：

1. FateZero: Fusing Attentions for Zero-shot Text-based Video Editing
   [https://arxiv.org/abs/2303.09535](https://arxiv.org/abs/2303.09535)
2. Video-P2P: Video Editing with Cross-attention Control
   [https://video-p2p.github.io/](https://video-p2p.github.io/)
3. TokenFlow: Consistent Diffusion Features for Consistent Video Editing
   [https://arxiv.org/abs/2307.10373](https://arxiv.org/abs/2307.10373)
4. Rerender A Video: Zero-Shot Text-Guided Video-to-Video Translation
   [https://arxiv.org/abs/2306.07954](https://arxiv.org/abs/2306.07954)
5. Rerender A Video 官方项目页
   [https://www.mmlab-ntu.com/project/rerender/](https://www.mmlab-ntu.com/project/rerender/)
6. AnyV2V: A Tuning-Free Framework For Any Video-to-Video Editing Tasks
   [https://arxiv.org/abs/2403.14468](https://arxiv.org/abs/2403.14468)
7. AnyV2V 官方项目页
   [https://tiger-ai-lab.github.io/AnyV2V/](https://tiger-ai-lab.github.io/AnyV2V/)
