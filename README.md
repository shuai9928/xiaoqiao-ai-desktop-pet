# AI 桌宠 · Windows

运行在 Windows 桌面的陪伴桌宠：可跟随当前 Claude、Codex、ZCode 窗口换成 AI 角色，用姿态与工作台显示本机 AI 的工作状态。也可切换为自定义的小乔角色。此分发版基于 2026-10-10 的 I-52，并恢复小乔表情贴纸默认开启。

[演示视频](#演示视频) · [下载源码 ZIP](https://github.com/shuai9928/xiaoqiao-ai-desktop-pet/archive/refs/heads/main.zip) · [使用指南](docs/GUIDE.md) · [更换角色](docs/CUSTOMIZE.md)

源码现已公开，采用 MIT 许可，无需下载密码。角色、美术和音频保留各自授权范围，详见[许可](#许可)。原[介绍页](https://xiaoqiao-ai-desktop-pet.alightcloud6.chatgpt.site)的历史便携包下载仍可能要求密码，与公开 GitHub 源码的访问无关。

## 演示视频

https://github.com/user-attachments/assets/c880d15e-7eaf-4cdc-a23d-11ee9215c8d1

**[观看完整视频（约 53 秒）](https://github.com/user-attachments/assets/c880d15e-7eaf-4cdc-a23d-11ee9215c8d1)** · [下载 1080p MP4](https://raw.githubusercontent.com/shuai9928/xiaoqiao-ai-desktop-pet/main/docs/media/demo.mp4) · [字幕](docs/media/demo.srt) · [封面、截图与署名](docs/media/README.md)

页面内可播放完整 720p 版本，1080p 原片可单独下载。

视频为离线渲染的功能演示，会话、额度和文件名均为模拟数据。画面展示制作时的演示版本；本仓库为上文所述 I-52 分发版，具体功能和接入条件以源码与使用指南为准。AI 角色画面沿用 CrossPet 的 CC BY-NC-SA 4.0 署名与使用范围。

## 便携版

Windows 10/11 x64。把下载的 ZIP 完整解压到有写入权限的文件夹，再双击 `DesktopPet.exe`；无需安装 Python。保持 `_internal` 与 `assets` 在程序旁边，不要直接在压缩包内运行。

初次启动不需要 AI 密钥。右键打开互动卡片，在「场景与设置 → 桌宠形象」切换 AI／小乔；AI 模式可自动跟随或固定形象。拖动移动，滚轮缩放，双击聊天，托盘或设置菜单退出。

程序自动观察 Windows 本机已存在的 Codex／Claude Code 日志。ZCode、WSL、跨机来源和账户额度需要另行配置相应 hook 或数据来源；安装桌宠不会自动创建这些来源。没有数据时显示缺失，不填造进度或额度。

自由聊天是可选功能，需使用自己的 Gemini 服务配置。基础互动和工作状态显示不调用模型。配置、聊天、个人记忆和状态只写在本机程序目录，请勿把运行后的文件夹上传。

升级时先从菜单退出旧实例，再解压新版到新目录。个人数据迁移前先备份；不要直接覆盖运行中的安装。

## 源码启动

直接[下载源码 ZIP](https://github.com/shuai9928/xiaoqiao-ai-desktop-pet/archive/refs/heads/main.zip)解压，或使用 `git clone https://github.com/shuai9928/xiaoqiao-ai-desktop-pet.git`。获取源码无需 GitHub 登录。

准备 Windows 10/11 和带 Tkinter 的 Python（此版本使用 Python 3.14 验证）：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe pet.py
```

开发检查：`py tools/run_checks.py --unit-only`。构建便携 ZIP：安装 `requirements-build.txt` 后运行 `py tools/release/build_release.py`。构建目录不可用作现有安装目录；输出位于 `release/Xiaoqiao-AI-Pet-Windows-x64.zip`。

完整使用与数据说明见 [docs/GUIDE.md](docs/GUIDE.md) 与 [docs/ASSISTANT.md](docs/ASSISTANT.md)。

想换成自己的角色：看 [把小乔换成你的角色](docs/CUSTOMIZE.md)。当前为手动素材／配置编辑，需自行备份与校准；素材许可独立于源码。

## 许可

源码采用 MIT，第三方角色、美术、音乐和语音各有许可范围。AI 角色来自 CrossPet，适用 CC BY-NC-SA 4.0（署名、非商用、相同方式共享）；请保留 [ASSET_LICENSES.md](ASSET_LICENSES.md) 与 [角色许可](assets/characters/LICENSE.md)。源码许可不覆盖第三方素材。
