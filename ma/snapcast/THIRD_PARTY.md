# 第三方来源和许可证

Music Assistant Snapcast provider 基于 [music-assistant/server 2.10.6](https://github.com/music-assistant/server/tree/2.10.6/music_assistant/providers/snapcast)，采用 Apache License 2.0，本目录 LICENSE 保留其许可证。upstream/ 为固定源，provider/ 为本项目修改；哈希及补丁用于审阅，不代表上游已经接受这些修改。

Snapdroid 来自 [snapcast/snapdroid v0.29.0.2](https://github.com/snapcast/snapdroid/tree/v0.29.0.2)，采用 GPLv3；完整许可证在 LICENSE-SNAPDROID。这里保留修改方法和新增 smali 源，以及从官方包复现候选的脚本，不附官方/修改后 APK，不改变上游许可证。发布自己构建的 APK 时须同时遵守对应源码与许可要求。

工具来源是 [smali 2.5.2](https://github.com/JesusFreke/smali) 及其 Maven 依赖，各文件 URL/SHA 在 build-tools.json。工具二进制不随仓库分发。Android SDK/JDK 使用各自许可。

依赖包分别来自 [python-snapcast](https://github.com/happyleavesaoc/python-snapcast)、[bidict](https://github.com/jab/bidict)、[websocket-client](https://github.com/websocket-client/websocket-client)、[packaging](https://github.com/pypa/packaging)、[construct](https://github.com/construct/construct)。仅保存版本清单，不打包其运行库。Snapserver 来源为 [snapcast](https://github.com/snapcast/snapcast)，复用当前环境已有二进制。
