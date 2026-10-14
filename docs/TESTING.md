# 验证方式与结果边界

仓库通过 GitHub Actions 运行隔离检查，入口为 `.github/workflows/ci.yml`。每次 push、PR 或手动触发都会生成报告；在 GitHub 的 **Actions → 对应运行 → Artifacts** 下载。报告保留 14 天，不再向主分支提交每次测试的 JSON 状态快照。

## 检查分组

| 分组 | 主要检查 | 环境 |
| --- | --- | --- |
| gateway | 配置、HTTP/WS、PCM16/Float32、音乐抢占和预检复用、LRU、日志、部署入口、硬件音量轮询 | Python 3.12，deployment/requirements.txt |
| java | AI 分句、取消、续听、音量、设置缓存、PCM 编码、共享意图规则、hook 事务和构建输入契约 | Python + JDK 11 |
| ma | 固定上游下载与 SHA、精确补丁、幂等/回退、封面、预取、flow 进度 | Python 3.14，music-assistant-models 1.1.205 |
| ha | 中文句式、模板、专辑续播、音量范围、配置渲染 | Python 3.14，Home Assistant 2026.10.1 |
| frontend | 卡片定时器与 URL、模拟端点的日志页面 | Node.js、Python + Playwright Chromium |
| container | 两个架构镜像构建、显式模型下载/校验、启动健康、SIGTERM 停止 | Linux Docker，amd64 / arm64 |

MA 官方源码包含 Python 3.14 语法，不能用 Python 3.10 的解析失败判断补丁失效。各组依赖独立安装，避免将 HA 和 MA 的依赖混入同一全局环境。

从仓库根目录运行单组：

```sh
python tools/run_checks.py gateway
python tools/run_checks.py java
python tools/run_checks.py ma
python tools/run_checks.py ha
python tools/run_checks.py frontend
```

输出在被 Git 忽略的 `reports/`：每步日志与分组 JSON。命令退出码非零表示失败，不能仅凭生成了报告就认为通过。JDK 可通过进程环境 `JAVA_HOME` 指定；本地已有浏览器可设置 `R1_TEST_BROWSER`，CI 使用 Playwright 安装的 Chromium。

容器构建和运行命令见 [可选容器部署](../deployment/README.md)。这些检查不连接实际 R1 / N1、不执行电脑电源动作、不使用个人令牌或付费云 API。容器 CI 会显式下载固定运行时和模型，不发布镜像。

## 热词与识别测试

历史本地热词表含“周杰伦”“晴天”，涉及这两个词的本地测试受到定向热词辅助，不能代表无热词或任意歌名的识别能力。这两项已从热词表和实际服务移除，现在只保留通用控制词。

后续测试必须说明热词条件，不根据测试题目向热词表添加答案。评估完全无热词能力时禁用所有热词参数。当前默认云端最终转写、本地仅断句，不代表历史结果已重新完成验证。

## 什么算验证通过？

- 单元/隔离测试证明对应逻辑在指定输入和故障场景下的行为。
- 合成音频转写证明该样本能通过接口，不能代表真人远场、低音量或音乐背景准确率。
- 服务健康证明端口、进程与协议可达，不能证明云端识别质量或实际听感。
- MA 源准备、HTTP 完成、音频包到达、AudioTrack 帧推进均不是人耳首声时间。
- PCM 字节对照可检查转换是否保真，不能据此声称 Apple 音源无损或 R1 硬件 bit-perfect。

首次安装仍需现场检查暂停/恢复、自然点歌、连续播放、温湿度、普通问答和提示后续听。天气、闹钟、蓝牙切换及真实电脑开关机未全面验收。

本轮重构的 CI 与源码验证和此前现场安装分开记录。没有构建/安装的新 APK，不能继承旧 APK 的 Android ART 或真人听测结果。历史 JSON 在此前 Git 提交中保留，历史性能摘要见 [PERFORMANCE.md](PERFORMANCE.md)。
