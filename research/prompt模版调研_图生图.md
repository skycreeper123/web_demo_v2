# AI 图生图 Prompt 模板汇报文档

## 1. 汇报目的

本文档参考多篇 **图生图 Image-to-Image, I2I** 相关真实文献，整理这些论文中实际采用的 prompt 组织方式，并进一步归纳出一个可直接落地的通用图生图 prompt 模板。

这里的目标不是重新完整描述一张图，而是在已有输入图像的前提下，让模型明确理解：

- 哪些内容必须保留；
- 哪些内容需要被编辑；
- 编辑是局部的还是全局的；
- 编辑后希望呈现什么新属性、新主体或新风格；
- 哪些错误、伪影或误改必须避免。

## 2. 文献中的 Prompt 格式总结

| 文献 | Prompt 使用方式 | 对图生图 Prompt 的启发 |
| --- | --- | --- |
| InstructPix2Pix | 输入是“原图 + 编辑指令”。论文明确强调用户不需要提供输入图或输出图的完整描述，而是直接给出“要怎么改”的自然语言指令。 | 图生图 prompt 应优先写“编辑动作”而不是重写整张图。 |
| MagicBrush | 采用 `(source image, instruction, target image)` 三元组；同时覆盖 single-turn、multi-turn、mask-free、mask-provided 四类编辑场景。 | 图生图模板应兼容单步编辑与多步编辑，并区分“仅文字编辑”和“局部区域编辑”。 |
| Prompt-to-Prompt | 使用“源 prompt → 目标 prompt”方式做编辑，核心操作包括 `word swap`、`adding a new phrase`、`attention re-weighting`。 | 当编辑是替换、补充、强调某个概念时，prompt 最好写成“原概念保持，其中特定词替换/增强”。 |
| Null-text Inversion | 先用“有意义的 source caption”将真实图像反演进模型，再配合 Prompt-to-Prompt 做编辑；项目页特别强调可编辑部位必须包含在源 caption 中。 | 真实图片编辑时，prompt 不能只写目标效果，还要显式点出原图里需要被跟踪和保留的可编辑对象。 |
| DiffEdit | 使用 `text query` 作为目标编辑描述，并使用 `reference text` 描述原图语义，通过二者差异自动推断应编辑区域。 | 图生图 prompt 很适合拆成“原图参考描述 + 目标编辑描述”，特别适合局部替换与最小改动场景。 |
| Plug-and-Play Diffusion Features | 输入是 `guidance image + target text prompt`，目标是“保持 guidance image 的语义布局，同时让结果符合目标文本”。 | 当用户关心构图、姿态、布局不变时，prompt 应显式写“保持布局/结构/语义位置关系”。 |
| Imagic | 输入是“单张真实图片 + target text”；目标文本直接表达期望编辑结果，尤其适合复杂非刚性语义编辑。 | 图生图模板除了属性替换，也应支持姿态变化、构图变化、主体状态变化。 |

## 3. 综合结论

从这些文献可以看出，图生图 prompt 的核心不是“描述整张图”，而是“告诉模型在原图基础上改什么、保留什么”。

文献中最常见的三种 prompt 组织方式是：

1. **原图 + 编辑指令**
2. **源 prompt + 目标 prompt**
3. **原图参考描述 + 目标编辑描述**

因此，一个完整的图生图 prompt 往往应包含以下信息层：

- 原图保持层：主体身份、构图、姿态、背景、物体数量、文字/logo；
- 编辑目标层：要改哪个主体、哪个属性、哪个区域；
- 编辑操作层：替换、增加、删除、变色、变材质、变风格、变姿态、变场景；
- 编辑范围层：局部还是全局，是否只改前景/背景/某个物体；
- 风格质量层：写实、产品图、电影感、插画感、广告感、清晰度；
- 负向约束层：不要过度改图、不要误改其他区域、不要脸部/手部畸形、不要文字错误。

## 4. 推荐 Prompt 模板

```text
基于输入图像生成一张编辑后的图像。尽量保持原图中的主体身份、姿态、构图、背景布局、物体数量、文字/logo 和整体画面风格不变，只对指定内容进行编辑。

编辑对象：
[需要修改的主体/区域/物体]

编辑类型：
[替换/增加/删除/改颜色/改材质/改姿态/改风格/改背景/改场景]

编辑指令：
[具体希望改成什么]

局部或全局范围：
[只改某个局部 / 只改前景 / 只改背景 / 全图统一风格变化]

保持不变：
[脸部身份、服装、姿态、构图、背景结构、文字、logo、数量关系等]

风格与画质：
[写实/电影感/商业广告/插画/动漫/高细节/柔和光线/自然色彩等]

避免：
[不要改动未指定区域；不要改变主体身份；不要新增无关物体；不要改变文字和 logo；不要让脸、手或边缘畸形；不要出现伪影、水印、乱码文字或过度重绘]
```

## 5. 英文精简模板

```text
Edit the input image while preserving the subject identity, pose, composition, background layout, object count, text/logo, and overall visual style as much as possible.

Modify [target object or region] by [edit operation]. Change it to [desired result]. Keep [important unchanged elements] unchanged.

Apply a [visual style] look with [lighting / texture / quality]. Avoid changing unrelated regions, altering the subject identity, modifying object counts, distorting faces or hands, changing text or logos, or introducing artifacts, watermarks, or unreadable text.
```

## 6. 示例 Prompt

### 示例 1：人物照片换服装

```text
基于输入图像生成一张编辑后的图像。保持人物的脸部身份、发型、站姿、构图和街景背景不变，只编辑服装。

将人物身上的黑色西装外套改为浅卡其色风衣，保留人物的脸、身体比例、姿态和原有背景。整体保持写实摄影风格，光线自然，衣物材质真实。

不要改变人物身份，不要改变裤子和鞋子，不要新增配饰，不要让手部、脸部或衣物边缘出现畸形，不要出现文字、水印或背景重构。
```

### 示例 2：产品图改材质

```text
基于输入图像生成一张编辑后的图像。保持产品形状、角度、构图、logo、包装文字和背景布置不变。

将产品外壳从磨砂塑料改为银色金属材质，强化边缘高光和金属反射，但不要改变产品结构和文字内容。整体风格保持干净、高级、商业广告感。

不要改变产品大小、logo、文字、颜色数量关系或背景道具，不要出现文字变形、反光脏污、伪影或水印。
```

### 示例 3：场景图局部替换

```text
基于输入图像生成一张编辑后的图像。保持桌面、碗、桌布和背景厨房环境不变。

将碗中的苹果替换为梨，保持水果摆放方式、光照方向和画面构图一致。整体仍然是自然写实风格。

不要改变碗的形状，不要改动其他水果和背景，不要新增物体，不要让水果边缘模糊、数量错误或产生不自然的重绘痕迹。
```

## 7. 使用建议

填写图生图 prompt 时，建议优先保证以下顺序：

1. 先写清楚“保持原图哪些内容不变”。
2. 再写“要改哪个对象或哪个区域”。
3. 然后写“改成什么”。
4. 接着写“局部还是全局变化”。
5. 最后补充“风格要求”和“避免事项”。

图生图里最常见的问题不是“不够会画”，而是“改太多”。因此 prompt 越要强调最小必要改动，越符合文献中高保真编辑的共同方向。

## 8. 质量检查清单

- 是否只修改了指定内容；
- 主体身份、构图、背景和数量关系是否保持；
- 未指定区域是否被误改；
- 文字、logo、包装信息是否被错误改变；
- 局部替换是否自然，没有硬边或糊边；
- 是否出现脸部、手部、边缘、反光等结构畸形；
- 整体风格和目标编辑是否与 prompt 一致；
- 是否出现伪影、水印、乱码或过度重绘。

## 9. 最终推荐公式

```text
图生图 Prompt =
原图保持要求
+ 编辑对象
+ 编辑类型
+ 目标结果
+ 局部/全局范围
+ 风格画质
+ 保持不变项
+ 负向约束
```

最核心的写法可以概括为：

```text
在尽量不破坏原图主体、构图和背景的前提下，只对指定对象进行明确、有限、可控的编辑，并显式禁止未指定区域被误改。
```

## 10. 参考文献链接

以下链接均为本文档归纳时直接参考的真实论文或官方项目页：

1. InstructPix2Pix: Learning to Follow Image Editing Instructions
   [https://arxiv.org/abs/2211.09800](https://arxiv.org/abs/2211.09800)
2. MagicBrush: A Manually Annotated Dataset for Instruction-Guided Image Editing
   [https://arxiv.org/abs/2306.10012](https://arxiv.org/abs/2306.10012)
3. Prompt-to-Prompt Image Editing with Cross Attention Control
   [https://arxiv.org/abs/2208.01626](https://arxiv.org/abs/2208.01626)
4. Null-text Inversion for Editing Real Images using Guided Diffusion Models
   [https://arxiv.org/abs/2211.09794](https://arxiv.org/abs/2211.09794)
5. Null-text Inversion 官方项目页
   [https://null-text-inversion.github.io/](https://null-text-inversion.github.io/)
6. DiffEdit: Diffusion-based semantic image editing with mask guidance
   [https://arxiv.org/abs/2210.11427](https://arxiv.org/abs/2210.11427)
7. Plug-and-Play Diffusion Features for Text-Driven Image-to-Image Translation
   [https://arxiv.org/abs/2211.12572](https://arxiv.org/abs/2211.12572)
8. Imagic: Text-Based Real Image Editing With Diffusion Models
   [https://openaccess.thecvf.com/content/CVPR2023/html/Kawar_Imagic_Text-Based_Real_Image_Editing_With_Diffusion_Models_CVPR_2023_paper.html](https://openaccess.thecvf.com/content/CVPR2023/html/Kawar_Imagic_Text-Based_Real_Image_Editing_With_Diffusion_Models_CVPR_2023_paper.html)
9. Imagic 官方项目页
   [https://imagic-editing.github.io/](https://imagic-editing.github.io/)
