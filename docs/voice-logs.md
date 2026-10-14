# 8080 语音诊断日志

8080 导航增加独立“日志”页，原有音响、音乐、HA 和 AI 配置保留。返回原设置页时，尚未提交的表单内容仍在。

日志记录默认关闭、保存等级默认 `INFO`。打开“保存诊断日志”，选择 `DEBUG`、`INFO`、`WARN` 或 `ERROR` 后，点击“保存日志设置”才写入配置。刷新记录不会改写保存等级。只保存开启后的记录；旧记录达到上限自动轮转；不保存录音和密钥。后端每个日志文件最多 1 MiB，保留两个文件。

页面显示最近 50 条转写、分流、操作和接口结果，包括模型、通道、耗时与是否执行。只读取规定的字段，动态内容用 `textContent` 显示，URL 和常见密钥格式作额外掩码。读取失败会明确显示错误并保留上次成功记录，不会把接口失败显示为“暂无记录”。

页面与浏览器均可见时，每 5 秒刷新一次；关闭“每5秒刷新”后仍可手动刷新。最多一个请求同时进行，请求 8 秒超时。清空需要浏览器确认，只调用诊断日志清空接口，不清理音乐队列或设备配置。

## 接口

| 操作 | 方法和路径 | 请求/响应 |
| --- | --- | --- |
| 读取记录 | `GET /voice_logs?limit=50` | `{ "entries": [...] }` |
| 读取设置 | `GET /voice_logs_config` | `{ "enabled": false, "level": "INFO", "generation": 0 }` |
| 保存设置 | `POST /voice_logs_config` | 请求只包含 `enabled` 和 `level`；响应返回实际设置 |
| 清空记录 | `POST /voice_logs_clear` | 请求 `{}`；成功响应为含 `cleared: true` 的 JSON 对象 |

条目字段为 `timestamp`、`level`、`source`、`stage`、`turn` 和 `fields`。`fields` 可显示 `text`、`response`、`route`、`model`、`backend`、`operation`、`error_kind`、`status`、`duration_ms`、`audio_seconds`、`accepted`、`executed`、`request_id`。前端不写入或解释后端的 `generation`。

## 独立验证

安装测试依赖后，在仓库根目录运行：

```sh
python -m pip install playwright
python -m playwright install chromium
python device/tests/test_voice_logs_browser.py
```

也可以用 `--browser` 指定已有 Chromium/Edge 路径，用 `--playwright-path` 指定独立依赖目录，`--report` 和 `--screenshot` 指定输出文件。测试只访问模拟端点，覆盖 17 项浏览器行为，并在临时目录验证 Java 页面常量生成；不会连接音响、清空实际日志或构建/安装 APK。测试结果由 CI 上传到 Actions Artifacts；本地 `--report` 请写入 ignored `reports/`。真实设备端到端验收由安装后另外记录。

## 设备验收

9084c13b67b64f76350a806cd064d540db4f4b879a03cc87f8d9ce290a1cc3cd已安装且ART/安装后SHA256通过。真实Edge验证开启DEBUG、保存/刷新、关闭保留历史、空历史清空；只转写合成暂停、不执行，设备和网关的记录均保存。测试后恢复原disabled/INFO，保留验证条目以避免清除可能的用户记录。

耗时是对应代码阶段的测量：设备ASR包含收音及模型等待，MA完成表示后台调用返回，TTS first_audio表示网关首块发送；均不直接代表人耳首次听见声音的时刻。

模型服务失败与听不清分开显示。只要一个候选服务正常返回空文字，即使另一个故障，也可提示后续听一次；全部服务失败则退出并提示服务不可用。

## 音乐请求超时的判断

网关的 MA 记录会在“回复”字段标出接口名称，例如 `music/search` 或 `player_queues/play_media`。DEBUG 等级还记录各步骤完成耗时。这里只保存固定接口名，不保存调用参数或上游原始响应。

搜索阶段超时显示 `failed`；点播等修改请求已发送后超时或连接中断显示 `unconfirmed`，表示 MA 可能仍在执行。网关不会自动重复提交点播，也不能通过断开 HTTP 连接撤回已送达 MA 的操作。请结合 MA 当前队列和后续状态判断结果，避免连续重复点播。
