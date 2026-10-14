# HA 音乐语法与随机播放

`custom_sentences/zh-cn/r1_music.yaml` 是控制语法源，`packages/r1_apple_music.yaml` 复用现有 MA REST 接口执行操作。

## 集中设置与准备配置

`packages/` 和 `dashboards/` 是含明确占位符的模板，不能直接复制到 HA。复制 `r1_settings.example.yaml` 为不入库的 `r1_settings.yaml`，只填写四项：`queue_id`、`provider`、`r1_url`、`ma_url`。然后从仓库根目录运行：

```sh
python -m pip install PyYAML
python ha/render_config.py --settings ha/r1_settings.yaml --output-dir ha/rendered
```

渲染器严格验证设置，仅替换 `__QUEUE_ID__` 等明确 token，保留原 Jinja 模板和授权文件的 `!include`。它不连接设备、不部署、不覆盖已有不同内容。调整设置后应选择新的准备目录。输出目录中的两个 package、仪表盘和配置片段供维护者审阅后部署；`r1-ma.env.example` 提供相同 `R1_MA_QUEUE_ID`，仍需在现有 MA 容器环境中设置并重启。现有 `r1_music_authorization.yaml` 保留，不在渲染器内填写令牌。

默认队列兼容原 `upbac50e55`。默认 `provider: apple_music` 使用稳定域；[MA 2.10.6 官方 `get_provider` 实现](https://github.com/music-assistant/server/blob/c24866405bd2068c25a60e1014e5ef8c3f6445bb/music_assistant/mass.py)先匹配实例，域名则取第一个可用实例。多个 Apple 账户应明确填写目标实例 ID，避免选错账户。示例 `ma_url` 使用局域网地址，须能被 HA 和仪表盘浏览器同时访问；不能把浏览器的 `localhost` 当作 N1。

手动卡片安装使用仓库根 `r1-ha-voice.js`，复制到 HA `/config/www/r1-ha-voice.js`，资源 URL 为 `/local/r1-ha-voice.js`；HACS 安装使用 `/hacsfiles/r1-ha-voice/r1-ha-voice.js`。两种方式择一，不重复注册旧资源；自定义元素名仍为 `r1-player-card`。

| 说法 | 行为 |
| --- | --- |
| 播放、继续播放、接着放、播放音乐 | 继续当前队列；空队列使用默认流行歌单 |
| 随机播放点音乐、随便放点歌、来点音乐 | 新选默认国语流行目录歌单，关闭单曲循环，随机首曲与队列 |
| 播放国语精选、播放流行歌曲 | 按原风格别名搜索歌单 |
| 随机播放流行歌曲、随便放点国语精选 | 保留指定风格，随机播放该歌单 |
| 播放周杰伦的晴天 | 保留歌名/歌手查询，沿用用户队列随机偏好 |

泛泛随机请求使用目录歌单，不是 Apple Music 个性化推荐。查到候选后才关闭单曲循环；设置失败则不发播放请求。随机直接使用 MA `player_queues/play_media` 的 `shuffle=true`，普通点歌不传 shuffle，避免改掉用户偏好。该流程不设置音量或修改播放端参数。

裸“放”“打开”和缺少歌名的“播放周杰伦的”不属于封闭控制表。网关先判断完整控制命令，再做不完整转写保护。“播放音乐是什么意思”“随机播放是什么意思”等解释请求还会在 HA 点歌脚本入口拦截，避免通配查询被误当歌名；明确否定播放的查询也不执行点歌。

## 生成核心命令表

使用已安装 Home Assistant 的 Python 环境，依赖现有 yaml 与 hassil。无需另装服务：

~~~sh
python ha/generate_music_commands.py
~~~

默认读取本目录句式并更新 `gateway/music-commands.json`；可用 `--sentences` 和 `--output` 指定路径。表只保留核心短句，礼貌前后缀由网关统一解析，不枚举全部组合。句内“听/听听”保留，因此“放点歌听听好吗”仍兼容只移除一次请求后缀的网关。

本轮输出1538条、49,952字节；不要手工维护第二份同义词表。

## 隔离验证

在同一 HA Python 环境从仓库根目录运行：

~~~sh
python ha/tests/test_music_rules.py
~~~

测试使用实际 hassil、HA Template 及共享 `gateway/intent_rules.py`，不调用播放器或 HA 服务。除24条控制、4条查询、10条解释保护及93,168条完整变体，还验证专辑 ID 来源、跨实例隔离、图片字段/顺序回退、音量参数与滑条范围、中文百分比和非法数值。设置渲染器另用 `python -m unittest discover -s ha/tests -p 'test_render_config.py' -v` 验证。测试可通过 `--sentences`、`--package`、`--gateway` 选择候选模板源码。

直接 HA 识别的“百分之三十”由 hassil 数值列表转换为30；脚本只接受0到100的整数，不能识别的中文文字或非法数字会明确拒绝，不再被 `int` 默认转换成0。单曲点播的后续专辑 ID 优先读取 Apple 专辑映射，再遍历全部 Apple 来源 URL；后续曲目已有图片保留原字段和顺序，没有图片时先复用专辑图片，再回退首曲图片。

部署应先备份 HA 两份文件及网关表，运行 HA 配置检查，重载自定义句式/脚本后再现场验收。隔离识别通过不等于已确认新歌实际出声或播放耗时。

此前音乐语义部署的历史 JSON 可在旧 Git 提交中查看，新检查报告由 Actions Artifacts 保存。本次集中设置、专辑图片和音量校验修改仅完成隔离验证，未部署生产或操作播放；实际更新仍需 HA 配置检查与现场验收。
