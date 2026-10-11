# AI 桌宠 · Windows

运行在 Windows 桌面的陪伴桌宠：可跟随当前 Claude、Codex、ZCode 窗口换成 AI 角色，用姿态与工作台显示本机 AI 的工作状态。也可切换为自定义的小乔角色。此分发版基于 2026-10-10 已安装的 I-52。

[介绍与密码下载](https://xiaoqiao-ai-desktop-pet.alightcloud6.chatgpt.site) · [私密源码仓库](https://github.com/shuai9928/xiaoqiao-ai-desktop-pet)

下载页提供 Windows 便携包与源码 ZIP，需由所有者提供下载密码；介绍页可直接访问。GitHub 仓库按仓库权限访问，下载密码不授予 GitHub 权限。

## 便携版

Windows 10/11 x64。把下载的 ZIP 完整解压到有写入权限的文件夹，再双击 `DesktopPet.exe`；无需安装 Python。保持 `_internal` 与 `assets` 在程序旁边，不要直接在压缩包内运行。

初次启动不需要 AI 密钥。右键打开互动卡片，在「场景与设置 → 桌宠形象」切换 AI／小乔；AI 模式可自动跟随或固定形象。拖动移动，滚轮缩放，双击聊天，托盘或设置菜单退出。

程序自动观察 Windows 本机已存在的 Codex／Claude Code 日志。ZCode、WSL、跨机来源和账户额度需要另行配置相应 hook 或数据来源；安装桌宠不会自动创建这些来源。没有数据时显示缺失，不填造进度或额度。

自由聊天是可选功能，需使用自己的 Gemini 服务配置。基础互动和工作状态显示不调用模型。配置、聊天、个人记忆和状态只写在本机程序目录，请勿把运行后的文件夹上传。

升级时先从菜单退出旧实例，再解压新版到新目录。个人数据迁移前先备份；不要直接覆盖运行中的安装。

## 源码启动

准备 Windows 10/11 和带 Tkinter 的 Python（此版本使用 Python 3.14 验证）：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe pet.py
```

开发检查：`py tools/run_checks.py --unit-only`。构建便携 ZIP：安装 `requirements-build.txt` 后运行 `py tools/release/build_release.py`。构建目录不可用作现有安装目录；输出位于 `release/Xiaoqiao-AI-Pet-Windows-x64.zip`。

完整使用与数据说明见 [docs/GUIDE.md](docs/GUIDE.md) 与 [docs/ASSISTANT.md](docs/ASSISTANT.md)。

## 许可

源码采用 MIT，第三方角色、美术、音乐和语音各有许可范围。AI 角色来自 CrossPet，适用 CC BY-NC-SA 4.0（署名、非商用、相同方式共享）；请保留 [ASSET_LICENSES.md](ASSET_LICENSES.md) 与 [角色许可](assets/characters/LICENSE.md)。源码许可不覆盖第三方素材。
