# 开发工具

[开发指南](../docs/DEVELOPMENT.md) · [测试说明](../tests/README.md)

从仓库根目录运行：

| 命令 / 目录 | 用途 |
| --- | --- |
| `py tools/run_checks.py` | 隔离当前核心回归与必需旧引擎兼容烟测 |
| `py tools/run_checks.py --unit-only` | 当前单元检查，供CI使用 |
| `py tools/run_checks.py --legacy` | 额外检查退役功能 |
| `py tools/check_public_files.py` | 跟踪文件的运行数据、密钥和本机路径检查，只输出位置 |
| `py tools/check_docs.py` | 本地链接、锚点和媒体检查 |
| `py tools/preview_workspace.py` | 当前工作台离线预览，只用合成数据，不读取会话或调用模型；`--look claude` 等预览 AI 桌宠，`--screen-height 1080/1800` 切 1.0／1.5 密度 |
| `py tools/import_crosspet.py --source <clone>` | 仅复制固定上游五主角色及彩蛋的原图／角色设定／许可；完整验证后写入，`--check` 只读校验。不运行上游代码或 hooks |
| `py tools/build_character_manifests.py` | 由 AI 角色图生成 `assets/characters` 的 registry 与 manifest（尺寸、哈希、落脚点）；`--check` 只校验 |
| `py tools/bake_blink_clip.py --write-assets` | 从公开立绘和眼部参数预烘焙局部眨眼PNG与manifest，在开发副本执行 |
| `py tools/preview_blink_sprite.py` | 当前生产网格合成眨眼静帧和动图，100%／76%档、合成状态 |
| `py tools/bake_relief_clip.py --write-assets` | 预烘焙松口气身体通道，保护脸与接触区域，在开发副本执行 |
| `py tools/preview_relief_sprite.py` | 对比旧程序呼吸与身体PNG的两档生产模拟图，计时为诊断用途 |
| `tools/assets/` | 素材派生与布局导出，手动开发工具 |
| `tools/release/build_release.py` | Windows打包、发布副本净化与本机存档回填 |

素材生成器可能写素材，在独立开发副本执行。探针的额外依赖见脚本说明。旧真实AI质量脚本和通配重启脚本均已归档，不进入默认检查。

公开文件检查仅覆盖跟踪或暂存文件；文档检查不验证外部网站。打包工具存在不等于已经发布验收过的exe。
