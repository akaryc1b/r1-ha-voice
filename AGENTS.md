# AI 维护指南

本文件供 AI 编程助手维护仓库时阅读。面向使用者的介绍、安装入口和常见问题放在 `README.md`；不要把任务流水账、内部推理或长篇验证输出写回首页。

## 工作方式

- 先读相关代码和文档，理解实现后修改；优先复用已有 HA 规则、MA 接口和配置机制。
- 遵循 KISS、DRY、YAGNI，只解决已提出的问题，不增加未需要的服务和容器。
- 文档和新增注释使用简体中文，保留代码标识符风格。
- README 按使用者任务组织，维护约束放在本文件，测试证据放在 `docs/`。
- 历史部署记录不代表允许修改另一台设备。真实播放、音量、电源和数据操作按当前任务授权执行。

## 源码入口

| 修改内容 | 文件 |
| --- | --- |
| 8080 页面 | `device/web/`、`device/generate_web.py` |
| Android 收音、续听、音量、日志 | `device/src/r1/local/asr/`、`device/apply_*_hooks.py` |
| 网关与配置 | `gateway/voice_gateway.py`、`gateway/gateway_config.py`、`gateway/intent-rules.json` |
| 日志存储 | `gateway/event_log.py`、`docs/voice-logs.md` |
| HA 音乐语义 | `ha/custom_sentences/`、`ha/packages/`、`ha/README.md` |
| MA 优化 | `ma/ma-optimizations-manifest.json`、`ma/ma-optimizations.patch`、`ma/maintain_ma_optimizations.py` |
| Snapcast 与硬件音量 | `ma/snapcast/` |
| 本地断句、启动服务 | `asr/`、`services/`、`docs/INSTALL.md` |
| 客户端构建安装 | `device/build_client.py`、`tools/flash_r1.py`、`docs/BUILD.md` |

`device/base-apk.json` 保存允许的构建输入契约，`device/build/build-report.json` 是被忽略的本次输出。日期化文档可能包含历史 APK 哈希、模型主备顺序和部署参数，不凭旧记录推断当前设备状态。

## 环境边界

- 已验证环境：N1 ARM64 OpenWrt、HA Container 2026.10.1、MA 2.10.6、R1 Android 5.1 / API22 / ARMv7。
- 网关复用 MA Python；Sherpa 使用独立 glibc 目录。OpenWrt / HA Alpine 的 musl 与 MA Debian 的 glibc 不混用，不替换系统 libc。
- 保留已有 HA / MA 数据和账号；HA 中的 MA 集成不能代替 MA Server。
- IP、容器名、路径、队列、Apple Music provider 和实体都是示例，部署前读取实际配置。
- R1、N1、容器、浏览器分别有自己的网络视角，不混用 `localhost`。

## 行为约束

- 默认云端转写、本地断句；本地短指令优先由网页开关控制。模型、接口、密钥和预算可配置，不硬编码云模型。
- ASR 与聊天模型用途不同，接口接受模型名不能证明它能可靠转写。
- 空或不完整文字不猜测执行。任一服务正常返回空文字可续听一次；全部服务故障提示服务未响应。
- 未听清重试等真实 TTS 完成事件；新唤醒、取消、其它播报废弃旧轮次，每原轮最多重试一次。
- 连续对话独立于未听清重试，默认关闭。回复结束后短时续听，按配置限制轮数；无有效指令或故障静默结束，不重开无限循环，不为续听静音音乐。开口窗口不截断已开始的长指令，最长收音仍受网关预算约束。
- 组合计划只在 N1 生成，随最终 ASR 帧返回；音箱按当前轮次绑定计划，复用既有 HA 实例顺序执行。HA 的结构化成功响应才允许下一步，不凭“好的”等文字判断成功，不回滚已执行动作。
- 收音静音采用成对 lease，不恢复历史音量覆盖用户操作。音乐和播报音量分开处理。
- 不重置已保存的唤醒词，不恢复旧云知声识别或闲聊回退。
- 密钥只回读配置状态；留空保留，显式勾选才清除，校验失败不覆盖原配置。
- 音色下拉框保留自定义 ID；未知模型不虚构音色，读取和切换模型不自动覆盖原值。
- HA 句式是音乐语义来源，通过 `ha/generate_music_commands.py` 生成核心表；前缀、纠错和分类使用 `gateway/intent-rules.json`，Java由 `tools/generate_intent_rules.py` 生成，不维护第二套规则。
- “播放”恢复原队列，泛泛随机请求选新歌单，具体歌名和风格保留查询。
- 暂停/停止抢占尚未提交的慢搜索；已提交 MA 的播放不可事务撤回，不声称可以回滚。
- HA / 网关使用同一逻辑队列，通过 MA 配置迁移协议，不直接改数据库播放器 ID。
- Snapdroid 使用 oboe、burst 1024、44.1kHz / 16bit / stereo、FLAC；服务器缓冲500ms。2026-10-27 短断声对照将 R1 的 Snapcast 客户端 latency 改为-200ms，有效播放目标700ms，已回读持久化；后台缺帧消失，现场听感仍待确认。不要无故把客户端偏移重置为0或扩大成秒级缓冲。独立 opensl 后端曾失败，不与 oboe 内部 OpenSL 路径混淆。
- 无当前需求或新证据，不随意调整已获现场确认的编码、采样率和缓冲。
- MA 补丁只应用到清单匹配的源码；保留纯换行兼容，不绕过其它哈希差异。
- 保留 AI 分句、预算、取消、历史只提交一次的约束，推理文字不当正文朗读。
- 日志默认关闭，开启并保存后才记录；关闭留历史，清空才删除。保留等级、白名单、脱敏、非阻塞、容量和 generation 栅栏。
- 日志请求失败保留已有显示并明确提示，不显示成“暂无记录”。

## 发布内容

- 不提交真实密钥、令牌、私人配置、诊断日志、用户录音和签名私钥。
- APK、JAR、镜像、模型和运行库不进入源码备份，公开其来源、版本、校验值和构建方法。
- 不打印含密钥 HTML、完整私密配置或未过滤设备日志。
- 发布前扫描工作树与 Git 历史，不只依赖 `.gitignore`。提交、发布遵循当前授权，不强推。

## 验证与文档

先检查工作树并保留用户改动，只修改源文件。`VoiceConfigPage.java` 由网页脚本生成，不维护转义大字符串。按改动选择检查；文档修改无需启动真实播放或电源操作。

在依赖准备好的环境中，可从仓库根目录执行：

```sh
python -m unittest discover -s tests -v
python tests/ai_stream/run_tests.py
python ha/tests/test_music_rules.py
```

HA 规则检查依赖其 `hassil` 与模板环境，网关检查依赖 `aiohttp`、`numpy`。构建和其它检查见 `docs/BUILD.md`、`docs/TESTING.md`。未运行的命令不能标成通过。

- 分开报告收音、转写、路由、源准备、播放器输出和人耳听见新歌的时间。
- HTTP 成功、MA 状态、音频包到达、AudioTrack 帧推进不能代替听感验收。
- 合成转写不能证明真人远场、低音量或音乐背景中的准确率。
- 不为测试样本加入特定歌手、歌名或答案热词。通用控制热词与无热词评估要分开记录；历史定向热词测试不能当成通用识别能力的证据。
- FLAC 传输不能证明 Apple 源无损或硬件链路 bit-perfect。
- 已验证版本不代表最新上游；升级后重新检查兼容性。
- 更新对应使用说明和验证记录，区分配置、合成、真人测试，不用历史成绩冒充本次结果。


## 当前交付入口

- `deployment/` 为可选独立语音容器，不会自动迁移当前 N1 服务；镜像需实际 Linux CI 构建验证。
- `ha/packages/` 和仪表盘为 token 模板，先运行 `ha/render_config.py`，不原样复制到 HA。
- `r1-ha-voice.js` 为 HACS 单一卡片入口，元素名仍为 `r1-player-card`。
- `tools/run_checks.py` 与 CI 使用同一组命令，结果放 ignored `reports/` 并上传 Actions Artifacts，不提交每次测试快照。
- 新客户端网关上行为 PCM16，旧 Float32 仍兼容；离线 Sherpa 连接保持 Float32。网关组装 WAV 不转换采样值，但拼接仍有内存复制。
