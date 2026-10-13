# Flow 播放进度的已知限制

Snapcast 没有原生暂停。MA 2.10.6 用 STOP/RESUME 模拟，因此暂停后显示 idle，继续时重新建立流。[官方说明](https://www.music-assistant.io/player-support/snapcast/)。flow mode、缓冲或 idle threshold 设置不能改变这一语义。

另外，本轮发现 MA flow 共享播放 metadata 的问题：单曲循环预载同曲时，_load_item 默认 seek_position=0；缓存复用中央 QueueItem 的 StreamDetails，再把 seek offset 写成0。而 flow tracker 仍从该中央对象读取正在播放的 offset。

用当前源代码的缓存分支和 flow tracker 在隔离进程复现：seek146 后流时间14，正确歌曲进度应160；同曲0预载后计算变14。这可能影响 UI 进度和后续暂停恢复，并非只由 Snapcast 协议产生。

旧源实机非零 seek 的界面出现回零。仅有 UI 和部分 FFmpeg 参数不足以证明听见的音频已经回到歌头，AudioBuffer 还可能通过丢弃 PCM 实现 seek。

本仓库的 `ma/ma-optimizations.patch` 已包含针对现有 R1 队列 `upbac50e55` 的修复：同曲预载复制播放 metadata；flow playlog 跟踪本次 occurrence，开始消费时把新 buffer 所有权交回中央队列；已完成的 entry 只保留 seek 标量，释放含 PCM buffer 的 metadata 引用。保留原预载和自然循环，不覆盖活动品质映射，补齐延迟封面并保留失败可用性标记。

22 项隔离检查通过，含旧 session 交接保护、99 个历史 entry 无 buffer 引用。实机在 repeat ONE 下 seek146 后保持146→153.17秒；暂停保存155秒，继续后155→160.40秒；两次真实尾部自然循环均回到0再递增，停止后源和 transport FFmpeg 进程数为0，11项队列顺序不变。这些证据验证状态及源生命周期，未用现场麦克风确认听见的具体歌词或声学续播位置。

选择 Snapcast 时应同时考虑已验证的播放稳定性与上述功能差异。保留 AirPlay 回退；暂停/继续按钮可用，底层仍是 STOP/RESUME。升级 MA 后必须重新核对补丁与测试，不能盲目套用本版本核心源码。
