# R1 的 Snapcast 播放候选

复用现有 Music Assistant 的 Apple Music 授权和队列，R1 用兼容 Android 5.1 的 Snapdroid 接收音乐。语音助手继续运行，不使用蓝牙模式，也不增加 LMS 或音乐服务容器。

此目录保存环境、少量源代码适配与复现方法，不附 APK、JAR、模型、镜像或运行库。实际采用的路由和验收结果以项目主文档为准；本目录不把后台取流时间当成新歌实际出声时间。

## N1 需要什么

| 项目 | 已核对版本/要求 |
|---|---|
| 现有 MA | Music Assistant 2.10.6，Python 3.14 |
| Snapserver | 已有镜像中的 v0.34.0；不用另开容器 |
| Python 依赖 | requirements.txt 中 5 个纯 Python 包；construct 通常已存在 |
| Web/配置 | 镜像已有 /usr/share/snapserver/snapweb 和 /etc/snapserver.conf |
| R1 | Android API22 / ARMv7；官方 Snapdroid 0.29.0.2 最低 API21 |

普通完整 MA 镜像通常已有 Snapcast 环境；只有删除过 provider/依赖的精简镜像需要恢复。先检查环境，不重复安装整个 HA 或 MA。不要把 OpenWrt 的 musl 库复制到 Debian/glibc 容器。

上游 MA 2.10.6 把 Snapcast 标为 unmaintained，需做长播和控制稳定性验证。[官方环境说明](https://www.music-assistant.io/player-support/snapcast/)；[固定版本源代码](https://github.com/music-assistant/server/tree/2.10.6/music_assistant/providers/snapcast)。

暂停使用 STOP/RESUME 模拟，状态为 idle；本轮还发现单曲循环预载可能污染非零 seek 的进度 metadata。准确续播/seek 尚未全部验收，详见 [FLOW_PROGRESS_LIMITATION.md](FLOW_PROGRESS_LIMITATION.md)。不能仅凭播放稳定或后台加载快就宣称功能完全等同。

## 三个源文件为何修改

- constants.py：R1 专用默认改为 44100 Hz、16 位、双声道，允许 44100，使用镜像现有 Snapweb 目录。上游内置固定 48000 Hz，单改 snapserver 配置不能让 MA 同步保持 44100。
- player.py：把 Snapcast 输出声明为 PROTOCOL，按 MAC/设备标识并入现有通用播放器，避免原 HA/网关队列 ID 被新的 native 播放器替换；另外增加可选硬件音量入口。
- r1_hardware_volume.py：仅对显式配置 URL 的客户端生效。Snap 软件保持 unity，用户音量直接读写 R1 音乐硬件端点，避免软件和硬件重复衰减。不触碰语音 stream 9、不把系统音乐音量拉满。

这是 R1 专用适配。多设备部署应逐一验证，不能把这组默认值当成所有 Snapcast 场景的通用最佳配置。传输使用 FLAC 或 PCM，保留音质；设备 HAL 是否重采样还需检查，不能据配置宣称全链路 bit-perfect。

本机最终采用 `oboe` 引擎、Android硬件burst1024、44100Hz/16位/双声道、FLAC、服务器缓冲500ms。用户已在现场确认播放正常、无噼啪；后台短测仍有少量重同步，完整边界及失败的独立OpenSL对照见 [BUILD.md](BUILD.md)。

2026-10-27 再次出现零点几秒断声时，R1 日志抓到播放期间帧不足，未伴随收音静音。单独将该 R1 客户端 `latency` 设为 `-200`，服务器500ms加上200ms余量，保持原音频格式。调整前30秒有12次帧不足；调整后分别60秒和120秒观察均为0，仍有时钟重同步，真人听感待确认。此偏移保存在 Snapserver 数据目录的 `server.json`，不是重新编译 APK 或修改语音识别模型。该数值仅是本机对照结果，不作为所有设备的默认值。

## 恢复/应用 MA 源码

先备份当前 MA 数据目录和需要修改的源文件。upstream/ 保存两个官方 before 文件，provider/ 保存三个适配文件，upstream-manifest.json 和 patches/ 用于来源、哈希和差异核对。只覆盖固定 MA 2.10.6，不支持盲目覆盖其它版本。

如果精简镜像删除了整个 provider，可先运行下面的命令，将固定上游代码下载到指定准备目录，逐个校验 SHA；再把准备目录内容复制到实际 providers/snapcast 目录，并在 MA 自己的 Python 环境补齐 requirements.txt。不在 N1 主系统全局安装 Python 包。现有镜像中的 snapserver、动态库和 Web 资源应直接复用。

~~~sh
python fetch_upstream.py --output-dir "$PREPARED_PROVIDER_DIR"
~~~

将本目录放到容器的持久化工作目录，传入容器内实际 provider 路径：

~~~sh
python maintain_provider.py --provider-dir "$SNAPCAST_PROVIDER_DIR"
python maintain_provider.py --provider-dir "$SNAPCAST_PROVIDER_DIR" --backup-dir "$SOURCE_BACKUP_DIR" --apply
~~~

默认只读；写入前校验上游、当前适配及清单显式登记的旧适配 SHA，拒绝未知内容，先备份再原子替换。完成后重启现有 MA 容器加载源代码。--restore 恢复两个官方源，保留不再引用的新增 helper，不删除其它文件。

仓库源码以 LF 保存，清单哈希针对 Git 中的实际字节。检查同时接受仅 CRLF 换行不同的已部署副本；不忽略其他内容差异。应用时使用清单对应的原始字节，避免 Windows 换行转换使校验失效。

## MA 配置

添加 Snapcast 播放器提供者，先设缓冲 500ms、块大小 20ms、FLAC。稳定后再单独比较 300ms；不要只凭点击状态变化判断速度。

R1 Snapcast 子播放器的高级设置新增 r1_hardware_volume_url，填写自己的 R1 地址：

~~~text
http://<R1_IP>:8080/voice_volume
~~~

留空时保留标准 Snapcast 软件音量。启用后 MA 显示实际硬件百分比（15 级量化），播放时每 2 秒、空闲时每 10 秒回读外部变化；显式设置/静音/取消静音不等待轮询，直接发布设备返回的实际值。失败保留上次值，并从尝试开始计时，避免初始读取或 unity 失败后反复快速重试。先暂停播放，再设置该项，避免初次软件增益归一时意外变响。

MA 内部仍使用 1 秒调度 tick，但不会每 tick 请求 R1 或 Snapserver。共享 helper 按 provider 合并所有播放器的 Server.GetStatus，最多每 5 秒尝试一次，慢请求未结束时不会重叠；硬件音量回读采用独立时间戳。上游 provider 原本已有 2.5 秒最低间隔，所以旧版也并非每秒实际请求 Snapserver。音频规格、500ms 缓冲、unity 和硬件步进映射保持不变。

等 Snapcast 与已有卧室播放器合并后，使用 MA 正常设置页面选择 Snapcast 为首选输出。保留 AirPlay 作为回退；不直接编辑数据库。需确认原 HA 和语音网关仍指向同一逻辑队列。

## R1 客户端构建与无屏配置

见 [BUILD.md](BUILD.md)。基于官方 API21 APK，关闭强制重采样时仍保留硬件 burst 参数，并新增可选启动参数 EXTRA_PERSIST。默认不镜像 native 日志，排查可加 `--native-log`。仍使用官方服务、网络重连和 BOOT 接收器，不修改语音固件或 MediaCenter。

安装自己构建的 APK 后，设置通用环境参数并启动：

~~~sh
adb -s "$R1_ADB" shell am startservice -n de.badaix.snapcast/.SnapclientService -a ACTION_START --es EXTRA_HOST "$MA_HOST" --ei EXTRA_PORT 1704 --ez EXTRA_PERSIST true --es EXTRA_PLAYER oboe
~~~

只有 ACTION_START 且 EXTRA_PERSIST=true 时才保存 host、streamPort、autoStart=true。普通启动不改偏好；host 非空、端口有效才保存。可选 EXTRA_PLAYER 仅接受 oboe/opensl，保存到原 audioEngine 偏好；现有服务需先 ACTION_STOP 再按上式启动才切换引擎，无需再改代码或重装。R1 已验证独立 opensl 引擎启动失败，默认使用 oboe；误选后用同样停启参数恢复 oboe。

不用重启 R1，也能验证偏好读取：

~~~sh
adb -s "$R1_ADB" shell am startservice -n de.badaix.snapcast/.SnapclientService -a ACTION_STOP
adb -s "$R1_ADB" shell am broadcast -n de.badaix.snapcast/.BroadcastReceiver -a de.badaix.snapcast.START_SERVICE
~~~

广播会按已保存的服务器重新启动。实际开机依赖官方 BOOT_COMPLETED 分支；广播验证不等于真实重启验收。

## 验证与回退

已完成固定容器中的 provider 临时导入、44100:16:2 格式检查、8 项隔离音量集成检查，以及候选 APK 签名/修改内容复核。公开 helper 单元测试可在装有 aiohttp 的 Python 环境运行：

~~~sh
python -m unittest discover -s tests
~~~

轮询调整新增隔离验收见 Actions Artifacts 的 gateway 报告：23 项 localhost/模拟时钟测试通过，覆盖跨播放器 5 秒合并、慢请求不重叠、失败/取消退避、2/10 秒硬件回读、显式量化值立即发布和旧 SHA 升级保护。此次未部署到 N1，也未改变真实音乐或音量；Python 3.10 测试提取实际 player 方法运行，完整上游 player 文件仍要求 MA 的 Python 3.14。

还应逐项验证首播、立即/预取后的切歌、暂停/继续、音量/静音、至少 10 分钟长播、音乐中唤醒/收音/播报和恢复。分别记录源加载、传输、实际新音频输出时间。Snapdroid 的源码没有完整语音 duck 接口，不能先假设唤醒共存已经处理完。

回退时先在 MA 把首选输出切回 AirPlay，再停止 Snapdroid 服务；恢复代码用上述 --restore 或自己的源备份。无需卸载原语音 App。

许可证和第三方来源见 [THIRD_PARTY.md](THIRD_PARTY.md)。
