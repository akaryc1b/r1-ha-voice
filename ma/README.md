# 当前 MA 优化备份

仅针对记录的 MA 2.10.6 源码，全部文件在写入前检查 SHA256。`ma-final` 的 before/after 文件及 patch 用于审阅与恢复，不能直接覆盖其他版本。

| 改动文件 | 目的 |
| --- | --- |
| providers/apple_music/streaming.py | 小规模、短时元数据缓存 |
| controllers/player_queues/stream_feeder.py | 原部署 R1 下一首预热 |
| controllers/player_queues/queue_loader.py | 拆分取流准备耗时 |
| controllers/streams/controller.py | R1 DLNA 备用流的有界起始预读 |
| controllers/streams/audio.py | R1 Apple MP4 起播顺序读取，避免先遍历远程分片 |
| controllers/player_queues/controller.py | 原 R1 上下首按钮等待由 1 秒缩到 0.15 秒 |

修改目标是原队列 `upbac50e55`。网页可以配置其他 MA 队列进行常规控制，但性能补丁的目标不会自动改写为新的队列；新部署需要适配与验证。

顺序读取仅用于原 R1 队列的 Apple 加密 MP4、从源位置 0 起播。真实非零源进度跳转保留正常 HTTP Range。没有降低音质、取消源单流限制或传输节奏。

`maintain_ma_optimizations.py --check` 只读；`--apply` / `--restore` 写入匹配源码后，需要重启现有 MA 容器。

`airplay-restoration/maintain_airplay_provider.py` 记录现有 N1 的补齐方式，需要本机已有的官方恢复归档；公开仓库不包含该归档。一般完整官方 MA 镜像已有配套文件，精简镜像按环境文档核对依赖。

单曲循环时，自动下一首是当前歌曲，手动下一首是队列后继。R1 后台预取额外准备该后继的资料和未过期播放详情，最多等待 8 秒；沿用原有停止/队列切换取消机制。不创建第二音频缓冲，不改变单曲循环模式。预取未完成或详情过期时，手动切歌仍可能等待。
