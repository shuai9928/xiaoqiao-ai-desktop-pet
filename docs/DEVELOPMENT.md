# 开发与维护

[文档导航](README.md) · [贡献约定](../CONTRIBUTING.md) · [工具说明](../tools/README.md)

## 当前入口与目录

`pet.py` 是唯一日常启动入口，生产 Python 模块保持在根目录。这样保留现有素材路径、打包导入、ZCode／WSL hook 和外部指令兼容性。本轮整理移动测试、工具和文档，不借目录迁移改写角色引擎。

```text
根目录 *.py            生产模块和外部接入入口
assets/                 角色、分层场景、特效与声音
tests/                  当前测试及旧兼容测试
tools/
  run_checks.py         隔离测试入口
  check_docs.py         本地文档链接检查
  check_public_files.py 发布内容检查
  preview_workspace.py  当前生产工作台的模拟数据预览
  assets/               素材制作与分层工具
  diagnostics/          特效、性能及其他诊断探针
  release/              Windows 打包工具
  legacy/               旧版制作／展示工具
docs/
  design/               六份设计与实验记录
  archive/              旧手册、交接与历史展示
  media/                当前文档图片
house3d/                保留原位的 Godot 实验
```

根目录入口源码代表当前行为。历史交接里的复制源码与旧预览只用于追溯，不是另外一套可继续修改的生产代码。

## 按职责找模块

| 修改方向 | 主要入口 |
| --- | --- |
| 角色状态、交互、菜单、聊天窗、Windows 窗口 | `pet.py`：`Pet`、`InteractionCard`、`ChatBox` |
| 实时／展开工作台、状态图形与额度布局 | `flat_workspace.py` |
| 活动合并成阶段、委派记录展开 | `workflow_stages.py` |
| 有限任务方向与子代理职责标签 | `task_directions.py` |
| Windows 原生 Codex／Claude 事件采集 | `native_session_sync.py` |
| 会话标签清洗与 hook 公共数据层 | `ai_lights_core.py`、`xiaoqiao-lights-hook.py`、`wsl_lights_hook.py`、`zcode_notify.py` |
| 跨机来源快照 | `mac_session_sync.py` |
| 额度快照的单位、缺失和过期语义 | `ai_quota.py` |
| AI 模式素材／视觉导演／公开工作适配／有限绘制 | `appearance.py`、`ai_pet.py`、`ai_work.py`、`ai_fx.py`；Pet 只接高层互动和 View，见[接入规格](design/CROSSPET_PORT.md) |
| 状态触发的陪伴规则与接线 | `agent_reactions.py`、`agent_companion.py` |
| 帽上特效与预烘焙缓存 | `hat_fx.py`、`fx.py` |
| 2.5D 网格、惯性和接触稳定 | `depth_model.py`、`life.py`、场景模块 |
| 聊天／卡片／原生菜单透明度 | `popup_material.py` |
| 可选角色模型聊天与记忆 | `ai_chat.py` |

桌宠不会因工作流显示而自动执行代理任务或批准操作。会话采集、额度读取和角色模型聊天保持独立，新增来源也应遵守这一边界。

## 开发环境与检查

按[安装指南](GUIDE.md)建立虚拟环境，之后从仓库根目录运行：

```powershell
py tools/run_checks.py
py tools/run_checks.py --unit-only
py tools/check_docs.py
py tools/check_public_files.py
```

使用虚拟环境时，将 `py` 换成 `.\.venv\Scripts\python.exe`。运行器把源码、测试和允许的素材复制到临时目录，禁用真实模型，提供测试配置，隔离聊天、记忆、会话与额度来源。不要直接在日常运行目录执行会建立 `Pet` 的集成脚本。

| 模式 | 检查范围 |
| --- | --- |
| 默认 | 规定的角色、生命、秋千、会话灯、数据层检查，加当前工作台／方向／原生采集／闭眼／弹层／特效等定向检查，并运行脚本式 `test_pet` |
| `--unit-only` | 用于 Windows CI 的当前单元与定向检查，省略脚本式 `test_pet` |
| `--legacy` | 另外运行旧引擎兼容检查；退役功能的断言可能失败，输出必须如实记录 |

`test_pet` 包含旧引擎兼容 fixture，不能替代默认核心模式的证明；`test_core_profile`、`test_core_runtime` 和当前 UI 测试负责约束日常行为。不要把 unittest 的发现数量当成 `test_pet` 的脚本断言数。检查数量以本轮实际输出为准，不保留旧总数充当当前成绩。

关键定向测试集中在 `tests/test_flat_workspace.py`、`test_workflow_stages.py`、`test_task_directions.py`、`test_native_session_sync.py`、`test_rest_eyes.py`、`test_popup_material.py` 和 `test_hat_fx.py`。缺失来源、过期记录、委派成功但代理未完成等情况必须按数据边界验证。

## 当前界面预览

```powershell
py tools/preview_workspace.py
py tools/preview_workspace.py --mode tasks
py tools/preview_workspace.py --mode steps
```

默认输出到 `outputs/current-workspace.png`。工具调用当前生产合成器，使用固定模拟活动，额度保持未知，不调用 AI，也不读取个人会话或真实用量。图片内保留“模拟”，文档图复制到 `docs/media/current-workspace.png`。`--mode` 可切换实时、任务或阶段视图；预览不运行思考过程或动态特效。

静态预览用于看布局、颜色和文字，不能替代实际桌面尺寸、动态效果或窗口操作验收。聊天和原生菜单还需检查输入、复制、焦点、键盘与透明度；半透明不是实时背景模糊。

## 修改时的约束


- 修改 `pet.py` 前检查并行写入和 mtime，使用原子写入；保持日常实例、个人存档和设置可恢复。
- 脸部不做明显橡皮变形，握绳、坐垫和身体接触保持稳定；真实桌面尺寸先于放大图。
- 动作按经过时间计算，一次性反馈去重；粒子和缓存有上限，运行时不加入重模糊来掩盖结构问题。
- 互动奖励走 `gain_star()`；不通过新视觉反馈增加模型调用或改写真实额度。
- 工作流只能归纳已观察的公开活动，不输出文件／命令流水账，不虚构计划、并行数、子代理完成或百分比。
- 额度缺失／过期与会话结束／等待分开处理；不要用测试数据替代真实接入。
- 辅助窗口透明度接口不能用于主人物的 `UpdateLayeredWindow` 绘图窗口。

## 发布

审阅改动、运行隔离检查、复核对应界面，再运行 `git diff --check`、文档和公开文件检查。发布检查只检查跟踪／暂存内容，是额外守卫，不能代替对新增文件和演示图的人工审阅。

Windows 打包入口是 `py tools/release/build_release.py`，需安装 `requirements-build.txt`。目录整理不等于可执行发布包已经验收；包内素材、运行入口、外部 hook 依赖和敏感文件排除需另行验证。

历史说明集中在 [docs/archive](archive/README.md)。不要把归档中的旧菜单、源代码副本、性能数字或图稿写进当前能力清单。新增依赖和素材来源应同步更新许可说明。


## 秋千动作预览

`py tools/preview_seated_actions.py` 调用生产姿态和合成器，用公开素材与模拟状态生成两组8动作的100%/76%动图、关键帧和帧成本报告。它不创建日常主实例、不读取账户/会话/存档。默认输出到outputs/seated-actions；首次重绘、同姿态缓存与冷网格成本分别记录，不能以缓存结果掩盖首遍开销。

已有 `pet_cmd.json` 的demo命令可加 `seat_action`（glance/nudge/startle/relief/pat/flick/push/shy），页脚保留模拟；`secs` 到期恢复真实工作台。它遵守安静/拖动守卫，不唤醒睡眠、不改偏好，不奖励星光或调用模型。真实主实例演示须观察实际状态，单纯代码和离线GIF不证明命令播起来。


## Hybrid 动画的第一步（I-41）

当前调用链、资源缺口、分阶段计划和ADR见[Hybrid架构评估](design/HYBRID_ANIMATION.md)。现阶段只有8个坐姿视觉动作进入统一Action API；主movement状态机仍由Pet维护，尚未迁移成新的完整FSM。

`Pet.perform_action(name, source="user", side=1)` 请求glance/nudge/startle/relief/pat/flick/push/shy；合法source为user/agent/demo，agent只可请求前4个。名字、来源、镜像和时钟经过校验；不接收位置、速度、frame、rotation或任意模型字典。`start_seat_action(name, side)`保留兼容并走同一API。调用者保留原奖励/台词/音效，demo不增加这些副作用。

`character_actions.ActionSystem` 复用SeatMotion的优先级和时间轴；idle/playing/blocked只表示坐姿子层。主状态上下文、每帧更新、离座和五官采样同步取消，动作自有眼睑/排队眼睑/嘴形按token释放，其他聊天表情保留。取消动作不排队恢复；snapshot只读。现有state导出可观察`action_system`的公开动作名、来源、接收/拒绝原因，不导出请求正文或姿态参数。

当前已有mouse look、局部呼吸、Spring与Pendulum，后续先整理真实Sprite clip配置和锚点，再抽取PoseComposer的最终限幅及物理时序。不要为了架构名义重新实现这些已有通道；缺动作素材保持现有底图/idle，不用夸张变形冒充新主动作。

## Hybrid Phase 1B：秋千生命周期（I-42）

`pet.py`的`_enter_swing_state / _update_swing_state / _swing_stop`划清秋千进入、帧内一致性和退出；`_set_swing_nap`统一打盹切换。主事实来源仍是state、_swing和_nap_on_swing，其他movement继续分批整理。当前没有第二个FSM，也不在render中重复推进钟摆。

入盹同步取消坐姿动作，入盹／离座使旧点击和长按失效，移动场景拖动优先于休息。醒来保持同一scene／pend与theta／omega；清醒时重复wake不拆场景。定向测试见`tests/test_swing_lifecycle.py`，通过统一隔离入口运行。完整决策与限制见[架构评估](design/HYBRID_ANIMATION.md)。

## Hybrid Phase 2A：局部眨眼 Sprite（I-43）

`assets/animations/manifest.json` 定义当前角色的非循环局部眨眼：半闭40ms、闭眼100ms、半闭40ms，结束回到底图。两个RGBA PNG共用固定canvas、rect与anchor；源图RGBA和eyes参数指纹必须匹配。它不是walk／jump等主动作资源协议。

`SpriteBank.load(ASSETS, main_src, eyes)` 只在初始化读盘、校验和解码；`sample("blink", elapsed)` 按经过时间返回有限帧身份，`overlay(ref, target_size)` 等比缩放并复用最多8项缓存。宿主将版本／帧身份放入原五官和网格缓存键。缺帧、坏图、错配或超资源预算整段退回原程序眨眼；睡眠持续闭眼不播放这段clip。测试见`tests/test_sprite_animation.py`与`tests/test_blink_sprite_runtime.py`，仍通过统一隔离入口执行。

```powershell
py tools/bake_blink_clip.py --write-assets
py tools/preview_blink_sprite.py
```

制作工具从公开底图和当前闭眼画法预烘焙，半闭曲线沿已标定眼部倾角；更换立绘或eyes参数后需重新制作并复核。预览使用生产合成器、公开素材和合成状态，输出100%／76%静帧和180ms片段，不能替代真实窗口调度与观感验收。工具不创建Pet实例、不读存档、不开窗口、不调用模型。

已有临时demo可加`blink: true`测试眨眼，`secs`到期恢复真实工作台；睡眠时拒绝开始，不唤醒、奖励或调用模型。state中的`sprite_animation.last_frame`是上一张实际采样脸的帧身份，不是当前时刻播放位置。正常启动无需`--debug-state`，只在明确诊断请求时写一次state。

## Hybrid Phase 2B1：松口气的身体通道（I-44）

`assets/animations/relief-body/manifest.json`只定义已有`relief`的胸肩起伏，完整动作仍由原视线、表情、帽发和秋千共同表达。14个200ms采样段复用9张PNG；连续同图合并后13条资源记录，总时长仍2.8秒。它不是完整主movement素材集，不改变现有触发方式或Action权限。

`BodySpriteBank`独立于眨眼资源，绑定当前`swing_studio`源RGBA、公开rig/meta及接触几何版本。载入阶段校验时间、路径、坐标、PNG格式、字节和解码预算，任一失败整段回退。PNG共解码1,427,337像素，另保存一份906×1254源RGBA；运行时从完整源画布合成并同相位缩放，再裁局部替换，避免单独缩放crop导致眼嘴错位。缩放缓存最多8项，临时目标画布最多4M像素，无逐帧读盘。

默认flat路径从同一个SeatMotion取elapsed，RGBA无mask替换会清掉旧透明轮廓；成功后才从有效呼吸量扣除已烘焙部分。有效姿态继续用于特效挂点，余下姿态交给原网格。缓存记录实际应用帧，fallback不会误报播放。取消、优先级、睡眠和拖动仍沿用原Action System；非flat或缺资源使用完整旧路径。

```powershell
py tools/bake_relief_clip.py --write-assets
py tools/preview_relief_sprite.py
```

制作工具只使用公开原图与原网格，保留脸和接触区RGBA；预览对比100%／76%档真实生产合成器，使用合成活动，不调用模型或读取存档。定向检查见`tests/test_body_sprite_animation.py`、`tests/test_body_sprite_runtime.py`，通过统一隔离入口。两次采样与脸部保护不等于和旧整姿态逐像素相同；对比计时也不是桌面逐帧p95。变更接触算法后须推进`contact_gate_version`并重新制作资源。


## AI 头顶反馈

`ai_bubble.py` 是有限文字排版/停留/定位，宿主持有一张缓存图；`flat_workspace.static_layout` 给已有角色运动留头顶气泡带。文字在导演消费 View.say 后同帧合成，不走小乔隐藏投影；`ai_fx` 画没有文字时的思考云。直接回归为 `test_ai_bubble` / `test_ai_fx`，覆盖实际透明轮廓、无帽FX留白、小档、跳跃包络、节流与切换取消。
