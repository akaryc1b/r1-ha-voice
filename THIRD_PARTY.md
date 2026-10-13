# 第三方来源

本仓库以安装环境、配置和本次修改源码备份为目的。没有把第三方 APK、模型、运行库或完整镜像重新打包上传。

| 项目 | 用途与来源 |
| --- | --- |
| Music Assistant Server 2.10.6 | [官方源码](https://github.com/music-assistant/server/tree/2.10.6)，Apache-2.0；原许可证保留在 `ma/LICENSE` |
| MA 源码优化 | `ma/ma-final` 保留修改前/后文件，差异见 `ma/ma-optimizations.patch`；修改涵盖元数据缓存、预热、有限起始读取、计时、R1 顺序取流与按钮等待 |
| MA AirPlay / cliairplay | [官方 MA AirPlay 说明](https://www.music-assistant.io/player-support/airplay/)，本次 cliairplay 0.5.5；仓库只记录来源/校验信息和依赖，不携带运行归档 |
| Sherpa-ONNX | [官方项目](https://github.com/k2-fsa/sherpa-onnx)，[1.13.8 发布](https://github.com/k2-fsa/sherpa-onnx/releases/tag/v1.13.8)，Apache-2.0 |
| 中文 Zipformer 模型 | [模型来源](https://huggingface.co/csukuangfj/sherpa-onnx-streaming-zipformer-zh-14M-2023-02-23)，下载清单与 SHA256 见 `asr/sources.json` |
| Debian ARM64 兼容库 | glibc、libgcc、libstdc++ 对应 Debian 软件包；只记录依赖，不携带二进制 |
| smali / baksmali | [官方项目](https://github.com/JesusFreke/smali)，2.5.2；Maven 工具依赖清单见 `device/build-tools.json` |
| Android SDK / D8 | 通过 Android SDK 安装，仓库不携带 SDK |
| R1 基础自定义固件 | 来自用户已有安装和下载；[用户选用的恩山论坛页面](https://www.right.com.cn/forum/thread-8491286-1-1.html)。不声称本仓库从该页面直接获得完整可重建源码 |

第三方源码、工具与服务各自保留其原有许可证和使用条件。当前仓库没有给厂商 SDK 或基础固件重新声明许可证。
