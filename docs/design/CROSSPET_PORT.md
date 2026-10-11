# CrossPet 完整角色移植（I-47）

[问题池](DESIGN_ISSUES.md) · [I-45 双模式](AI_CHARACTER_THEMES.md) · [素材许可](../../ASSET_LICENSES.md)

## 目标

AI 桌宠模式完整接入开源项目 CrossPet 1.2.4（GitHub `lokicorvus/crosspet`，代码 MIT，立绘与角色设定 CC BY-NC-SA 4.0）的五个正式角色：Claude、Codex（上游 `gpt`）、Gemini、DeepSeek、GLM（对应智谱 ZCode），以及它们的彩蛋包。不只是 7 张姿态：全部姿态与变体、眨眼、各角色台词、跟着 AI 干活的动作、闲时小动作、睡觉、摸头／戳一下、分时段问候、节日装扮、退出挥手、额度快满时累了，以及上游的彩蛋。

小乔模式完全不变。上游代码只作参考，全部按本仓库的 Python／PIL 架构重写；上游脚本（含 hooks、integrate.py、fix_blink.py）一律不运行、不安装。

## 模块与接口（实现必须遵守）

### A. 素材与目录：`appearance.py`、`tools/import_crosspet.py`、`tools/build_character_manifests.py`、`assets/characters/`

- `tools/import_crosspet.py --source <上游克隆目录>`：只把 `characters/{claude,gpt,gemini,deepseek,glm}` 和 `egg-*` 下的 `*.webp`、`character.json`、`characters/LICENSE.md` **按字节复制**到 `assets/characters/<id>/`（`gpt`→`codex`，`egg-gpt`→`egg-codex`），校验每张图是单帧 RGBA WebP；不执行、不导入上游任何代码。重复运行结果一致。
- `tools/build_character_manifests.py`（可 `--check`）由本仓库里的文件生成 `registry.json` 与各包 `manifest.json`（schema 2）。
- **姿态名** = 文件名在第一个 `-` 前的部分；同名多张为变体，按**序号序**（ordinal）排序，因此 `idle = [idle-2, idle-3, idle]`。`idle-blink` 不是姿态，是 `idle.webp` 的眨眼帧。下划线名（`greet_morning`、`fest_spring`）整体是一个姿态名。
- manifest schema 2：

```json
{"schema_version": 2, "id": "claude", "renderer": "static", "version": 2,
 "label": "Claude", "theme": "claude", "reference_size": [W, 640],
 "source": "CrossPet 1.2.4 characters/claude", "license": "CC BY-NC-SA 4.0, see ../LICENSE.md",
 "poses": {"idle": [{"file": "idle-2.webp", "size": [w, h], "foot_anchor": [x, y], "sha256": "…"}, …], …},
 "blink": {"base": "idle.webp", "file": "idle-blink.webp", "size": [w, h], "foot_anchor": [x, y], "sha256": "…"},
 "lines": {"idle": ["在呢", …], …},
 "behavior": {"accent": "#e8a33d", "greeting": "我在这儿～", "idle_actions": ["clawd"],
              "poke_pose": null, "corrected_pose": "sorry",
              "long_think": null, "fx": {"proud": "victory"}}}
```

  - 彩蛋包另有 `"egg": {"host": "codex", "caption": "…", "aura": "#…"}`，`poses` 只有 `pop/pretend/caught/bye`，不出现在选择菜单与前台映射里。
  - `reference_size` 的宽 W 取该包**普通姿态宽度的 85 分位**（不是最大值），高取 640；更宽的姿态在绘制时单独缩到放得下，不被裁切。
  - `foot_anchor`：x = 图片上 40% 区域 alpha 质心（头部），y = 图片高度（脚底）。眨眼帧沿用 `idle.webp` 的锚点。
  - GLM 的上游眨眼帧不是只改眼睛（整张重绘），Gemini 没有眨眼帧：两者 `blink` 为 null。
  - `lines` 来自上游 `character.json` 的 `lines`，每条 ≤ 40 字、每个键 ≤ 16 条、无换行；`behavior` 由 `accent/greeting/idleActions/pokePose/correctedPose/longThink/fx` 转来。
- `appearance.py` 目录 API（在现有 `CharacterCatalog` 上扩展，同时兼容 schema 1）：
  - 姿态名不再是封闭集合：任何通过 `_ID` 的名字都可以；**删除 `running→thinking` 别名**，保留旧名兼容别名 `waiting→asking`、`error→oops`、`sleep→sleeping`、`done→happy`。
  - `POSE_FALLBACK = {compact: writing, reset: happy, feast: eat, sorry: listening, asking: listening, update: happy, bye: happy, drawing: writing, deepthink: thinking}`，一跳后回 `idle`。
  - `has_pose(c, p)`（只看自有图）、`frame_count(c, p)`（解析回退后的那组）、`resolve(c, p)`（返回实际用图的姿态名）、`lines(c, key)`（tuple）、`behavior(c)`（只读映射）、`eggs_for(host)`、`listing(asset_root)`（类方法，只读 registry，不解码不哈希，供菜单用）。
  - `frame(c, pose, box_size, index=0, blink=False)` → `CharacterFrame(image, offset, pose, ref, index, alpha_box)`（`alpha_box` 随缓存图一次算好）；`index` 对帧数取模；`blink=True` 且该帧是眨眼底图时返回眨眼帧。缓存键含 (角色, 版本, 指纹, 姿态, 帧号, 眨眼, 尺寸)。
  - 摆放：`s = min(box_w/ref_w, box_h/ref_h)`；若该图 `w*s > box_w` 则 `s = box_w/w`。锚点 x 对齐框中心、脚底对齐框底，然后把整张图**水平夹回框内**；不裁切。
  - 预算：单包原分辨率像素 ≤ 24M、全目录 ≤ 128M、单包字节 ≤ 32 MiB；解码后缩到 ≤ 400px 高的原生图 LRU ≤ 64 张；缩放缓存 ≤ 48 张且 ≤ 8M 像素。加载时校验清单、哈希与文件头，不解码像素。
  - `prewarm(c, poses)`：线程安全地解码这些姿态（工作线程调用）。解码只在独立的解码锁里排队、缩放不持锁，已缓存的 `frame()` 不再等后台解码；解码途中 `disable()` 仍原子，被弃用的包不会再写回缓存。

### B. 演出导演：`ai_pet.py`（纯逻辑，无 Tk／Win32，时间与随机数可注入）

`AiPetDirector(catalog, *, rng, memory)`；`memory` 是可序列化 dict（问候记录、额度记忆），宿主负责存盘。

- 输入：`set_character(c, now, reason)`（`reason ∈ foreground/follow/pinned/entered/restore`，只有 foreground/follow 会问候）、`on_work(level, events, now)`、`on_click(now)`、`on_poke(now)`、`farewell(now) -> 秒数`、`set_quota(low, windows, now)`、`dev_show(pose, secs, now)`。
- 输出：`tick(now, *, chat_open, model_thinking, reduced_motion) -> View`：
  `View(character, pose, art_pose, frame_index, blink, motion, motion_t, fade_from, fade_alpha, fx, fx_age, say, egg)`；`say` 只在需要冒新台词的那一帧非空。
- 规则（照搬上游 index.html，带下列改动）：DWELL 2.5s、急切请求立即生效、TRANSIENT 表（happy 5、proud 6、oops 4、surprised 3、pat 4、hum 4、stretch 3.2、yawn 3、greet_* 5.5、fest_* 6.5、自有闲时动作 4、poke 姿态 3.5）结束后回 restPose（额度低为 tired，否则 idle）；闲时循环每 20s、42% 概率，hum/stretch，静默 >3 分钟加 yawn，自有闲时动作双倍权重；**静默 10 分钟睡觉**（AI 事件和点击会刷新静默时钟）；睡着时点击 = yawn + 「唔…你回来啦」；点击 = pat；戳一下 = poke_pose 或 surprised；新一轮任务在出错 180s 内且有 corrected_pose = sorry 3s 再 thinking；thinking 超过 long_think.after 秒换 long_think.pose；多帧姿态入场随机选帧、8–10s 换另一帧；眨眼只在 idle 且显示 `idle.webp` 时，每 3–6.5s 一次 140ms；换角色取消所有旧计时器。
- 工作状态：level（由 C 给出）是持续姿态；edge 事件 `turn`→listening（2.5s 后 thinking）、`oops`→oops、`done(n_tools)`→`n_tools ≥ 8` proud 否则 happy、`interrupt`→surprised。
- 台词：TRANSIENT、问候、点击、睡觉、累了总是说；工作姿态切换的台词每 8s 最多一次（上游每次切换都说，在我们的工作台上太吵）。
- 问候：时段 night 23–2、dawn 2–5、morning 5–11、noon 11–14、afternoon 14–18、evening 18–23；节日顺序 lantern、dragonboat、midautumn（农历，表用上游 2026–2036）、10-31 halloween、12-24/25 christmas、01-01 newyear、春节初一到初七 spring、10-01–10-07 national；问候日以 05:00 为界；记录键 `slot:<日>:<时段>`、`fest:<日期>:<节日>` 存在 `memory["greeted"][角色]`；60s 检查一次，只在 idle/tired、10 分钟内活跃时；普通问候 30 分钟冷却；忙时只说话不换姿态。
- 额度：Claude/Codex 任一非过期周期 used ≥ 90 → low → tired；Codex 窗口提前恢复（同标签、比上次少 ≥15 点、距原重置时间还早 10 分钟以上）→ reset 庆祝 6.5s。
- 彩蛋：仅当前角色有 host 匹配的彩蛋包；每 60s 以 1/40 概率（仅 idle、设置允许），或 3% 的 pat；pop 2.2s → pretend（每 9s 换台词）→ 40s 内点击 caught 2s → bye 2.2s，否则 escape 台词后 bye；有非 idle 工作事件立即结束。
- 动作表 MOTION 与上游一致（bob/hop/jump/quick/rock/sway/slow/float/shake/squish/gift/jolt/dash/leave）；聊天窗打开时的 listening 用 bob（不长时间跳动）。动作族不变时（thinking→reading 同为 rock、换变体、眨眼）`motion_t` 连续，只有换族才从该姿态切换时刻归零：同上游 className 不变时 CSS 动画不重启，不再在同族姿态间跳回 0（rock 最多跳 5°）。

### C. 工作状态：`ai_work.py`（纯逻辑）

`WorkTracker()`：`update(sessions, now)` 在每次 2s 扫描后调用；`level(c, now)`、`drain(c)`、`last_activity(c)`、`recent_turn(now, window=30)`。

- 来源→角色：`agent_name()` 为 Claude→`claude`、Codex→`codex`、ZCode→`glm`；`mac-*` 只更新状态不参与跟随。
- level：waiting→`asking`；running 时取本轮最新的非状态动作：`问你问题`→asking、`委派/跟进子智能体`→delegating、`读网页/搜网页`→searching、`读…`/`搜索…`→reading、`改…/写…`→writing、`跑测试/构建/远程/命令…`/`执行工具`→running、`等结果`→本轮有委派则 delegating 否则 running、`调用工具 X`/其他原始工具名→按上游 pose_for_tool 关键词（`image_gen` 等→drawing）；该动作已有非空结果且超过 2.5s→thinking；无动作或只有「收到新任务/正在处理任务」→thinking；动作超过 90s 无新动作→thinking；done/idle/过期→None。
- edge：首次扫描只记基线；新轮次标记→`turn`；新出现 `err` 的动作→`oops`；状态变为 done 或最新动作「本轮已结束」→`done`（本轮非状态动作数）；「本轮已中断」或 running/waiting 直接回 idle→`interrupt`；mac 的 error→`oops`。证据时间窗：本机来源 20s、mac 来源 180s（用首次观察时间）。

### D. 绘制辅助：`ai_fx.py`（PIL）

- `motion(name, t) -> (dx, dy, angle, sx, sy)`，dx/dy 以精灵高度为单位，绕脚底中心。`apply(img, motion) -> (img, (ox, oy))` 保留给其他调用方（整像素平移不重采样）。
- 宿主逐帧走 `MotionCache.place(ref, img, offset, family, motion, box_w) -> (img, (x, y), alpha_box)`：平移量化到 1/8 px，整数部分向下取整作落点，小数部分与角度（0.05°）、缩放（0.001）并进一次预乘 BICUBIC 仿射（源图四周补 2px 透明，免得 PIL 把落在源图外的边缘像素丢掉）；只有整像素平移时原图对象原样返回。结果进有界 LRU（≤16M 像素、≤1024 张；源图资料另限 24 张），键含 `frame.ref`（角色、包版本/指纹、姿态、变体、眨眼、尺寸），稳定循环零重采样。
- 每个（立绘，动作族）只算一次缩放系数与底座平移：取该族一个周期内最坏的透明凸包水平外包络，放得下系数就是 1；不再逐帧 LANCZOS 缩小、也不夹住位移（shake 照常抖）；dash/leave 只按倾斜定尺寸，滑出列边时裁掉。换姿态时后台守护线程（只碰 PIL 与缓存，换计划即作废）从当前相位起按时间顺序预渲染一个周期；它没赶上的一两帧和 350ms 淡入期间的缺失用不入缓存的 BILINEAR 顶替。
- `crossfade_sprites(old, new, alpha)`：淡出的旧图也套当前动作，只在两图并集里做预乘混合（`crossfade`），透明度按 CSS `ease` cubic-bezier(.25,.1,.25,1) 查表；`crossfade(old, new, alpha)` 本身不变。
- `draw(canvas, fx, age, sprite_box, u, accent, glyph)`：在角色附近（不越过左栏 174u 宽）画小特效：pat 爱心、sleeping zZ 和月亮、idle/victory/happy 星星、happy 彩纸、hum 音符、thinking 思考云和三点、surprised「!」、oops 小红叉、tired 电量、stretch 暖光点、yawn「~♡」、DeepSeek 的 bubbles/steam、greet/fest 的简化版（太阳、月亮、萤火、雪花、灯笼、烟花、落叶等）。上游的终端／编辑器／浏览器卡片放不下工作台左栏，不画。

### E. 宿主接线（`pet.py`、`flat_workspace.py`、`ui_themes.py`）

AI 模式下由导演决定画面；`STATIC_BOX` 放宽到 `(2, -12, 174, LIVE_H-2)`；GLM 主题「墨夜狐影」；前台 `ZCode.exe`→GLM、`deepseek harness.exe`→DeepSeek；当前用户决定优先：只跟可靠前台 AI；普通应用保持当前角色，后台新任务不抢形象；菜单加「戳一下」；AI 模式下不再说小乔的台词、不播她的语音；退出时挥手 2s 再退出；`pet_cmd` 加 `ai_pose`（调试定格）。


## Codex 接手约束（2026-10-09 CST）

- 相较上游修正：明确手动休息独立于小乔隐藏 nap，AI 自动静默 10 分钟休息；固定/恢复不问候，前台换角色才问候。
- 彩蛋关闭同时禁随机和点击彩蛋；坏彩蛋只取消演出，坏主包角色与主题共同回退小乔。
- 工作姿态来自已有公开记录；完成庆祝的工具数仅为现有本轮非状态记录数，可能因采集去重低估/重复高估，不代表精确调用次数或进度。
- 不新增浏览器/终端猜测、账号读取、上游 hooks、模型控制权限或复杂物理引擎。

## 实现与验证记录（2026-10-09 CST）

- 素材来自固定版本 `c6a756e81862e45ffe16bfbccaba5fd301fe822f`，按字节复制 232 张 WebP、10 份角色元数据和原许可；生成 schema 2 清单，schema 1 兼容保留。228 个普通/彩蛋变体 × 两尺寸，456 个实际摆放验证通过；有效眨眼仅三个包，GLM 重绘帧不播放。
- 导演/工作适配/绘制分成三模块，宿主只接当前角色、高层互动、公开状态与 View；小乔沿用 Action/nap/rig，手动固定与前台选择不受后台事件控制。临时互动恢复持续工作、显式休息优先；聊天状态和缺包同帧回退保留。
- 独立审核闭合重复摸头台词、DeepSeek 长思考持有、同步心跳排序、旧 hook 延迟错误、畸形时间、旧气泡/粒子/播报、告别切换和语音取消。预热缩为逐资源加锁，保留并发去重与坏图整包回退。
- 完整隔离入口：890 项单元零失败/错误/跳过，旧兼容烟测 190/190。合成 HOME、禁网络、无真实模型或账号数据；源码哈希在检查前后逐项一致。文档引用和 602 个公开候选文件检查零发现，临时 Git index 未修改实际暂存区。
- 两档离线预览使用实际生产合成器与模拟数据；30 张主姿态、5 张较小视图、90 帧互动动图。真实运行目录以 263 文件哈希守卫选择性安装，备份已有文件，只正常关闭精确桌宠窗口；重启时模式、隐藏小乔打盹、位置（1px取整差）、缩放、视图和尺寸恢复。正常实例逐个通过五角色摸头/睡醒/戳一下与工作姿态恢复，小乔模式正常，最终恢复 AI/auto。后续验证期间位置变化，保留最新位置；未发重定位或前台激活指令。
- 这一步验收的是资源、功能和状态边界。没有把上游离散姿态称为连续主动作，没有声称完成性能 p95、浏览器/终端 AI 识别、自定义包编辑/导入界面，或完全复刻主题参考图的装饰；这些仍需后续小步工作。真实画布截图留在本机私有证据目录。


## I-49 气泡可见度（2026-10-09 CST）

AI台词使用直接在左栏合成的轻色圆角气泡、深字和主题描边，按实际透明边界定位；6–10秒停留，明确工作阶段变化时撤旧文字，主动互动和倾听台词不随短动作提前结束。工作台词8秒节流，保留提醒静音。固定50u顶部空间包括运动包络，脚底及窗口尺寸不变，角色适度缩小以避免气泡遮脸。文字存在时思考云暂避，随后恢复白云/描边/两尾泡/三点明暗/轻浮动。字体与单张气泡缓存有界，无新增模型调用或背景模糊；减少动画/拖动仍显示台词。


## I-50 动作与精灵（2026-10-09 CST）

- 亚像素动作缓存、按族固定缩放、旧图同动作淡出、同族相位连续、解码不挡帧，接口见上文 B/D 与 A。宿主仍只调用 `_static_look(art_size) -> (frame, dy)`，`frame` 多带 `alpha_box`，供合成不再逐帧 getbbox。
- 像素层面的差别：bob/hop/shake 等平移现在以 1/8 px 前进，非整数相位的帧是预乘 BICUBIC 重采样（整数相位仍是原图）；rock 顺时针到顶时旧版 x 夹边会让 Claude thinking 左跳约 2px，现已没有；宽姿态（如 delegating）旧版随摆动逐帧缩到 0.96–1.0 来回呼吸，现为常数（Codex delegating/sway 0.969，Claude 0.986），其余实测 Claude/Codex 的 idle、thinking、searching、sleeping、oops 系数都是 1；告别 dash/leave 现在真的滑向右边并在列边裁掉；淡入时旧图跟着摆，透明度按 ease 曲线。
- 思考云三点本来就是 1.2s 周期、0.3s 错相的连续明暗（I-49），只补了逐帧连续性回归测试；特效形状、颜色、列宽裁剪、单次分配均未改。
- Windows 实测（Python 3.14 / Pillow 12.3，u=1.5、列 258×249，60fps 节奏、关闭 EcoQoS 节流，base 与新版交替 3 轮）：rock 每帧 base p50 约 7ms、p95 约 10ms，新版稳定后 p50 0.15ms、p95 0.3ms；350ms 淡入期 p95 由 11.3ms 降到 3.9ms；只剩换姿态第一帧 2–9ms（算包络并顶替渲染）。数据与图在本机暂存证据目录，不入库。
