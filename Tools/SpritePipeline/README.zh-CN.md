# 像素序列帧生成 Harness（V0.1）

这是方案文档对应的首个可运行版本。它把“角色参考包 + 动作规格 → 生成/导入候选 → 自动检查 → 人工或 Codex 审核 → 确定性导出”固定成一套本机流程。

核心服务同时供四种入口使用，因此不会出现网页、API 和 Codex 行为不一致：

- PixelLab Animate with Text V3；
- Codex 可直接调用的单行 JSON CLI；
- 供外部脚本调用的本机 REST API；
- 六页式项目化 Gradio 操作界面；按“指引与示例 → 生成动画 → 播放检查 → 逐帧修补 → 导出”排列，API/项目设置独立放在最后。

正式游戏资产不会被覆盖。任务、中间文件和不可变原始候选进入 `work/`，批准后的成品只进入 `exports/` 暂存区。

## 已完成

- PixelLab 生成严格支持 64×64、128×128 透明 PNG 帧格和 4–16 个偶数帧；Sheet 导入会按透明内容自动识别实际帧数，仅忽略末尾空格。
- PixelLab V3 提交、Job ID 持久化、限时轮询、429/529 退避、脱敏请求/响应和用量记录。
- 候选串行生成；POST 结果不明时不自动重试，防止重复扣费。
- PNG 目录、GIF、规则 Sprite Sheet 导入。
- 数量、尺寸、损坏、空白、无 Alpha、连续重复、整个人物在画布内平移等硬失败门禁。
- 安全边距、面积、质心、色板、循环首尾和脚底基线等角色级可配置警告。
- Sheet、原尺寸/放大 GIF、逐帧网格、首帧叠加和固定锚点十字线预览。
- 逐帧标记、警告显式确认、最多两轮版本化坏帧替换。
- 导出 PNG、预览 GIF、生成配方 JSON 和 QA JSON，并记录 SHA-256。
- 不需要密钥的 `fixture` 离线全链路诊断；其结果始终标记为 `diagnostic_only`，不能视为生产动画。
- 面向非技术使用者的项目化网页工作台：正式页面过滤测试机器人；导入前显示网格预检；播放检查与版本化修补分离；项目列数和单帧尺寸不再暴露为日常输入项。
- 内置“织梦者 / 赛博战士”项目配置和角色外观参考：128×128/格、4 列、RGBA、按行读取、锚点 (64,106)。
- 随仓库提供待机、行走、奔跑、跳跃、突刺、近战攻击、受击和倒地死亡 8 个动作模板。

## 安装与启动

需要 Python 3.11 或更高版本：

```powershell
cd Tools\SpritePipeline
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

如果这台 Codex Windows 主机没有全局 `python`，用内置运行时建立虚拟环境：

```powershell
$codexPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $codexPython -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

可以直接在网页的“API 与项目”页填写 PixelLab API Key；保存后立即生效，不需要重启。也可以继续在本机 `.env` 中填写 `PIXELLAB_API_KEY`。密钥不会写入任务 JSON、导出文件或日志，网页不会回显完整 Key。

当前 Windows Codex 主机若没有全局 `python`，可直接使用自动寻找 `.venv`、PATH 或 Codex 内置 Python 的启动器：

```powershell
.\harness.ps1 list-presets
```

如果 PowerShell 提示“禁止运行脚本”，无需修改系统执行策略，改用不受该策略影响的 CMD 启动器：

```powershell
.\harness.cmd list-presets
.\harness.cmd serve-ui
```

下文出现的所有 `harness.ps1` 命令都可以逐字等价替换为 `harness.cmd`。

也可以完全绕过启动器：

```powershell
.\.venv\Scripts\python.exe cli.py serve-ui
```

内置 Python 足以运行本仓库的核心离线诊断；PixelLab、REST API 和网页界面需要先在 `.venv` 中安装 `requirements.txt`。

## 开箱即跑的离线验收

仓库附带 `diagnostic_dummy` 和不会联网的 `fixture`。它只验证流程，输出会明确标成 `diagnostic_only`：

```powershell
$created = .\harness.ps1 create --request examples\create_job.json | ConvertFrom-Json
$jobId = $created.data.job.job_id
.\harness.ps1 generate --job $jobId
.\harness.ps1 approve --job $jobId --candidate 1 --reviewer codex --acknowledge-warnings
.\harness.ps1 export --job $jobId --candidate 1
```

最后一条结果中的 `data.job.export.sha256` 是导出 Sheet 的校验和。诊断角色不是游戏美术，不应进入正式资产目录。

## 建立角色参考包

最简单的方式是在网页“生成动画”页直接上传角色原型图，同时填写角色外观提示词和本次动作提示词。可以上传一张 128×128 透明 PNG，也可以上传当前项目 128×128/格、4 列的 Sprite Sheet；对于 Sheet，系统会自动取第一个非空格作为生成第一帧并建立可复用角色包。CLI/REST 核心仍支持通用 64×64 或 128×128 角色预设。

需要配置专用 QA 阈值或主设定图、色板、轮廓图时，再把 `presets/characters/_template/character.example.json` 复制到 `presets/characters/<character_id>/character.json`，并加入至少一张尺寸完全匹配、含 Alpha 且非空白的 `idle_reference.png`。可选加入 `master.png`、`palette.png` 和 `silhouette.png`；使用可选文件时，再把 JSON 中对应的 `null` 改成文件名。

角色描述只写身份、服装、比例、武器和批准色板；动作的起手、发力、命中、停顿、恢复放在 `presets/actions/*.json` 中。QA 阈值应写进角色预设。

## 由 Codex 驱动

CLI 无交互，每次只输出一个 UTF-8 JSON 对象：

```powershell
$created = .\harness.ps1 create --character your_character --action forward_thrust --provider pixellab --candidates 3 | ConvertFrom-Json
$jobId = $created.data.job.job_id
.\harness.ps1 generate --job $jobId
.\harness.ps1 status --job $jobId
.\harness.ps1 approve --job $jobId --candidate 1 --reviewer codex --acknowledge-warnings
.\harness.ps1 export --job $jobId --candidate 1
```

把 `your_character` 替换为已经通过 `list-presets` 校验的真实角色 ID。

`generate` 默认等待并按候选串行执行；加 `--no-wait` 时只推进一次提交/轮询。遇到 `submitting` 且没有 Provider Job ID 时，Codex 不应重提；遇到 `provider_pending` 时可再次调用 `generate` 恢复轮询。

完整的 Codex 状态与修补规则见 [CODEX_USAGE.md](CODEX_USAGE.md)。

## 其他入口

网页：

```powershell
.\harness.cmd serve-ui
```

打开 `http://127.0.0.1:7860`。

网页分成六个含义明确的页面：

1. “指引与示例”先解释角色原型图、提示词、动画帧和 Sprite Sheet；
2. “生成动画”集成上传角色原型图、角色外观提示词、动作提示词和候选生成；
3. “播放检查”检查 AI 结果；已经存在的成品 Sheet 也只在这里作为待检查素材上传；
4. “逐帧修补”只处理检查页标记的问题帧；
5. “导出”只显示已通过的动画，并输出固定网格 PNG；
6. “API 与项目”作为独立设置页，管理 Key 和项目合同。

生成后，任务会自动带入“播放检查”，无需填写任务 ID、候选编号或本机路径。生成提示会锁定角色根部锚点，要求模型不能在不同帧中平移整个人物。若只是检查一张已有成品 Sheet，可在“播放检查”页展开对应入口；这条路径不依赖 API。自动检查负责发现尺寸、帧数、透明度、空白、重复、整帧位置偏移、边距、重心、循环和脚底基线等问题；检测到可确认的整个人物画布平移会阻止采用和导出。角色身份、服装、武器、肢体和动作意图仍需人工确认。当前版本不会擅自按外接矩形重新居中，因为武器和姿势变化会使外接矩形变化，机械居中反而会移动身体；可通过固定锚点十字线人工复核，并在“逐帧修补”上传一张外部修好的同尺寸透明 PNG。原图会保留，修补图作为新版本重新检查。

### 织梦者 / 赛博战士项目合同

当前网页项目模式固定使用：

- 单帧 128×128、4 列、RGBA 透明背景、从左到右再换行；
- 水平根部锚点固定在 x=64，项目脚底基线为 y=106；每帧都在相同的 128×128 格内保持同一画布坐标，不裁边、不逐帧自动居中；
- 待机 16 帧 @ 8 FPS（循环），推荐文件名 `赛博人物待机.png`；
- 行走 16 帧 @ 5 FPS（循环），推荐文件名 `赛博人物行走.png`；
- 跳跃 12 帧 @ 6 FPS（按当前 Godot 资源循环），推荐文件名 `赛博人物跳跃.png`；
- 受击 12 帧 @ 12 FPS（按当前 Godot 资源循环），推荐文件名 `赛博人物受击.png`；
- 失败 16 帧 @ 12 FPS（单次并停末帧），推荐文件名 `赛博人物失败.png`。

导出保持每一帧完整的 128×128 画布和已经确认的坐标，不裁边、不缩放，也不会逐帧自动居中。地面攻击和空中攻击在当前 Godot 场景里采用稀疏格坐标选取 5 帧，首版不会假装可以用连续 5 格直接覆盖；设置页会明确标注这一限制。

REST API：

```powershell
.\harness.cmd serve-api
```

接口说明在 `http://127.0.0.1:8765/docs`。服务默认只监听本机；当前没有账号或权限系统，不应直接暴露到公网。

## 验证与尚未包含的范围

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

V0.1 暂未自动调用 PixelLab Edit Animation V2 或 GPT-Image-2；现阶段可通过 `review-frame` 标记后，用 `replace-frame` 加入外部修补 PNG。空白仓库也没有可修改的 Godot 工程，因此独立 Godot 预览场景仍需在真实项目接入时补做。正式采用 PixelLab 前，仍应按原方案用玩家、128px 怪物和 64px 怪物完成模型可行性门槛测试。
