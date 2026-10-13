# N1 环境与启动配置

已有环境不必重装。下面说明复现这套方案时要准备的组件，不要求把镜像、模型、运行库上传到 GitHub。

## 1. 宿主和容器

- N1：ARM64 OpenWrt，Docker，宿主 Python 3。
- 保留现有 HA Container（本次 2026.10.1），端口 8123。
- MA 2.10.6，host 网络，端口 8095；本次容器名 r1-apple-music。
- MA 数据挂载：/mnt/mmcblk2p4/r1-apple-music/data:/data。
- 网关在 MA 容器内运行，需已有 aiohttp、numpy；不需要在 HA 容器安装这些依赖，也不新建语音容器。

检查命令：

~~~sh
docker ps
python3 --version
docker exec r1-apple-music python -c 'import sys,aiohttp,numpy; print(sys.version); print(aiohttp.__version__,numpy.__version__)'
~~~

MA 镜像来源：[官方仓库](https://github.com/music-assistant/server)，版本固定 2.10.6。本次官方 ARM64 来源摘要：

~~~text
ghcr.io/music-assistant/server@sha256:f96e5feaca760dbce34ee7ca79b5ae56a8d636b9af73985240a4f59322b0b5dc
~~~

完整官方镜像已包含其配套 Python/播放依赖。现有精简镜像可继续使用；不为了修改 ASR 模型重新下载完整镜像。

## 2. 本地语音识别

当前安装：

- [Sherpa-ONNX 1.13.8 ARM64 shared CPU 运行时](https://github.com/k2-fsa/sherpa-onnx/releases/download/v1.13.8/sherpa-onnx-v1.13.8-linux-aarch64-shared-cpu.tar.bz2)。
- [中文 Zipformer 14M INT8 模型](https://huggingface.co/csukuangfj/sherpa-onnx-streaming-zipformer-zh-14M-2023-02-23)。
- encoder、decoder、joiner 三个 ONNX 文件与 tokens.txt；完整下载 URL 和 SHA256 见 ../asr/sources.json。
- 运行时需要 libonnxruntime.so、libsherpa-onnx-c-api.so、libsherpa-onnx-cxx-api.so 和 WebSocket server。

OpenWrt 使用 musl，而本次官方识别二进制使用 glibc。当前在独立 compat 目录准备了 Debian ARM64 glibc 2.41（实际版本 2.41-12+deb13u3）及以下库：

~~~text
ld-linux-aarch64.so.1
libc.so.6
libm.so.6
libdl.so.2
libpthread.so.0
librt.so.1
libgcc_s.so.1
libstdc++.so.6
~~~

可从 Debian ARM64 对应 [libc6](https://packages.debian.org/trixie/arm64/libc6/download)、[libgcc-s1](https://packages.debian.org/trixie/arm64/libgcc-s1/download)、[libstdc++6](https://packages.debian.org/trixie/arm64/libstdc++6/download) 包提取，放入独立目录，**不覆盖 OpenWrt 的系统 libc**。不要把 HA Alpine 的 musl 库复制进此环境。

当前目录：

~~~text
/mnt/mmcblk2p4/r1-asr-eval-20261013/
  server_launcher.py
  music-hotwords.txt
  tokens.txt
  encoder-epoch-99-avg-1.int8.onnx
  decoder-epoch-99-avg-1.int8.onnx
  joiner-epoch-99-avg-1.int8.onnx
  runtime/
    sherpa-onnx-online-websocket-server
    libonnxruntime.so
    libsherpa-onnx-c-api.so
    libsherpa-onnx-cxx-api.so
    compat/...
~~~

把仓库 asr/server_launcher.py、music-hotwords.txt 与下载的文件放入该目录。启动器通过独立 glibc loader 运行，只为该进程清除 LD_PRELOAD。

安装启动模板前检查 services/r1-local-asr 中的 task_root：

~~~sh
cp services/r1-local-asr /etc/init.d/r1-local-asr
chmod +x /etc/init.d/r1-local-asr
/etc/init.d/r1-local-asr enable
/etc/init.d/r1-local-asr start
~~~

服务端口 16066。本次两个识别线程、单流、热词分数 1.5；句尾静音 1.3 秒，长静音 4 秒。更换本地模型/断句参数时改服务参数并重启，不需要改云端 ASR 代码。

## 3. 网关文件与服务

将以下四个仓库文件放到 MA 数据目录下的 r1-cloud-voice/：

~~~text
gateway/voice_gateway.py
gateway/gateway_config.py
gateway/music-commands.json
gateway/command-pause-16k.wav
~~~

当前宿主路径为 /mnt/mmcblk2p4/r1-apple-music/data/r1-cloud-voice，容器内是 /data/r1-cloud-voice。

保留已有 gateway.private.json。旧 provider.private.json / ma-authorization.private 可以迁移；新安装可参考 gateway/gateway.example.json 创建配置，然后在 8080 填写真实密钥与 MA 令牌。

将 services/r1-cloud-voice 的容器名改为自己的 MA 容器名，再安装服务：

~~~sh
cp services/r1-cloud-voice /etc/init.d/r1-cloud-voice
chmod +x /etc/init.d/r1-cloud-voice
/etc/init.d/r1-cloud-voice enable
/etc/init.d/r1-cloud-voice restart
~~~

服务运行命令就是：

~~~sh
docker exec r1-apple-music python -u /data/r1-cloud-voice/voice_gateway.py
~~~

网关默认 N1 192.168.1.88:16068。更换 IP 时更新 gateway.private.json 的 bind_host、allowed_clients、r1_control_url，并在 R1 8080 更新网关/离线识别地址。改模型无需重启；改监听地址需重启服务。

## 4. AirPlay 和 MA

官方 MA 配套依赖完整时，直接在 MA 启用 AirPlay 并发现 R1 的 MediaCenter 接收端。本次接收端原始名称是 Airplay-Player-MediaCenter；它是 R1 的物理协议，不是另一个音箱。

当前精简环境补齐过的依赖清单：

| 包/组件 | 配套版本 |
| --- | --- |
| pyatv | 0.18.0 |
| chacha20poly1305-reuseable | 0.13.2 |
| miniaudio | 1.71 |
| pydantic / pydantic-core | 2.14.0 / 2.50.0 |
| annotated-types / typing-inspection | 0.8.0 / 0.4.4 |
| srptools / tabulate / tinytag | 1.0.1 / 0.10.0 / 2.3.2 |
| cliairplay ARM64 | 0.5.5 |

这些是当前已验证镜像的配套文件，不能据此全局升级 HA 或宿主 Python。缺失时优先使用同版本官方 MA 文件；ARM64 miniaudio 未必有对应 wheel，不要把“pip 一次安装”当成已验证安装方法。

打开 MA 8095，添加 Apple Music 并完成订阅账号授权，创建 MA 访问令牌。把 R1 的 AirPlay 关联到实际逻辑播放器并选为首选协议，停用重复逻辑播放器。

在 R1 8080 的“音乐播放与音源”填写 MA 地址、队列 ID、令牌。host 网络下网关访问 MA 通常用 http://127.0.0.1:8095。

## 5. R1、HA 与 AI

R1 需要已安装兼容的自定义语音应用并能连接 ADB。本仓库仅保存客户端源码与构建报告，不打包厂商 APK；保留自己已验证的 APK 备份，重建/覆盖安装见 [BUILD.md](BUILD.md)。

HA 接入：

1. 将 ha/packages 的两个 YAML 复制到 HA /config 根目录。
2. 合并 ha/custom_sentences/zh-cn；复制 ha/www/r1-player-card.js 到 /config/www。
3. 将面板 YAML 放为 /config/r1_music_dashboard.yaml。
4. 参考 ha/configuration.snippet.yaml 合并配置，不覆盖整个 configuration.yaml。
5. 用授权示例创建 /config/r1_music_authorization.yaml，写入带 Bearer 前缀的 MA 令牌。
6. 替换 IP、队列 upbac50e55、Apple Music 实例 apple_music--tP6RUHDy、面板温湿度实体。
7. 检查 HA 配置后重载/必要时重启。
8. 在 HA 创建长期访问令牌，填入 R1 原有 /4 页面；它不是 MA 令牌。

温湿度语音按 HA 区域寻找传感器；把传感器放入正确区域。电脑控制在 ha/optional，默认不启用、不包含私人 SSH 密钥。

R1 的 /5 继续配置聊天 AI；8080 的“语音识别与播报”配置 ASR/TTS。模型 ID 需由对应接口支持。

## 6. 最少验收

- 网关 health 的 asr 与网页保存值一致。
- 8080 保存、刷新后配置一致，密钥不回显。
- 合成 ASR 测试返回“暂停”且不执行指令。
- 现场分别测试暂停/恢复、自然点歌、温湿度和普通问答。
- 听见新歌才算切歌完成，界面切换不等于已经出声。

## Snapcast 替代播放接收端

复用 MA 容器的 snapserver 0.34.0，不增加容器。精简镜像需恢复同版本 Snapcast provider，
以及 snapcast、bidict、websocket-client、packaging 纯 Python 依赖。
R1 为 Android 5.1 / API 22 / ARMv7，使用匹配的 Snapdroid 0.29.0.2；
本次修改仅关闭其强制44.1→48 kHz软件重采样，并提供显式保存服务器的启动参数。

完整下载来源、SHA、参数化部署/回退和许可证见 [ma/snapcast](../ma/snapcast/README.md)。
服务使用 TCP 1704（音频）、1705（控制），均限定可信局域网。
MA 需将 Snap 输出挂到原逻辑播放器并设置为首选，保留 HA 与网关现有队列 ID。
不能靠直接在数据库替换 player_id 迁移。
传输为 44.1 kHz / 16 bit / stereo FLAC；R1 HAL 仍可能使用48 kHz，
不宣称整个硬件链路 bit-perfect。暂停/恢复与进度能力见该 provider 说明及实测记录。
