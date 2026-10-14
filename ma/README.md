# 当前 MA 优化备份

仅针对 MA 2.10.6 的固定官方提交 `c24866405bd2068c25a60e1014e5ef8c3f6445bb`。仓库保存统一差异 `ma-optimizations.patch`、哈希清单和维护工具，不包含成对的全量源码快照。7 个 before 哈希均逐字节匹配该官方提交，可从官方地址可靠重建；并无额外的非官方基准。较小的 `ma-queue-environment.patch` 仅迁移已知旧优化版至可配置队列版，避免把当前已验证部署误判为未知源码；它同样受输入、输出与补丁哈希保护。

| 改动文件 | 目的 |
| --- | --- |
| providers/apple_music/streaming.py | 小规模、短时元数据缓存 |
| controllers/player_queues/stream_feeder.py | 原部署 R1 下一首预热 |
| controllers/player_queues/queue_loader.py | 拆分取流耗时，并把适用首播的补封面移到缓冲就绪后 |
| controllers/streams/controller.py | R1 DLNA 备用流的有界起始预读 |
| controllers/streams/audio.py | R1 Apple MP4 起播顺序读取；flow occurrence 独立跟踪，完成后释放历史 buffer 引用 |
| controllers/player_queues/controller.py | 原 R1 上下首按钮等待由 1 秒缩到 0.15 秒；同曲预载不重置当前进度 |
| controllers/player_queues/playback_tracker.py | flow 从本次播放的元数据或完成后的 seek 标量计算进度 |

R1 专用限制统一读取 MA 进程环境变量 `R1_MA_QUEUE_ID`，默认 `upbac50e55`，空值会拒绝启动。新部署应将它设为实际逻辑队列 ID，并同步 HA/网关的队列设置；修改后重启 MA 才生效。仅所选队列使用这些限制，不会把 R1 优化套用于所有播放器。Apple 元数据短时缓存与公共进度跟踪类保持原来的作用范围。

顺序读取仅用于原 R1 队列的 Apple 加密 MP4、从源位置 0 起播。真实非零源进度跳转保留正常 HTTP Range。没有降低音质、取消源单流限制或传输节奏。

## 核对、应用与回退

在 MA 容器对应 Python 环境执行，默认从已安装包定位源码，也可用 `--source-root` 指定 `music_assistant` 包目录：

```sh
python ma/maintain_ma_optimizations.py --check --source-root "$MA_SOURCE_ROOT"
python ma/maintain_ma_optimizations.py --apply --source-root "$MA_SOURCE_ROOT"
python ma/maintain_ma_optimizations.py --restore --source-root "$MA_SOURCE_ROOT"
```

`--check` 只读。工具校验补丁自身哈希、全部 7 个目标的 before/after 哈希、精确 hunk 上下文与结果哈希；只兼容纯 CRLF/LF 差异，拒绝未知版本或其它用户改动。验证全部通过才写入；单文件采用同目录原子替换，运行期间写入失败会恢复本次已写的文件。多文件更新不能保证突然断电下的事务原子性。重复应用/回退均不重复修改。应用或回退后由维护者重启已有 MA 容器，工具不会自动重启或操作播放。

## 隔离重建与测试

完整 MA 2.10.6 源码使用 Python 3.14 语法，测试使用 Python 3.14，并安装 `music-assistant-models==1.1.205`。从仓库根目录执行：

```sh
python -m pip install music-assistant-models==1.1.205
python ma/maintain_ma_optimizations.py --prepare "$MA_TEST_SOURCE" --cache-dir "$MA_UPSTREAM_CACHE"
export R1_MA_SOURCE_ROOT="$MA_TEST_SOURCE"
export R1_MA_CACHE_DIR="$MA_UPSTREAM_CACHE"
python -m unittest discover -s tests -p 'test_ma_*.py' -v
python ma/tests/test_flow_offset.py --source-root "$MA_TEST_SOURCE"
```

`--prepare` 仅从固定官方提交下载 7 个文件并校验 before 哈希，再套用同一补丁重建测试源码，不访问已安装 MA。缓存及测试源码应放在仓库外；缓存不匹配会报错，不会静默覆盖。需要准备原版时加 `--state before`。不设置测试目录时，测试会按需从系统临时目录中的固定官方缓存重建，首次运行需要网络；设置目录后可离线运行。测试依赖此统一补丁，不再依赖已移除的 `ma-final` 快照。

`airplay-restoration/maintain_airplay_provider.py` 记录现有 N1 的补齐方式，需要本机已有的官方恢复归档；公开仓库不包含该归档。一般完整官方 MA 镜像已有配套文件，精简镜像按环境文档核对依赖。

单曲循环时，自动下一首是当前歌曲，手动下一首是队列后继。R1 后台预取额外准备该后继的资料和未过期播放详情，最多等待 8 秒；沿用原有停止/队列切换取消机制。不创建第二音频缓冲，不改变单曲循环模式。预取未完成或详情过期时，手动切歌仍可能等待。

## Snapcast 播放路线

同一逻辑播放器可选 Snapcast 输出，保留 AirPlay 回退及原 HA 队列。
源码、来源核对、纯Python依赖、R1接收端构建和回退见 [snapcast/README.md](snapcast/README.md)。
它不要求重建 HA/MA 数据；使用本仓库七源补丁可同时修复原 R1 flow 同曲预载的进度问题。
Snapcast 官方使用flow模式，不具备原生PAUSE，暂停按STOP/RESUME模拟；
需要按实际验收确认进度、恢复耗时及与语音的共存，不能仅凭“连接成功”认定全面替代。

flow 隔离测试验证22项进度、自然循环、缓冲所有权、历史引用释放及封面/失败语义；测试不会控制实际播放器。补封面只能证明适用曲目的音频加载不等待可选图片请求，不改变 HA 的单曲/专辑查询语义。已有曲目或专辑映射图片会直接复用，不额外请求图片。实机专项历史结果和限制见 [flow 说明](snapcast/FLOW_PROGRESS_LIMITATION.md)，本次源码整理未作生产播放验收。
