# 序列帧生成管线方案

## 1. 目标与边界

这条管线只解决人物和怪物序列帧：

- 放弃 Rika；
- FrameRonin 和地图流程保持不动；
- 最终资产仍是当前的透明 PNG Sprite Sheet；
- 保持现有 `64×64`、`128×128` 帧格；
- 不改 `AnimatedSprite2D/SpriteFrames` 使用方式；
- 不引入骨骼、3D、本地模型或训练；
- 操作复杂度控制在一个内部网页工具。

推荐主流程：

```text
角色参考包
    +
动作规格
    ↓
PixelLab V3 生成完整序列
    ↓
自动规格检查
    ↓
网页预览和标记坏帧
    ↓
PixelLab / GPT-Image-2 局部修补
    ↓
确定性切帧、对齐、打包
    ↓
现有 Godot Sprite Sheet
```

## 2. 模型选择

### 主生成模型：PixelLab Animate with Text V3

把它作为第一版唯一主生成后端。

适配原因：

- 输入一个角色参考帧和自然语言动作；
- 支持 4–16 个偶数帧；
- 支持 `64×64`、`128×128` 等当前规格；
- 第一帧保持为原始参考图；
- 可要求透明背景；
- 支持 Seed；
- API 异步任务适合网页 Harness；
- 自定义动作不依赖预设名称。

这些能力与项目格式直接匹配。[PixelLab Animate with Text](https://www.pixellab.ai/docs/tools/animate-with-text-new)、[PixelLab API](https://api.pixellab.ai/v2/docs)

建议调用：

```text
POST /v2/animate-with-text-v3
GET  /v2/background-jobs/{job_id}
```

第一版不接 PixelLab Skeleton。虽然它控制力更强，但会把动作编辑成本重新压到团队身上。

### 序列统一修补：PixelLab Edit Animation V2

调用：

```text
POST /v2/edit-animation-v2
```

适合处理：

- 所有帧的武器颜色不一致；
- 某些帧缺少围巾、护甲或帽子；
- 统一添加武器、光效或服装元素；
- 清除整套序列中的错误背景。

它会一次编辑多个帧，官方设计目标就是维持帧间一致性。对于 `128×128` 资产，每次最多处理四帧，因此 Harness 应以带重叠的窗口处理：

```text
帧 1–4
帧 4–7
帧 7–8
```

重叠帧只作为上下文，最终保留已经批准的原始版本。[PixelLab Edit Animation](https://www.pixellab.ai/docs/tools/edit-animation-pro)

### 困难坏帧备用：GPT-Image-2

只用于 PixelLab 无法修复的单帧问题：

- 多余手脚；
- 武器严重变形；
- 面部或服装局部错误；
- 需要同时参考角色原画及相邻帧。

当前 OpenAI 官方推荐的图像生成和编辑模型是 `gpt-image-2`，支持多张参考图、图片编辑、蒙版和高保真输入；可以锁定快照 `gpt-image-2-2026-04-21`，减少模型版本变化。[GPT-Image-2](https://developers.openai.com/api/docs/models/gpt-image-2)、[图像编辑文档](https://developers.openai.com/api/docs/guides/image-generation)

需要注意：官方明确说明蒙版是引导，不保证严格按边界执行。因此修复时只从返回图中裁出目标坏帧，不允许用返回结果覆盖整张已批准序列。

如果团队暂时没有可用的 OpenAI API 账号，第一版可以只接 PixelLab；备用接口保留但不实现。

## 3. 工具技术栈

推荐使用：

| 组件 | 选择 |
|---|---|
| 语言 | Python 3.11 |
| 网页 UI | Gradio |
| API 请求 | `httpx` |
| 图片处理 | Pillow |
| 参数校验 | Pydantic |
| 状态记录 | JSON 文件 |
| 密钥 | 环境变量或本机 `.env` |
| 数据库 | 不使用 |
| 部署 | 本机启动，浏览器访问 |

原因很简单：PixelLab 有 Python 客户端，Pillow 适合切帧、Alpha 和 Sprite Sheet 操作，Gradio 足以实现内部页面。

建议位置：

```text
Tools/SpritePipeline/
├─ app.py
├─ providers/
│  ├─ base.py
│  ├─ pixellab.py
│  └─ openai_image.py
├─ processing/
│  ├─ frame_checks.py
│  ├─ frame_alignment.py
│  ├─ sheet_export.py
│  └─ preview.py
├─ presets/
│  ├─ characters/
│  └─ actions/
├─ work/                  # Git忽略
├─ exports/               # 导出暂存区
├─ .env.example
└─ requirements.txt
```

API 密钥、原始候选和中间文件不进入 Git。

## 4. 角色参考包

每个角色只需要建立一次参考包：

```text
presets/characters/cyber_player/
├─ character.json
├─ master.png
├─ palette.png
├─ idle_reference.png
└─ silhouette.png
```

其中：

- `master.png`：质量最高、身份最准确的角色图；
- `idle_reference.png`：面向右、透明背景、可以直接作为动画第一帧；
- `palette.png`：项目批准颜色；
- `silhouette.png`：可选，用于检查比例和画布占用；
- `character.json`：固定规格。

示例：

```json
{
  "schema_version": 1,
  "character_id": "cyber_player",
  "display_name": "Cyber",
  "cell_width": 128,
  "cell_height": 128,
  "facing": "right",
  "reference_frame": "idle_reference.png",
  "palette": "palette.png",
  "anchor": {
    "x": 64,
    "ground_y": 112
  },
  "safe_margin": 4,
  "sheet_columns": 8,
  "transparent_background": true
}
```

角色描述必须只写身份，不混入动作：

```text
Side-view cyber swordsman. Dark fitted armor, cyan energy accents,
short dark hair, one straight energy sword. Preserve the exact outfit,
head-to-body ratio, weapon length and palette from the reference image.
```

以后所有动作都复用同一个描述。

## 5. 动作规格

每个动作保存为一个短 JSON：

```json
{
  "action_id": "forward_thrust",
  "frame_count": 8,
  "fps": 12,
  "loop": false,
  "grounded": true,
  "action_description": "Frames 1-2 anticipation, frame 3 starts a short forward lunge, frame 4 is the sword contact pose, frame 5 holds the impact briefly, frames 6-8 recover to the exact starting stance.",
  "locked_constraints": [
    "fixed side-view camera",
    "facing right",
    "no camera movement",
    "do not change outfit",
    "do not change weapon length",
    "no additional limbs",
    "transparent background"
  ]
}
```

动作描述不要只写：

```text
attack
```

应明确动作阶段：

```text
起手 → 发力 → 命中关键姿势 → 停顿 → 恢复
```

但是不必精确描述每一根骨骼。

### 循环动作

Idle、Walk 等循环动作增加：

```json
{
  "loop": true,
  "loop_constraint": "The last frame must transition smoothly back to the unchanged first frame."
}
```

由于 PixelLab 会保留第一帧，第一帧应直接使用项目批准的待机姿势。

## 6. 完整生产步骤

### 步骤 1：创建任务

操作者在网页选择：

- 角色；
- 动作预设；
- 帧数；
- 候选数量，默认 3；
- Seed，默认随机；
- 是否循环。

Harness 生成任务目录：

```text
work/20260831_cyber_forward_thrust_001/
├─ job.json
├─ input/
├─ raw/
├─ repaired/
├─ previews/
└─ export/
```

`job.json` 保存：

- 完整提示词；
- 参考图校验值；
- API 和模型版本；
- Seed；
- Provider Job ID；
- API 返回状态和用量；
- 每帧审核状态；
- 最终导出校验值。

### 步骤 2：提交生成

Harness 调用 PixelLab V3，获得 `background_job_id`。

轮询策略：

- 每 5 秒查询一次；
- 最长等待 5 分钟；
- HTTP 429/529 使用 5、10、20 秒退避；
- 最多重试三次；
- 参数错误、余额不足不自动重试；
- 所有原始请求和响应落盘。

每个任务默认生成三个候选，但一次只运行一个，避免并发限制和无意义消耗。

### 步骤 3：保存原始帧

原始返回图永远保留，不在原文件上修改：

```text
raw/candidate_01/frame_00.png
raw/candidate_01/frame_01.png
...
```

后处理只读取它们并生成新文件。

### 步骤 4：自动检查

#### 硬失败

出现以下情况直接判定候选不可导出：

- 返回帧数错误；
- 单帧不是 `64×64` 或 `128×128`；
- 文件损坏；
- 完全空白帧；
- 没有 Alpha 通道；
- 非透明内容全部在画布之外；
- 相邻多个帧完全相同。

#### 警告

允许操作者继续审核：

- 非透明内容接触画布边缘；
- 角色面积比参考帧变化超过阈值；
- 相邻帧质心突然移动；
- 非透明颜色大量偏离参考色板；
- 循环动画最后一帧与第一帧差异过大；
- 脚底基线异常；
- 武器或身体轮廓面积突然增加。

阈值保存在角色预设中，不硬编码。

### 步骤 5：生成审核预览

页面同时展示：

- Sprite Sheet；
- 放大 4–8 倍的逐帧网格；
- 原尺寸 GIF；
- 放大后的 GIF；
- 第一帧与其他帧叠加对比；
- 每帧的警告标记。

操作者对每帧标记：

```text
通过 / 需要修补 / 整套拒绝
```

坏帧问题选择固定分类：

- 身份漂移；
- 服装错误；
- 武器错误；
- 多余或缺失肢体；
- 姿势不符合；
- Alpha/背景错误；
- 比例或基线错误；
- 其他。

### 步骤 6：局部修补

#### 一致性问题

把问题帧和相邻批准帧提交给 PixelLab Edit Animation V2。

例如第 5 帧武器错误：

```text
输入：帧3、帧4、帧5、帧6
指令：Keep every pose unchanged. Repair the sword in frame 5 so its
length, cyan color and straight blade match the approved neighboring frames.
```

最终只替换第 5 帧，其他返回帧丢弃。

#### 单帧严重损坏

提交给 GPT-Image-2：

- `master.png`；
- 前一帧；
- 坏帧；
- 后一帧；
- 坏帧区域蒙版。

返回后只裁出修补目标，缩放到固定格子，再重新运行自动检查。

每一帧最多允许两轮修补。仍不合格就返回候选选择，不继续无限消耗。

### 步骤 7：确定性后处理

按固定顺序执行：

1. 转为 RGBA；
2. 清理完全透明像素中的脏 RGB；
3. 保持原始画布，不自动裁边；
4. 检查安全边距；
5. 对 `grounded=true` 的动作检查脚底基线；
6. 不自动重绘角色；
7. 按配置排列 Sprite Sheet；
8. 生成 GIF 和审核报告；
9. 导出 PNG。

第一版只对色板进行检查，不强行把所有颜色映射到固定色板，避免把勉强正确的角色处理坏。

### 步骤 8：导出 Godot 资产

导出内容：

```text
exports/cyber_player/forward_thrust/
├─ cyber_forward_thrust.png
├─ cyber_forward_thrust.preview.gif
├─ cyber_forward_thrust.recipe.json
└─ cyber_forward_thrust.qa.json
```

PNG 的：

- 单帧大小；
- 列数；
- 总尺寸；
- Alpha；
- 帧顺序；
- 文件命名

必须与当前角色资产约定一致。

Harness 第一版不直接覆盖正式资产，只导出到暂存区。确认后再由团队放进对应资产目录并配置现有 `SpriteFrames`。

## 7. 网页界面

只做三个页面。

### 生成

- 选择角色；
- 选择或新建动作；
- 编辑动作描述；
- 帧数；
- 候选数；
- 生成按钮；
- 显示任务时间和 API 消耗。

### 审核与修补

- GIF 预览；
- 逐帧网格；
- 点击坏帧；
- 选择错误类型；
- 输入补充说明；
- 修补；
- 批准动作。

### 导出

- 显示硬检查结果；
- 设置 Sprite Sheet 列数；
- 生成 PNG；
- 打开导出目录。

不做账号、权限、云部署和资产数据库。

## 8. 实施顺序

### 阶段 0：先验证模型，暂不开发 UI

选取：

- Cyber 玩家；
- 一个 128px 怪物；
- 一个 64px 怪物。

动作选择：

- Idle；
- 自定义攻击；
- Hurt；
- Death。

每个动作用 PixelLab V3 生成三次。

继续开发的门槛：

- 三次内至少有一个候选可修补；
- 8 帧动作中坏帧不超过两帧；
- 没有系统性改变角色身体比例；
- 自定义攻击能识别出要求的命中姿势；
- 单动作生成及筛选操作时间不超过 15 分钟。

如果 PixelLab 在玩家、普通怪、异形怪三类中有两类无法达标，就停止接入，改为测试第二个 API，而不是先把 Harness 做完。

### 阶段 1：后处理和审核工具

先用现有 Rika 资产验证：

- 切帧；
- GIF；
- 空白帧检查；
- 重复帧检查；
- Alpha；
- 尺寸；
- Sprite Sheet 导出。

这部分不依赖任何 API，最容易确认价值。

### 阶段 2：PixelLab 接入

实现：

- API 调用；
- 后台任务轮询；
- 失败重试；
- 原始结果落盘；
- 用量记录；
- 三候选审核。

完成后就已经可以替代 Rika 的主体功能。

### 阶段 3：坏帧修补

先接 PixelLab Edit Animation V2。

只有实际测试表明它无法处理的坏帧比例较高时，再增加 GPT-Image-2。避免第一版同时维护两个服务。

### 阶段 4：Godot 隔离验收

建立一个独立预览场景：

- 加载导出的 Sprite Sheet；
- 测试 64/128px 帧格；
- 测试循环、非循环、翻转和切换动作；
- 不修改正式玩家、敌人或关卡。

通过后再允许导出资产进入正式目录。

## 9. 工作量控制

如果由一名熟悉 Python 和 API 的程序员执行，建议按以下范围控制：

| 工作 | 估算 |
|---|---:|
| PixelLab 可行性测试 | 0.5–1 天 |
| 切帧、检查、GIF、导出 | 1 天 |
| Gradio 页面和任务记录 | 1 天 |
| PixelLab API、轮询和错误处理 | 1 天 |
| 修补流程和 Godot 隔离验证 | 1–2 天 |

也就是约 **4–6 个开发日**。如果时间紧，第一版砍掉 GPT-Image-2、色板分析和复杂基线调整，可以缩小到：

> PixelLab V3生成 → 人工选候选 → 自动检查 → Sprite Sheet导出。

这已经足以验证能否真正替代 Rika。

最关键的实施原则是：**先用项目真实角色证明 PixelLab V3 达标，再开发 Harness；Harness 只负责把成功流程固定下来，不负责拯救一个本身不适配项目的模型。**
