# 像素序列帧生成 Harness（V0.1）

这是方案文档对应的首个可运行版本。它把“角色参考包 + 动作规格 → 生成/导入候选 → 自动检查 → 人工或 Codex 审核 → 确定性导出”固定成一套本机流程。

核心服务同时供四种入口使用，因此不会出现网页、API 和 Codex 行为不一致：

- PixelLab Animate with Text V3；
- Codex 可直接调用的单行 JSON CLI；
- 供外部脚本调用的本机 REST API；
- 六页式项目化 Gradio 操作界面；按“指引与示例 → 生成动画 → 播放检查 → 逐帧修补 → 导出”排列，API/项目设置独立放在最后。

正式游戏资产不会被覆盖，用户数据也不再放进代码仓库。默认情况下，任务、中间文件、原始候选和自建角色包进入 `%LOCALAPPDATA%\SpritePipeline`，批准后的成品进入 `文档\SpritePipeline\Exports`。只有显式传入 `--root` 时才启用便携/测试目录。

## 已完成

- PixelLab 请求仍遵守 64×64、128×128 透明 PNG 帧格和 4–16 个偶数帧；若成功响应实际多回或少回帧，Harness 会保留全部有效图片、给出提醒，并按项目列数自动补透明尾格，不再丢弃已经付费的结果。
- PixelLab V3 提交、Job ID 持久化、限时轮询、429/529 退避、脱敏请求/响应和用量记录。
- 候选串行生成；POST 结果不明时不自动重试，防止重复扣费。
- 生成前查询剩余额度；网页、REST 和 CLI 的收费提交由跨进程锁串行化。任务使用幂等请求号，重复点击或网络重试只返回原任务。
- 后台任务恢复、追加式任务日志、原子结果目录和结果提交校验；页面刷新、关闭标签页或服务重启后都能继续查询已有任务，不会重复 POST。
- PNG 目录、GIF、规则 Sprite Sheet，以及由项目清单定义播放格位的稀疏 Sprite Sheet 导入。
- 尺寸、损坏、空白、无 Alpha、连续重复、相邻帧突变式位置跳跃等硬失败门禁；帧数与预设不同改为人工确认提醒。
- 安全边距、面积、质心、色板、循环首尾和脚底基线等角色级可配置警告。
- Sheet、原尺寸/放大 GIF、逐帧网格、相邻帧叠影和项目参考线预览。
- 逐帧标记、警告显式确认、内置无损像素编辑器，以及最多两轮外部/未来 AI 坏帧替换。手工像素版本不消耗 API 且没有两次上限。
- 导出 PNG、预览 GIF、生成配方 JSON 和 QA JSON，并记录 SHA-256。
- 不需要密钥的 `fixture` 离线全链路诊断；其结果始终标记为 `diagnostic_only`，不能视为生产动画。
- 面向非技术使用者的项目化网页工作台：正式页面过滤测试机器人；导入前显示网格预检；播放检查与版本化修补分离；项目列数和单帧尺寸不再暴露为日常输入项。
- 内置“织梦者 / 赛博战士”项目配置和角色外观参考：128×128/格、每行 4 格、RGBA、锚点 (64,106)；所有新动作统一为 16 帧、4×4、512×512 Sheet。
- 随仓库提供 11 个动作模板；项目界面直接提供待机、行走、跳跃、地面攻击、空中攻击、受击、向后闪避和失败 8 类动作，另保留 3 个通用模板供 API/CLI 使用。

## 用户数据、额度与结果安全

- “创建任务”先于任何收费请求落盘。网页每次生成都有不可见的幂等请求号；REST 可用 `Idempotency-Key`，CLI 可用 `--request-key`。相同请求号只对应一个任务。
- 每次收费 POST 前都会实时读取 PixelLab 余额，并在本机跨进程锁内完成“检查额度 → 保存提交意图 → 保存远端 Job ID”。额度按官方动态公式 `ceil(宽×高×模型帧数/65536)` 预估；128×128 的 4/8/16 帧分别约为 1/2/4 个 generation 单位。余额查询、状态查询和结果取回不会消耗额度。
- 状态明确区分“任务已保存、正在提交、模型处理中、正在保存、结果已保存、提交结果未知、失败”。“提交结果未知”绝不会自动重提，可在找到远端 Job ID 后手工绑定并只做查询。
- 结果先写入隐藏暂存目录，逐帧校验后原子发布；每个任务修订版都有追加式日志。即使 `job.json` 仍是旧版，系统也会选取更新的有效日志；即使进程在目录改名前退出，重启也会发布已完整写入的结果。
- 设置页可查看实际数据、导出、缓存和恢复目录。首次升级会复制并校验旧 `work/`、`exports/` 和用户角色包，不删除旧资产；旧 `.env` 中的 PixelLab Key 只有在 Windows DPAPI 加密副本可解密且一致后才会清除。

## 安装与启动

需要 Python 3.11 或更高版本：

```powershell
cd Tools\SpritePipeline
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

如果这台 Codex Windows 主机没有全局 `python`，用内置运行时建立虚拟环境：

```powershell
$codexPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $codexPython -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

请直接在网页的“API 与项目”页填写 PixelLab API Key；保存后立即生效，不需要重启。Windows 使用当前用户的 DPAPI 加密保存，密钥不会进入任务 JSON、导出文件、日志或 Git，网页也不会回显完整 Key。自动化部署仍可用进程环境变量 `PIXELLAB_API_KEY`，但不再建议把真实 Key 写进项目 `.env`。

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

网页上传建立的角色包会放在用户数据目录的 `characters/`，不会改动仓库。仓库内 `presets/` 只保留随软件发布的只读模板。需要开发新的内置 QA 配置时，才使用 `presets/characters/_template/character.example.json`；普通用户不需要手工编辑它。

角色描述只写身份、服装、比例、武器和批准色板；动作的起手、发力、命中、停顿、恢复放在 `presets/actions/*.json` 中。QA 阈值应写进角色预设。

## 由 Codex 驱动

CLI 无交互，每次只输出一个 UTF-8 JSON 对象：

```powershell
$created = .\harness.ps1 create --character your_character --action forward_thrust --provider pixellab --candidates 1 --request-key <本次操作的稳定唯一值> | ConvertFrom-Json
$jobId = $created.data.job.job_id
.\harness.ps1 generate --job $jobId
.\harness.ps1 status --job $jobId
.\harness.ps1 safety --job $jobId --candidate 1
.\harness.ps1 approve --job $jobId --candidate 1 --reviewer codex --acknowledge-warnings
.\harness.ps1 export --job $jobId --candidate 1
```

把 `your_character` 替换为已经通过 `list-presets` 校验的真实角色 ID。

每个候选都会单独提交一次付费生成，所以网页和示例默认只创建 1 个；一次提交消耗的 generation 单位随尺寸和模型帧数变化，并不恒等于 1。可先用 `estimate --character <id> --action <id> --candidates <n>` 离线估算。`generate` 默认等待并按候选串行执行；加 `--no-wait` 时只推进一次提交/轮询。`recover-all` 会扫描全部持久任务并只执行安全恢复。遇到 `submission_unknown` 时绝不能重提；若能从 PixelLab 找到原 Job ID，使用 `attach-provider-job` 绑定。遇到 `provider_pending` 或 `saving` 时可再次调用 `generate` 或 `recover-all`，它们只会继续已有任务。旧版帧数合同失败可用 `recover --job <id> --candidate <n>` 取回，所有恢复路径都不会创建新的收费生成。

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
4. “逐帧修补”只处理检查页标记的问题帧，内置铅笔、橡皮擦、吸管、像素网格、整数缩放、平移、撤销和重做；
5. “导出”只显示已通过的动画，并输出固定网格 PNG；
6. “API 与项目”作为独立设置页，管理 Key 和项目合同。

“生成动画”页包含任务安全中心。点击后会立即显示已经保存的任务以及四阶段进度；刷新页面后可从任务列表重新打开，后台恢复不依赖当前标签页。生成完成后任务会进入“播放检查”，无需填写任务 ID、候选编号或本机路径。生成提示要求角色根部的运动轨迹在相邻帧之间连续，但不要求人物始终固定在画布中央。若只是检查一张已有成品 Sheet，可在“播放检查”页展开对应入口；这条路径不依赖 API。模型实际返回帧数与预设不同时，所有有效帧仍会进入检查页，末行不足的格子保持透明；差异作为提醒交由人工确认。尺寸、透明度、空白、重复和相邻帧突变式跳位等真正不可用的问题仍会阻止采用和导出。角色身份、服装、武器、肢体和动作意图仍需人工确认。

所有帧的外框始终保持项目规定的固定尺寸。工具不会为了“居中”而逐帧裁剪、扩框、缩放或平移人物，因为武器伸展和姿势变化会自然改变可见外接矩形，机械居中反而会破坏身体轨迹。检查页提供项目参考线和相邻帧叠影：紫红色表示前一帧，青色表示当前帧。连续的小幅位移是正常运动，前后画面突然大幅分离才属于连续性问题。

需要修补时，先在“播放检查”把问题帧送去修补，再在内置画布逐像素修改。画布直接编辑 PNG 的原始 RGBA 矩阵；放大显示、网格和光标位于独立层，不会混入成品。铅笔不做抗锯齿，橡皮擦写入 `(0,0,0,0)`，吸管读取精确 RGBA；每次正式保存都会完成 PNG 往返校验、建立手工版本并重新运行序列检查。浏览器还会保存与基础版本绑定的未提交草稿。Aseprite、Krita 等外部工具上传入口仍作为备用方式保留。

### 织梦者 / 赛博战士项目合同

当前网页项目模式固定使用：

- 单帧 128×128、每行 4 格、RGBA 透明背景；普通动作按行读取，攻击动作按项目清单中的指定格位读取；
- 项目根部参考点为 x=64、y=106，用于初始放置和检查参照，不是强制中心锁；每帧保持相同的 128×128 外框，允许角色按动作连续移动，但不裁边、不逐帧自动居中；
- 待机：512×512、16 帧 @ 8 FPS（循环），`赛博人物待机.png`；
- 行走：512×512、16 帧 @ 5 FPS（循环），`赛博人物行走.png`；
- 跳跃：512×512、16 帧 @ 6 FPS（循环，下降关键姿势使用索引 12），`赛博人物跳跃.png`；
- 地面攻击：512×512、16 帧 @ 18 FPS（单次，索引 6 可定格），`赛博人物攻击.png`；
- 空中攻击：512×512、16 帧，运行时 18 FPS（资源场景记录 5 FPS），`赛博人物空中攻击.png`；
- 受击：512×512、16 帧 @ 12 FPS（按当前资源循环），`赛博人物受击.png`；
- 向后闪避：512×512、16 帧 @ 12 FPS（单次），`赛博人物向后闪避.png`；这是新增资产合同，当前 Godot 状态机尚需接线；
- 失败：512×512、16 帧 @ 12 FPS（单次并停末帧），`赛博人物失败.png`。

新建动作统一导出 4×4、16 帧、512×512 Sheet，并保持每一帧完整的 128×128 画布和已经确认的坐标，不裁边、不缩放，也不会逐帧自动居中。配方 JSON 同时记录 `frame_cells`、`unused_cells`、`source_region_px`、运行时/场景 FPS 和关键帧索引。旧版低帧数或稀疏 Sheet 仍可导入检查，模型意外返回非 16 帧时也仍会保留全部有效结果，但它们不再是新建任务的默认合同。

REST API：

```powershell
.\harness.cmd serve-api
```

接口说明在 `http://127.0.0.1:8765/docs`。服务默认只监听本机；当前没有账号或权限系统，不应直接暴露到公网。

创建任务时建议总是发送 `Idempotency-Key` 请求头；客户端超时后用同一个值重试会得到原任务。可用 `GET /v1/account/balance` 查询额度、`GET /v1/account/estimate` 估算本次单位数、`GET /v1/jobs/{id}/candidates/{n}/safety` 查看提交与结果完整性、`POST /v1/recovery/run` 扫描全部任务。已有 PixelLab 结果可用 `POST /v1/jobs/{id}/candidates/{n}/recover` 重新读取；提交结果未知时可用 `attach-provider-job` 绑定已知 Job ID。这些恢复端点都不会创建新的生成请求。

内置画布与 Codex 使用同一组无损像素接口：

- `GET /v1/jobs/{id}/candidates/{n}/frames/{frame}/pixel-edit` 读取精确 RGBA、尺寸和基础版本校验值；
- `POST /v1/jobs/{id}/candidates/{n}/frames/{frame}/pixel-edit` 提交 RGBA 手工版本并重新检查。

Codex 也可用 `pixel-edit-frame --source <同尺寸透明 PNG> --base-sha256 <读取到的校验值>` 走同一版本通道。手工版本和 `replace-frame` 的外部/未来 AI 两次限制分开计算。

## 验证与尚未包含的范围

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

V0.1 暂未自动调用 PixelLab Edit Animation V2 或 GPT-Image-2；当前已经支持内置手工像素修补、REST RGBA 修补和 Codex `pixel-edit-frame`，外部修补 PNG 仍可通过 `replace-frame` 加入。框选、填充、洋葱皮编辑视图和 AI 遮罩修补属于后续阶段。空白仓库也没有可修改的 Godot 工程，因此独立 Godot 预览场景仍需在真实项目接入时补做。
