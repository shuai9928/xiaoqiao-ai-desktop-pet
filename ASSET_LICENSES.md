# 素材与授权说明

源码的 MIT 许可不覆盖第三方美术、角色、音乐和语音。

公开演示视频、字幕和截图位于 `docs/media/`；来源、CrossPet 角色署名与配音说明见 [媒体说明](docs/media/README.md)。这些媒体中的第三方内容不因源码 MIT 许可而改变授权范围。

| 素材 | 来源及分发说明 |
| --- | --- |
| `assets/main.png`、`main.jpg`、`decor_*.png`、`expr/*.png` | 原项目提供的角色立绘与贴纸。维护者于 2026-09-13 确认拥有随本项目公开分发的授权。版权归各自权利人；本仓库不额外授予素材商用、修改或再次分发许可。 |
| `assets/animations/blink-half.png`、`blink-closed.png` | 从上述当前角色底图及本项目眼部画法预烘焙的局部表情帧，制作入口为 `tools/bake_blink_clip.py`。沿用原角色素材的授权范围，不因派生或源码 MIT 许可扩大素材使用许可。 |
| `assets/animations/relief-body/*.png` | 从项目当前 `assets/scene/swing_studio.png` 及生产接触网格预烘焙的胸肩通道，制作入口为 `tools/bake_relief_clip.py`。沿用原角色素材的授权范围，不额外授予素材使用或再分发许可。 |
| `assets/characters/{claude,codex,gemini,deepseek,glm,egg-*}/*.webp` 与 `character.json` | AI 桌宠模式的五主角色与五彩蛋包，按字节取自 [CrossPet 1.2.4](https://github.com/lokicorvus/crosspet)（固定源码版本 `c6a756e81862e45ffe16bfbccaba5fd301fe822f`，上游 GPT 包在本项目名为 Codex）。232 张原图不经重绘／裁切，表现为离散姿态与有限实时细节，不宣称连续骨骼动画。采用 **CC BY-NC-SA 4.0**：保留 CrossPet 与 [LICENSE.md](assets/characters/LICENSE.md) 所列原作者署名、不得商用、派生作品同协议；源码 MIT 不覆盖图像与角色设定。上游署名表没有逐项列出新增 GLM 和 Gemini 彩蛋，保留原表、不猜作者。清单生成器只生成尺寸、哈希、落脚点与有限角色元数据；上游脚本、hooks、安装器未运行或分发。Claude、GPT／Codex、Gemini、DeepSeek、GLM／ZCode 为各权利人的商标，本项目与其无关。 |
| `assets/song.mp3` | 原项目提供的歌曲，维护者确认可随本项目公开分发。版权归权利人；不适用源码 MIT 许可。 |
| `assets/audio/` 的角色语音 | 使用 Microsoft Edge 的 zh-CN-XiaoxiaoNeural 语音预渲染。原始来源记录见下方链接；维护者确认可随本仓库公开分发，不据此推定微软服务输出普遍具有开源许可。 |
| `assets/audio/magic_1.wav` 至 `magic_6.wav` | 原来源记录：JaggedStone 的 [Magic Spell SFX](https://opengameart.org/content/magic-spell-sfx)，CC0；从原音频转换为 WAV。 |

音频原始记录见 [assets/audio/CREDITS.md](assets/audio/CREDITS.md)。其中“仅在本机自用”属于早期制作记录；本次公开分发依据维护者另行确认的授权，未将其扩展为对所有使用者的素材再授权。

若要单独使用、修改、商用或再次分发第三方素材，请自行核实对应授权范围。也可替换为自己有权使用的素材；角色形状变化较大时，需要同步调整 `assets/config.json` 中的五官位置和 `depth_model.py` 中的部位权重。

如发现署名或授权记录需要更正，请联系仓库维护者。请勿在 Issue 中上传私人授权文件、身份证明或合同原件。
